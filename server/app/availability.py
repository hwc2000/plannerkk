"""Time the user cannot plan in, kept by the user and subtracted by code.

Weekly availability (``settings.slots``) says when the user can plan.  Two
user-level lists say when they cannot, and every project shares them:

- ``fixedSchedule``: weekly fixed commitments (classes, work), editable any time.
- ``blockedTimes``: hours taken out on one date ("this Wednesday evening").

Placement subtracts both whenever tasks are placed, so the user never unticks
those hours by hand.  Saving either moves the open tasks that now collide into
the earliest free time; a task that no longer fits the week is listed as not
placed, with the reason.
"""
from collections import namedtuple
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .execution_scheduler import availability_windows
from .plan_merge import entry_owner

MAX_FIXED_BLOCKS = 30
MAX_BLOCKED_TIMES = 50
MOVE_GAP_MINUTES = 5  # the same rest a placed task gets before the next one
FIRST_HOUR, LAST_HOUR = 8, 23  # the hours weekly availability can hold
KST = timezone(timedelta(hours=9))
UNPLACED_REASON = "고정 일정이나 비워 둔 시간과 겹쳐 옮기려 했지만, 이번 주 남은 빈 시간에 들어가지 않습니다."
SlotKey = namedtuple("SlotKey", "day hour")


@dataclass(frozen=True)
class Busy:
    """Unavailable time on one date; the same shape as a calendar event."""
    date: date
    startTime: time
    endTime: time


class FixedBlock(BaseModel):
    """A weekly commitment: the same hours on each of ``days`` (Monday = 0)."""
    model_config = ConfigDict(extra="forbid")
    id: str | None = Field(default=None, max_length=100)
    days: list[int] = Field(min_length=1, max_length=7)
    start: time
    end: time

    @model_validator(mode="after")
    def valid(self):
        if any(type(d) is not int or not 0 <= d <= 6 for d in self.days) or len(set(self.days)) != len(self.days):
            raise ValueError("요일을 다시 골라 주세요.")
        if self.start.tzinfo or self.end.tzinfo or self.start >= self.end:
            raise ValueError("고정 일정의 종료 시간은 시작 시간보다 늦어야 해요. 자정을 넘으면 나눠서 추가해 주세요.")
        return self


class BlockedTime(BaseModel):
    """Hours taken out on one date; the end hour is not included."""
    model_config = ConfigDict(extra="forbid")
    id: str | None = Field(default=None, max_length=100)
    date: date
    startHour: int = Field(ge=FIRST_HOUR, le=LAST_HOUR - 1, strict=True)
    endHour: int = Field(ge=FIRST_HOUR + 1, le=LAST_HOUR, strict=True)

    @model_validator(mode="after")
    def ordered(self):
        if self.startHour >= self.endHour:
            raise ValueError("비워 둘 시간의 끝은 시작보다 늦어야 해요.")
        return self


def local_today() -> date:
    return datetime.now(KST).date()


def fixed_schedule_value(blocks: list[FixedBlock]) -> list[dict]:
    """Stored form; two blocks on the same day may not overlap."""
    result = []
    for block in blocks:
        for other in result:
            if set(block.days) & set(other["days"]) and block.start < time.fromisoformat(other["end"]) \
                    and time.fromisoformat(other["start"]) < block.end:
                raise ValueError("같은 요일에 겹치는 고정 일정이 있어요. 시간을 확인해 주세요.")
        result.append({"id": block.id or f"fixed-{len(result) + 1}", "days": sorted(block.days),
                       "start": block.start.strftime("%H:%M"), "end": block.end.strftime("%H:%M")})
    if len({b["id"] for b in result}) != len(result):
        raise ValueError("고정 일정 식별자가 중복되었습니다.")
    return result


def blocked_times_value(items: list[BlockedTime], today: date) -> list[dict]:
    """Stored form, oldest first; past dates are dropped and repeats kept once."""
    result, seen = [], set()
    for item in sorted(items, key=lambda i: (i.date, i.startHour)):
        key = (item.date, item.startHour, item.endHour)
        if item.date < today or key in seen:
            continue
        seen.add(key)
        result.append({"id": item.id or f"blocked-{item.date.isoformat()}-{item.startHour}-{item.endHour}",
                       "date": item.date.isoformat(), "startHour": item.startHour, "endHour": item.endHour})
    return result


def busy_times(state: dict, start: date, days: int = 7) -> list[Busy]:
    """The fixed schedule and the blocked hours that fall in ``days`` days from ``start``."""
    result = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        for block in state.get("fixedSchedule") or []:
            if day.weekday() in block["days"]:
                result.append(Busy(day, time.fromisoformat(block["start"]), time.fromisoformat(block["end"])))
        for item in state.get("blockedTimes") or []:
            if item["date"] == day.isoformat():
                result.append(Busy(day, time(item["startHour"]), time(item["endHour"])))
    return result


def entry_busy(entry: dict) -> Busy:
    start, end = datetime.fromisoformat(entry["start"]), datetime.fromisoformat(entry["end"])
    return Busy(start.date(), start.time(), end.time())


def slot_keys(state: dict) -> list[SlotKey]:
    return [SlotKey(s["day"], s["hour"]) for s in state["settings"]["slots"]]


def _clashes(entry: dict, blocked: list) -> bool:
    start, end = datetime.fromisoformat(entry["start"]), datetime.fromisoformat(entry["end"])
    return any(datetime.combine(b.date, b.startTime) < end and start < datetime.combine(b.date, b.endTime)
               for b in blocked)


def _plan_projects(plan: dict) -> dict:
    return {p["id"]: p for p in plan.get("projects") or ([plan["project"]] if plan.get("project") else [])}


def relocate(state: dict, events=(), now: datetime | None = None) -> dict:
    """Move open tasks of the current plan out of time that is no longer available.

    Every project's tasks are checked: the fixed schedule and blocked hours
    belong to the user.  A moved task keeps its id, length, project and deadline
    and goes to the earliest free time from where it was, else earlier in the
    week.  A starter only leads its day's first task, so it is dropped rather
    than moved.  Returns the titles that moved and the ones that did not fit.
    """
    result = {"moved": [], "unplaced": []}
    plan = state.get("plan")
    if not plan:
        return result
    now = now or datetime.now(KST).replace(tzinfo=None, second=0, microsecond=0)
    start = date.fromisoformat(plan["startDate"])
    blocked = [*busy_times(state, start), *events]
    hit = [e for e in plan["entries"] if e["kind"] == "task" and not e.get("completed")
           and datetime.fromisoformat(e["end"]) > now and _clashes(e, blocked)]
    if not hit:
        return result
    hit_ids, hit_ends = {e["id"] for e in hit}, {e["end"] for e in hit}
    # A break right after a task leaves with it.
    kept = [e for e in plan["entries"] if e["id"] not in hit_ids and not (e["kind"] == "break" and e["start"] in hit_ends)]
    windows = availability_windows(start, slot_keys(state), [*blocked, *map(entry_busy, kept)], now=now)
    projects = _plan_projects(plan)
    for entry in sorted(hit, key=lambda e: e["start"]):
        if entry.get("starter"):
            continue
        project = projects.get(entry_owner(plan, entry))
        first = (project or {}).get("startDate")
        due = entry.get("dueDate") or (project or {}).get("dueDate")
        original = datetime.fromisoformat(entry["start"])
        order = sorted(range(len(windows)), key=lambda i: (windows[i][0] < original, windows[i][0]))
        placed = None
        for i in order:
            begin, end = windows[i]
            day = begin.date().isoformat()
            if (first and day < first) or (due and day > due) or end - begin < timedelta(minutes=entry["minutes"]):
                continue
            placed = (begin, begin + timedelta(minutes=entry["minutes"]))
            rest = placed[1] + timedelta(minutes=MOVE_GAP_MINUTES)
            windows[i:i + 1] = [(rest, end)] if rest < end else []
            break
        if placed:
            kept.append({**entry, "start": placed[0].isoformat(timespec="minutes"),
                         "end": placed[1].isoformat(timespec="minutes")})
            result["moved"].append(entry["title"])
        else:
            task = {k: entry[k] for k in ("title", "minutes", "doneWhen", "dueDate")}
            if entry.get("projectId") is not None:
                task["projectId"] = entry["projectId"]
            plan.setdefault("pendingTasks", []).append({**task, "reason": UNPLACED_REASON})
            result["unplaced"].append(entry["title"])
    plan["entries"] = sorted(kept, key=lambda e: (e["start"], e["kind"] != "task"))
    _close_stale_recovery_drafts(state, hit_ids, blocked)
    return result


def _close_stale_recovery_drafts(state: dict, moved_ids: set, blocked: list) -> None:
    """A waiting recovery draft for a moved task, or one offering blocked time, no longer holds."""
    from .adaptive.local import KEEP_CURRENT_PLAN, close_draft, drafts_for_plan  # adaptive.local imports this module's users
    for task_id, draft in list(drafts_for_plan(state).items()):
        offered = [t for t in draft["draft"].get("tasks", []) if t.get("start") and t.get("end")]
        if task_id in moved_ids or any(_clashes(t, blocked) for t in offered):
            close_draft(state, task_id, KEEP_CURRENT_PLAN)
