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


MIN_PIECE_MINUTES = 10
BREAK_MINUTES = 5


def min_piece(minutes):
    """The shortest part a task of ``minutes`` is cut into: half of it, so a split never leaves a sliver."""
    return min(minutes, max(MIN_PIECE_MINUTES, minutes // 2))


def min_task_minutes(block):
    """The shortest task worth its own slot for a focus block of ``block`` minutes: half of it."""
    return min_piece(block)


def validate_tasks(payload, block, projects=()):
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
        task = {"title": t["title"].strip(), "minutes": t["minutes"], "doneWhen": t["doneWhen"].strip(), "dueDate": due}
        by_id = {p["id"]: p for p in projects}
        if t.get("projectId") is not None and t.get("projectId") not in by_id:
            raise ValueError("AI 작업의 프로젝트가 올바르지 않습니다.")
        if projects:
            owner = projects[0] if len(projects) == 1 else by_id.get(t.get("projectId"))
            task["projectId"] = owner["id"] if owner else None
            if owner:
                task["dueDate"] = min(filter(None, (due, owner["dueDate"])))
                task["notBefore"] = owner["startDate"]
        result.append(task)
    return result


def daily_budgets(windows, daily_cap=None, daily_used=None):
    """Work minutes per day: the free time the plan may use, never above the daily cap.

    ``daily_used``: work other projects already hold that day, which counts against the cap.
    """
    minutes = {}
    for begin, end in windows:
        key = begin.date().isoformat()
        minutes[key] = minutes.get(key, 0) + int((end-begin).total_seconds()//60)
    if daily_cap is not None:
        minutes = {d: max(0, min(m, daily_cap - (daily_used or {}).get(d, 0))) for d, m in minutes.items()}
    return minutes


# A project whose work fills at least this share of its free time is placed earliest first.
SPREAD_FULL = 0.9


def window_owners(windows, reserved=None):
    """Who may use each window: the project whose own hours it is, or None (the shared hours)."""
    own = {owner: {tuple(w) for w in items} for owner, items in (reserved or {}).items()}
    return [next((owner for owner, items in own.items() if tuple(w) in items), None) for w in windows]


def spread_targets(tasks, windows, daily_cap=None, daily_used=None, owner_caps=None, reserved=None):
    """The first day each task may take, and how full each project's week is.

    Work that fills a project's free time (breaks between tasks included) is placed
    earliest first.  Less work than time (a few sessions a week, a short job) is not
    packed into the first day: the project's work is stretched from its first free day
    to its last, each task on the day whose start in the week's free time is nearest to where
    its share of the work begins, so three sessions in five even days land on days 1, 3 and 5.
    Free time is what the day may hold: the daily cap (less what other projects
    hold) and a project's own cap (``owner_caps``) count.  A project with hours of its
    own (``reserved``) counts only those; the others count only the shared hours.
    Returns ({task index: day}, {project: planned minutes / free minutes}).
    """
    users = window_owners(windows, reserved)
    budgets_of = {}
    for key in set(users):
        budgets_of[key] = daily_budgets([w for w, u in zip(windows, users) if u == key], daily_cap, daily_used)
    owners = {}
    for index, task in enumerate(tasks):
        owners.setdefault(task.get("projectId"), []).append(index)
    targets, fullness = {}, {}
    for owner, indexes in owners.items():
        first = max((tasks[i].get("notBefore") or "" for i in indexes), default="")
        last = max((tasks[i].get("dueDate") or "9999-12-31" for i in indexes), default="9999-12-31")
        own_cap = (owner_caps or {}).get(owner)
        budgets = budgets_of.get(owner if owner in (reserved or {}) else None, {})
        days = [(d, m if own_cap is None else min(m, own_cap)) for d, m in sorted(budgets.items()) if first <= d <= last]
        days = [(d, m) for d, m in days if m > 0]
        room = sum(m for _, m in days)
        total = sum(tasks[i]["minutes"] for i in indexes)
        fullness[owner] = (total + BREAK_MINUTES * len(indexes)) / room if room else 1.0
        if not room or fullness[owner] >= SPREAD_FULL:
            continue
        # Where each day starts in the week's free time, 0 for the first day and 1 for the last.
        span = room - days[-1][1]
        starts, before = [], 0
        for day, minutes in days:
            starts.append((day, before / span if span else 0.0))
            before += minutes
        work_span = total - tasks[indexes[-1]]["minutes"]
        done = 0
        for i in indexes:
            share = done / work_span if work_span else 0.0
            done += tasks[i]["minutes"]
            day = min(starts, key=lambda item: (abs(item[1] - share), item[1]))[0]
            due = tasks[i].get("dueDate")
            targets[i] = min(day, due) if due else day
    return targets, fullness


def _starter_entry(task, start, minutes):
    action = (task.get("starter") or "").strip() or f"{task['title']} 자료를 열고 첫 단계만 해 보기"
    end = start + timedelta(minutes=minutes)
    return {"id": str(uuid4()), "kind": "task", "starter": True, "title": f"시작 행동: {action}", "minutes": minutes,
            "doneWhen": "끝나면 바로 다음 작업으로 넘어가기", "dueDate": task["dueDate"],
            **({"projectId": task["projectId"]} if "projectId" in task else {}),
            "start": start.isoformat(timespec="minutes"), "end": end.isoformat(timespec="minutes"), "completed": False}


def schedule(tasks, windows, *, daily_cap=None, starter_minutes=None, fill_daily_cap=False, project_policies=None,
             shrink_to_fit=False, daily_used=None, pace_percent=None, reserved=None):
    """Place tasks in order; with ``starter_minutes`` each day's first task gets a short starter before it.

    A project with less work than free time is spread over the week (``spread_targets``);
    in a week of several projects, such light projects take their days first and the
    projects that fill their time go around them.  ``daily_used`` is work other projects
    already hold each day, counted against ``daily_cap``.  ``reserved`` maps a project to
    the windows that are its own hours: its tasks go only there, and no other task does
    (those projects are placed first, their time is fixed).  In a week of several projects,
    a project whose work takes longer than the time the windows were shaped for
    (``pace_percent``) gets that much free time after each of its tasks.

    ``fill_daily_cap`` cuts a task that is longer than what is left of today's plan, so the
    day is used up.  ``shrink_to_fit`` instead shortens a task to the free time it meets
    (at least half of it), so it stays one piece and later tasks still fit before the
    deadline.  Both are last resorts for an AI that keeps ignoring the day's slots.
    """
    cursors = [begin for begin, _ in windows]
    # Daily work budget leaves the rest for breaks and interruptions.
    budgets = daily_budgets(windows, daily_cap, daily_used)
    # Days where the cap, not the buffer, limits the work; pending reasons name it.
    cap_binds = set() if daily_cap is None else {d for d, b in daily_budgets(windows).items() if b > budgets.get(d, 0)}
    owner_caps = {owner: policy.daily_cap_minutes for owner, policy in (project_policies or {}).items()
                  if policy.daily_cap_minutes is not None}
    targets, fullness = spread_targets(tasks, windows, daily_cap, daily_used, owner_caps, reserved)
    users = window_owners(windows, reserved)
    reserved = reserved or {}
    order = list(range(len(tasks)))
    if project_policies or reserved:
        order.sort(key=lambda i: (tasks[i].get("projectId") not in reserved,
                                  fullness.get(tasks[i].get("projectId"), 1.0) >= SPREAD_FULL))
    base_pace = pace_percent or 100
    started_days = set()
    project_used = {}
    project_not_before = {}
    entries, pending = [], []
    not_before = windows[0][0] if windows else datetime.max
    for index in order:
        raw = tasks[index]
        task = {k: v for k, v in raw.items() if k not in ("starter", "notBefore")}
        owner = task.get("projectId")
        own_policy = (project_policies or {}).get(owner)
        own_cap = own_policy.daily_cap_minutes if own_policy else None
        # Free time after each task for work that runs long, beyond what the windows already leave.
        slack = max(0.0, (own_policy.pace_percent or base_pace) / base_pace - 1) if own_policy else 0.0
        effective_cap = min((cap for cap in (daily_cap, own_cap) if cap is not None), default=None)
        binding_days = cap_binds | ({d for d, minutes in daily_budgets(windows).items() if minutes > own_cap}
                                   if own_cap is not None else set())
        own_starter = own_policy.starter_minutes if own_policy else starter_minutes
        earliest = project_not_before.get(owner, windows[0][0] if windows else datetime.max) if project_policies else not_before
        first_day = max(filter(None, (raw.get("notBefore"), targets.get(index))), default=None)
        shortest = min_piece(task["minutes"])
        saved = (list(cursors), dict(budgets), set(started_days), len(entries), dict(project_used))
        capped = False
        usable = owner if owner in reserved else None
        for split in (False, True):
            left, pieces = task["minutes"], []
            for i, (_, end) in enumerate(windows):
                if users[i] != usable:
                    continue
                while left > 0:
                    cursor = max(cursors[i], earliest)
                    day = cursor.date().isoformat()
                    if (task["dueDate"] and day > task["dueDate"]) or (first_day and day < first_day):
                        break
                    start_key = (owner, day) if project_policies else day
                    lead = own_starter if own_starter and start_key not in started_days else 0
                    room = int((end - cursor).total_seconds()//60) - lead
                    budget = budgets.get(day, 0) - lead
                    if own_cap is not None:
                        budget = min(budget, own_cap - project_used.get((owner, day), 0) - lead)
                    piece = min(left, room, budget)
                    if shrink_to_fit and not split and not pieces and shortest <= piece < left:
                        # Minutes are an estimate: a slightly shorter task here beats losing a later one.
                        task["minutes"] = left = piece
                    # A task longer than what is left of today's plan is split so today is used up
                    # instead of skipped; otherwise later tasks fall out of the week.
                    budget_bound = fill_daily_cap and budget < min(left, room) and budget >= MIN_PIECE_MINUTES
                    if not split and piece < left and not budget_bound:
                        capped = capped or (budget < min(left, room) and day in binding_days)
                        break
                    # Filling the daily plan may leave a short piece; other splits keep half a task.
                    floor = MIN_PIECE_MINUTES if budget_bound else shortest
                    if 0 < left - piece < floor:
                        piece -= floor - (left - piece)
                    if piece < min(left, floor):
                        capped = capped or (budget < min(left, room) and day in binding_days)
                        break
                    if lead:
                        entries.append(_starter_entry(raw | task, cursor, lead))
                        started_days.add(start_key)
                    start = cursor + timedelta(minutes=lead)
                    finish = start + timedelta(minutes=piece)
                    pieces.append((start, finish))
                    budgets[day] -= lead + piece
                    project_used[(owner, day)] = project_used.get((owner, day), 0) + lead + piece
                    left -= piece
                    if slack:
                        finish = min(end, finish + timedelta(minutes=int(piece * slack)))
                    cursors[i] = finish
                    if finish + timedelta(minutes=BREAK_MINUTES) <= end:
                        pause_end = finish + timedelta(minutes=BREAK_MINUTES)
                        entries.append({"id": str(uuid4()), "kind": "break", "title": "휴식", "minutes": BREAK_MINUTES,
                                        "doneWhen": "잠깐 쉬고 다음 작업 시작", "dueDate": None, "start": finish.isoformat(timespec="minutes"),
                                        "end": pause_end.isoformat(timespec="minutes"), "completed": False})
                        cursors[i] = pause_end
                if left == 0:
                    break
            if left == 0:
                break
            cursors, budgets, started_days = list(saved[0]), dict(saved[1]), set(saved[2])
            project_used = dict(saved[4])
            del entries[saved[3]:]
        if left > 0:
            reason = (f"하루 계획량 {effective_cap}분을 넘지 않도록 이번 주에는 넣지 않았습니다." if capped
                      else "가용 시간·마감일 안에 배치할 수 없습니다.")
            pending.append({**{k: v for k, v in raw.items() if k != "starter"}, "reason": reason})
            continue
        for n, (begin, finish) in enumerate(pieces, 1):
            title = f"{task['title']} ({n}/{len(pieces)})" if len(pieces) > 1 else task["title"]
            entries.append({**task, "title": title, "minutes": int((finish-begin).total_seconds()//60), "id": str(uuid4()),
                            "kind": "task", "start": begin.isoformat(timespec="minutes"),
                            "end": finish.isoformat(timespec="minutes"), "completed": False})
        not_before = pieces[0][0]
        project_not_before[owner] = pieces[0][0]
    entries.sort(key=lambda e: (e["start"], e["kind"] != "task"))
    return entries, pending
