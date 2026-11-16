"""Projects the home screen asks about: past their deadline, or left without check-ins.

People rarely open a project's conversation to say they stopped; they come back after the
deadline, or not at all.  So the home screen, which everyone sees, asks instead: record what
happened, take a break from the project, or end it.

A task without a check-in is not a failure: nobody knows whether it was done.  Such tasks are
never counted by the learning rules.  The user may record them afterwards ("late" records):
the result only (no minutes: nobody remembers minutes weeks later), and those records keep the
plan honest (done work is not planned again, unknown work stays to do) but never teach the
profile, since recalled results are not the check-ins the rules were built on.
"""
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .plan_merge import entry_owner

KST = timezone(timedelta(hours=9))
# The same minimum evidence the learning rules use: three planned tasks in a row without a word.
IDLE_MISSES = 3
LATE_RESULTS = ("completed", "partial", "not_started", "incomplete")


def now_kst() -> datetime:
    return datetime.now(KST)


def _recorded(state):
    return {(r["planId"], r["taskId"]) for r in state.get("executionRecords") or []}


def unrecorded_tasks(state, project_id, today: str):
    """The plan's tasks of this project from before today: no check-in, not checked off. Oldest first.

    Today's tasks are left out: the evening check-in for them may still come.
    """
    plan = state.get("plan")
    if not plan:
        return [], 0
    recorded = _recorded(state)
    past = sorted((e for e in plan["entries"]
                   if e["kind"] == "task" and not e.get("starter") and entry_owner(plan, e) == project_id
                   and e["start"][:10] < today), key=lambda e: e["start"])
    silent = [e for e in past if not e.get("completed") and (plan["id"], e["id"]) not in recorded]
    trailing = 0
    for entry in reversed(past):
        if entry.get("completed") or (plan["id"], entry["id"]) in recorded:
            break
        trailing += 1
    return silent, trailing


def project_attention(state, projects, now: datetime | None = None):
    """What to ask about each open project.  ``projects`` are the ones the user has not paused."""
    today = (now or now_kst()).date().isoformat()
    closed = state.get("closedProjects") or {}
    items = []
    for project in projects:
        if project.id in closed:
            continue
        silent, trailing = unrecorded_tasks(state, project.id, today)
        overdue = project.dueDate.isoformat() < today
        if not overdue and trailing < IDLE_MISSES:
            continue
        items.append({
            "projectId": project.id, "title": project.title, "dueDate": project.dueDate.isoformat(),
            "kind": "overdue" if overdue else "idle",
            "silentInRow": trailing,
            "tasks": [{"taskId": e["id"], "title": e["title"], "start": e["start"], "minutes": e["minutes"]} for e in silent],
        })
    return items


class LateItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    taskId: str
    # "incomplete": the user does not remember; the task stays to do.
    result: Literal["completed", "partial", "not_started", "incomplete"]


def save_late_records(state, plan_id, items: list[LateItem], now: datetime | None = None):
    """Results recorded after the fact, for tasks of past days that never had a check-in."""
    from .execution_service import ExecutionRecordInput, _new_record  # execution_service imports learning
    plan = state.get("plan")
    if not plan or plan["id"] != plan_id:
        raise ValueError("계획이 변경되었습니다. 다시 불러와 주세요.")
    today = (now or now_kst()).date().isoformat()
    recorded = _recorded(state)
    entries = {e["id"]: e for e in plan["entries"] if e["kind"] == "task"}
    if len({item.taskId for item in items}) != len(items):
        raise ValueError("같은 작업이 두 번 들어 있어요.")
    for item in items:
        task = entries.get(item.taskId)
        if task is None:
            raise ValueError("작업을 찾을 수 없습니다.")
        if task["start"][:10] >= today:
            raise ValueError("지난 날의 작업만 나중에 기록할 수 있어요. 오늘 작업은 체크인으로 남겨 주세요.")
        if task.get("completed") or (plan_id, task["id"]) in recorded:
            raise ValueError("이미 기록한 작업이에요.")
        request = ExecutionRecordInput(planId=plan_id, taskId=task["id"], result=item.result,
                                       actualMinutes=0 if item.result == "not_started" else None)
        record = _new_record(plan, task, request)
        record["recordedLate"] = True
        state["executionRecords"].append(record)
        task["completed"] = item.result == "completed"


def learnable(record) -> bool:
    """Records the learning rules may count: check-ins made at the time, not results recalled later."""
    return not record.get("recordedLate")
