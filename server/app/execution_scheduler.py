from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from .execution_profile import object_schema

TASK_SCHEMA = object_schema({"tasks": {"type": "array", "items": object_schema({
    "title": {"type": "string"}, "minutes": {"type": "integer"},
    "doneWhen": {"type": "string"}, "dueDate": {"type": ["string", "null"]},
    "projectId": {"type": ["string", "null"]},
})}})


def availability_windows(start, slots, events, project=None, now=None):
    now = now or datetime.now(timezone(timedelta(hours=9))).replace(tzinfo=None)
    result = []
    chosen = {(s.day, s.hour) for s in slots}
    for offset in range(7):
        day = start + timedelta(days=offset)
        if project and not project.startDate <= day <= project.dueDate:
            continue
        for hour in range(8, 23):
            if (day.weekday(), hour) not in chosen:
                continue
            begin = datetime.combine(day, time(hour))
            end = begin + timedelta(hours=1)
            begin = max(begin, now.replace(second=0, microsecond=0) + timedelta(minutes=1))
            if begin >= end:
                continue
            if result and result[-1][1] == begin:
                result[-1] = (result[-1][0], end)
            else:
                result.append((begin, end))
    for event in events:
        busy_start = datetime.combine(event.date, event.startTime)
        busy_end = datetime.combine(event.date, event.endTime)
        pieces = []
        for begin, end in result:
            if busy_end <= begin or busy_start >= end:
                pieces.append((begin, end))
            else:
                if begin < busy_start:
                    pieces.append((begin, busy_start))
                if busy_end < end:
                    pieces.append((busy_end, end))
        result = pieces
    return result


MAX_TASK_MINUTES = 600
MIN_PIECE_MINUTES = 10
BREAK_MINUTES = 5


def validate_tasks(payload, block, projects=()):
    """Accept the LLM's task list; long tasks are split later instead of failing the plan."""
    tasks = payload.get("tasks") if isinstance(payload, dict) else None
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("AI 작업 목록이 비어 있습니다. 다시 생성해 주세요.")
    result = []
    for t in tasks[:40]:
        if not isinstance(t, dict) or type(t.get("minutes")) is not int or not 1 <= t["minutes"] <= MAX_TASK_MINUTES:
            raise ValueError("AI 작업 시간이 올바르지 않습니다. 다시 생성해 주세요.")
        if any(not isinstance(t.get(k), str) or not 1 <= len(t[k].strip()) <= 500 for k in ("title", "doneWhen")):
            raise ValueError("AI 작업 내용이 올바르지 않습니다.")
        due = t.get("dueDate")
        if due is not None:
            try:
                due = date.fromisoformat(due).isoformat()
            except (TypeError, ValueError):
                due = None  # an unreadable deadline must not block placing the task
        task = {"title": t["title"].strip(), "minutes": t["minutes"], "doneWhen": t["doneWhen"].strip(), "dueDate": due}
        if projects:
            # One project owns every task; with several, an unknown id falls back to "no project".
            by_id = {p["id"]: p for p in projects}
            owner = projects[0] if len(projects) == 1 else by_id.get(t.get("projectId"))
            task["projectId"] = owner["id"] if owner else None
            if owner:
                task["dueDate"] = min(filter(None, (due, owner["dueDate"])))
                task["notBefore"] = owner["startDate"]
        result.append(task)
    return result


def daily_budgets(windows, buffer_percent):
    budgets = {}
    for begin, end in windows:
        key = begin.date().isoformat()
        budgets[key] = budgets.get(key, 0) + int((end-begin).total_seconds()//60)
    return {d: int(m*(100-buffer_percent)/100) for d, m in budgets.items()}


def schedule(tasks, windows, buffer_percent, max_piece=None):
    """Place tasks in order into the earliest free time.

    A task that does not fit one window is split across later windows (never into
    pieces shorter than MIN_PIECE_MINUTES) and each piece is at most ``max_piece``.
    The daily budget keeps ``buffer_percent`` of each day's free time unplanned.
    A task is either placed completely (possibly in pieces) or left pending whole.
    """
    cursors = [begin for begin, _ in windows]
    budgets = daily_budgets(windows, buffer_percent)
    entries, pending = [], []
    not_before = windows[0][0] if windows else datetime.max
    for task in tasks:
        not_before_day = task.get("notBefore")
        task = {k: v for k, v in task.items() if k != "notBefore"}
        left, pieces = task["minutes"], []
        saved = (list(cursors), dict(budgets), len(entries))
        for i, (_, end) in enumerate(windows):
            while left > 0:
                cursor = max(cursors[i], not_before)
                day = cursor.date().isoformat()
                if task["dueDate"] and day > task["dueDate"]:
                    break
                if not_before_day and day < not_before_day:
                    break  # this window is before the task's project starts
                piece = min(left, int((end - cursor).total_seconds()//60), budgets.get(day, 0))
                if max_piece:
                    piece = min(piece, max_piece)
                if 0 < left - piece < MIN_PIECE_MINUTES:
                    piece -= MIN_PIECE_MINUTES - (left - piece)  # leave a workable remainder, not a sliver
                if piece < min(left, MIN_PIECE_MINUTES):
                    break
                finish = cursor + timedelta(minutes=piece)
                pieces.append((cursor, finish))
                budgets[day] -= piece
                left -= piece
                cursors[i] = finish
                if finish + timedelta(minutes=BREAK_MINUTES) <= end:
                    pause_end = finish + timedelta(minutes=BREAK_MINUTES)
                    entries.append({"id": str(uuid4()), "kind": "break", "title": "휴식", "minutes": BREAK_MINUTES,
                                    "doneWhen": "잠깐 쉬고 다음 작업 시작", "dueDate": None, "start": finish.isoformat(timespec="minutes"),
                                    "end": pause_end.isoformat(timespec="minutes"), "completed": False})
                    cursors[i] = pause_end
            if left == 0:
                break
        if left > 0:
            cursors, budgets = saved[0], saved[1]
            del entries[saved[2]:]
            reason = "마감일 전 가용 시간이 부족합니다." if task["dueDate"] else "이번 주 가용 시간과 여유분을 모두 사용했습니다."
            pending.append({**task, "reason": reason})
            continue
        for n, (begin, finish) in enumerate(pieces, 1):
            title = f"{task['title']} ({n}/{len(pieces)})" if len(pieces) > 1 else task["title"]
            entries.append({**task, "title": title, "minutes": int((finish-begin).total_seconds()//60), "id": str(uuid4()),
                            "kind": "task", "start": begin.isoformat(timespec="minutes"),
                            "end": finish.isoformat(timespec="minutes"), "completed": False})
        # Later tasks never start before this one, so the suggested order survives.
        not_before = pieces[0][0]
    entries.sort(key=lambda e: (e["start"], e["kind"] != "task"))
    return entries, pending
