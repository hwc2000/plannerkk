from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from .execution_profile import object_schema

TASK_SCHEMA = object_schema({"tasks": {"type": "array", "items": object_schema({
    "title": {"type": "string"}, "minutes": {"type": "integer"},
    "doneWhen": {"type": "string"}, "dueDate": {"type": ["string", "null"]},
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


def validate_tasks(payload, block):
    tasks = payload.get("tasks") if isinstance(payload, dict) else None
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 40:
        raise ValueError("AI 작업 목록의 개수가 올바르지 않습니다.")
    result = []
    for t in tasks:
        if not isinstance(t, dict) or type(t.get("minutes")) is not int or not 1 <= t["minutes"] <= block:
            raise ValueError("AI 작업 시간이 집중 구간을 벗어났습니다. 다시 생성해 주세요.")
        if any(not isinstance(t.get(k), str) or not 1 <= len(t[k].strip()) <= 500 for k in ("title", "doneWhen")):
            raise ValueError("AI 작업 내용이 올바르지 않습니다.")
        due = t.get("dueDate")
        if due is not None:
            try:
                due = date.fromisoformat(due).isoformat()
            except (TypeError, ValueError):
                raise ValueError("AI 마감일 형식이 올바르지 않습니다.") from None
        result.append({"title": t["title"].strip(), "minutes": t["minutes"], "doneWhen": t["doneWhen"].strip(), "dueDate": due})
    return result


def daily_budgets(windows, buffer_percent, daily_cap=None):
    """Work minutes per day: the free time minus the buffer, never above the daily cap."""
    minutes = {}
    for begin, end in windows:
        key = begin.date().isoformat()
        minutes[key] = minutes.get(key, 0) + int((end-begin).total_seconds()//60)
    budgets = {d: int(m*(100-buffer_percent)/100) for d, m in minutes.items()}
    if daily_cap is not None:
        budgets = {d: min(b, daily_cap) for d, b in budgets.items()}
    return budgets


def _starter_entry(task, start, minutes):
    action = (task.get("starter") or "").strip() or f"{task['title']} 자료를 열고 첫 단계만 해 보기"
    end = start + timedelta(minutes=minutes)
    return {"id": str(uuid4()), "kind": "task", "starter": True, "title": f"시작 행동: {action}", "minutes": minutes,
            "doneWhen": "끝나면 바로 다음 작업으로 넘어가기", "dueDate": task["dueDate"],
            "start": start.isoformat(timespec="minutes"), "end": end.isoformat(timespec="minutes"), "completed": False}


def schedule(tasks, windows, buffer_percent, *, daily_cap=None, starter_minutes=None):
    """Place tasks in order; with ``starter_minutes`` each day's first task gets a short starter before it."""
    cursors = [begin for begin, _ in windows]
    # Daily work budget leaves the rest for breaks and interruptions.
    budgets = daily_budgets(windows, buffer_percent, daily_cap)
    # Days where the cap, not the buffer, limits the work; pending reasons name it.
    cap_binds = set() if daily_cap is None else {d for d, b in daily_budgets(windows, buffer_percent).items() if b > daily_cap}
    started_days = set()
    entries, pending = [], []
    earliest = windows[0][0] if windows else datetime.max
    for raw in tasks:
        task = {k: v for k, v in raw.items() if k != "starter"}
        placed = capped = False
        for i, (_, end) in enumerate(windows):
            cursor = max(cursors[i], earliest)
            day = cursor.date().isoformat()
            lead = starter_minutes if starter_minutes and day not in started_days else 0
            finish = cursor + timedelta(minutes=lead + task["minutes"])
            if task["dueDate"] and day > task["dueDate"]:
                continue
            if finish > end:
                continue
            if budgets.get(day, 0) < lead + task["minutes"]:
                capped = capped or day in cap_binds
                continue
            if lead:
                entries.append(_starter_entry(raw, cursor, lead))
                started_days.add(day)
            start = cursor + timedelta(minutes=lead)
            entries.append({**task, "id": str(uuid4()), "kind": "task", "start": start.isoformat(timespec="minutes"),
                            "end": finish.isoformat(timespec="minutes"), "completed": False})
            budgets[day] -= lead + task["minutes"]
            cursors[i] = finish
            earliest = finish
            if finish + timedelta(minutes=5) <= end:
                pause_end = finish + timedelta(minutes=5)
                entries.append({"id": str(uuid4()), "kind": "break", "title": "휴식", "minutes": 5,
                                "doneWhen": "잠깐 쉬고 다음 작업 시작", "dueDate": None, "start": finish.isoformat(timespec="minutes"),
                                "end": pause_end.isoformat(timespec="minutes"), "completed": False})
                cursors[i] = pause_end
                earliest = pause_end
            placed = True
            break
        if not placed:
            reason = (f"하루 계획량 {daily_cap}분을 넘지 않도록 이번 주에는 넣지 않았습니다." if capped
                      else "가용 시간·여유분·마감일 안에 배치할 수 없습니다.")
            pending.append({**task, "reason": reason})
    return entries, pending
