"""Adapters for the local SQLite ExecutionStore.

Everything that knows the local document layout lives here.  When storage
moves to the shared DB, replace this module; graph.py and state.py stay.

Keys this module owns in the store document:
- ``executionRecords``: one record per accepted check-in (B's ExecutionRecord draft)
- ``recoveryDrafts``: waiting drafts keyed by task id, at most one per task
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import uuid4

from ..execution_api import BusyEvent, Slot
from ..execution_service import save_execution_record, set_recovery_action
from ..execution_scheduler import availability_windows
from ..execution_store import ConflictError, ExecutionStore
from .ports import PlanConflictError
from .state import RecoveryTask, ScheduleContext

KEEP_CURRENT_PLAN = "keep_current_plan"  # recoveryAction when the user rejects a draft
PLAN_REPLACED = "plan_replaced"  # recoveryAction when a new plan replaces the draft's plan
CARRY_OVER_REASON = "이번 계획의 빈 시간이 부족해 다음 계획으로 넘겼습니다."
KST = timezone(timedelta(hours=9))  # plans are stored in Asia/Seoul local time


def local_now() -> datetime:
    return datetime.now(KST).replace(tzinfo=None, second=0, microsecond=0)


def execution_context_from_profile(profile: Mapping[str, Any] | None, _records: Sequence[object]) -> dict[str, Any]:
    """Converter for ``to_execution_context`` from the local profile document."""
    if not profile:
        return {}
    prefs = profile["planningPreferences"]
    # blockMinutes falls back to a default when the user answered "모름";
    # only use it when the user actually gave a focus time.
    known_focus = profile["facts"].get("focusMinutes") is not None
    return {
        "schedule_style": prefs.get("scheduleStyle"),
        "focus_minutes": prefs["blockMinutes"] if known_focus else None,
        "break_minutes": prefs.get("breakMinutes"),
    }


def _snake_key(value: str) -> str:
    return "".join(("_" + char.lower()) if char.isupper() else char for char in value)


def profile_change_context_from_proposal(proposal: object) -> dict[str, Any]:
    """Local B ProfileUpdateProposal (camelCase) -> C profile change context."""
    if not isinstance(proposal, Mapping):
        raise ValueError("profile proposal must be a mapping")
    if proposal.get("status") != "approved" or not proposal.get("appliedProfileId"):
        raise ValueError("profile proposal must be approved and applied")
    changes = proposal.get("proposedChanges")
    if not isinstance(changes, Mapping) or not changes:
        raise ValueError("profile proposal has no changes")
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for external_name, change in changes.items():
        if not isinstance(external_name, str) or not isinstance(change, Mapping) or set(change) != {"from", "to"}:
            raise ValueError("profile proposal change is malformed")
        name = _snake_key(external_name)
        before[name] = change["from"]
        after[name] = change["to"]
    return {
        "before": before, "after": after, "changed_fields": list(before),
        "reason": proposal.get("reason"),
        "evidence_record_ids": proposal.get("evidenceRecordIds"),
        "source_profile_id": proposal.get("profileId"),
        "applied_profile_id": proposal.get("appliedProfileId"),
    }


def find_open_task(plan: Mapping[str, Any], task_id: str) -> dict[str, Any] | None:
    return next(
        (e for e in plan["entries"] if e["id"] == task_id and e["kind"] == "task" and not e["completed"]),
        None,
    )


def current_task(plan: Mapping[str, Any], task_id: str) -> RecoveryTask:
    entry = find_open_task(plan, task_id)
    if entry is None:
        raise ValueError("체크인할 작업을 찾을 수 없습니다. 이미 완료한 작업인지 확인해 주세요.")
    return {
        "id": entry["id"], "title": entry["title"], "minutes": entry["minutes"],
        "done_when": entry["doneWhen"], "recovery_depth": entry.get("recoveryDepth", 0),
    }


def record_check_in(state: dict[str, Any], task: RecoveryTask, check_in: Mapping[str, Any]) -> str:
    return save_execution_record(state, {
        'planId': state['plan']['id'], 'taskId': task['id'],
        'actualMinutes': check_in.get('actualMinutes'),
        'remainingMinutes': check_in.get('remainingMinutes'),
        'result': 'completed' if check_in['completed'] else 'incomplete',
        'reasonCode': check_in.get('reasonCode'), 'note': check_in.get('note', ''),
    }, allow_follow_up=True)


def schedule_context(
    state: Mapping[str, Any], task_id: str, events: Sequence[BusyEvent], now: datetime,
) -> ScheduleContext:
    """Free time left in the plan for moving ``task_id``.

    Availability slots minus calendar events (sent by the client, which keeps
    them) minus every plan entry, including the task's own slot: the user just
    said that time did not work.  Times proposed by other tasks' waiting drafts
    are held too, so two drafts never offer the same free time.  The plan's
    buffer is not held back: it exists to absorb exactly this kind of recovery.
    """
    plan = state["plan"]
    entry = next(e for e in plan["entries"] if e["id"] == task_id)
    deadline = entry.get("dueDate") or (plan.get("project") or {}).get("dueDate")
    within_plan = deadline is not None and deadline <= plan["endDate"]
    held = [t for other, d in drafts_for_plan(state).items() if other != task_id
            for t in d["draft"]["tasks"] if t.get("start")]
    busy = list(events) + [
        BusyEvent(date=e["start"][:10], startTime=e["start"][11:], endTime=e["end"][11:])
        for e in [*plan["entries"], *held]
    ]
    slots = [Slot(**s) for s in state["settings"]["slots"]]
    windows = availability_windows(date.fromisoformat(plan["startDate"]), slots, busy, now=now)
    if within_plan:
        cut = datetime.combine(date.fromisoformat(deadline) + timedelta(days=1), time())
        windows = [(start, min(end, cut)) for start, end in windows if start < cut]
    return {
        "now": now.isoformat(timespec="minutes"),
        "free_windows": [[s.isoformat(timespec="minutes"), e.isoformat(timespec="minutes")] for s, e in windows],
        "deadline": deadline,
        "deadline_within_plan": within_plan,
    }


def put_draft(state: dict[str, Any], task_id: str, draft: dict[str, Any] | None) -> None:
    """Set or clear the task's waiting draft; a new check-in always supersedes the old one."""
    drafts = drafts_for_plan(state)
    if draft is None:
        drafts.pop(task_id, None)
    else:
        drafts[task_id] = draft
    state["recoveryDrafts"] = drafts


def drafts_for_plan(state: Mapping[str, Any]) -> dict[str, Any]:
    """Waiting drafts of the current plan; drafts of a replaced plan are dropped."""
    plan_id = state["plan"]["id"] if state.get("plan") else None
    return {k: d for k, d in (state.get("recoveryDrafts") or {}).items() if d["planId"] == plan_id}


def find_draft(state: Mapping[str, Any], draft_id: str) -> dict[str, Any] | None:
    return next((d for d in (state.get("recoveryDrafts") or {}).values() if d["id"] == draft_id), None)


def close_draft(state: dict[str, Any], task_id: str, recovery_action: str) -> None:
    """Remove the task's draft and record what the user chose on its check-in."""
    draft = drafts_for_plan(state).get(task_id)
    put_draft(state, task_id, None)
    if draft is None:
        return
    record = next((r for r in state.get("executionRecords", []) if r["id"] == draft["recordId"]), None)
    if record is not None:
        set_recovery_action(state, record["id"], recovery_action)


def close_all_drafts(state: dict[str, Any], recovery_action: str) -> None:
    """Close every waiting draft, e.g. before a new plan replaces the current one."""
    for task_id in list(drafts_for_plan(state)):
        close_draft(state, task_id, recovery_action)
    state["recoveryDrafts"] = {}  # drafts of older plans too


def _entry(entry: Mapping[str, Any], task: Mapping[str, Any], start: datetime, end: datetime, depth: int) -> dict[str, Any]:
    return {
        "id": str(uuid4()), "kind": "task", "title": task["title"], "minutes": task["minutes"],
        "doneWhen": task["done_when"], "dueDate": entry["dueDate"],
        "start": start.isoformat(timespec="minutes"), "end": end.isoformat(timespec="minutes"),
        "completed": False, "recoveryDepth": depth,
    }


class LocalPlanWriter:
    """PlanWriter for the local store: the draft's pieces go to the times it was approved with."""

    def __init__(self, store: ExecutionStore):
        self.store = store

    def apply_recovery(
        self,
        *,
        user_id: str | None,
        project_id: str | None,
        base_revision: int,
        task_id: str,
        strategy: str,
        draft: Mapping[str, Any],
    ) -> None:
        def mutate(state: dict[str, Any]) -> None:
            plan = state.get("plan")
            entry = find_open_task(plan, task_id) if plan else None
            if entry is None:
                raise PlanConflictError
            # A reduced scope counts as a shrink; moving the same work does not.
            depth = entry.get("recoveryDepth", 0) + (draft["kind"] != "reschedule")
            others = [e for e in plan["entries"] if e is not entry]
            if not all(t["start"] and t["end"] for t in draft["tasks"]):
                raise ValueError("draft has no placement")  # validated already; never trust callers
            pieces = []
            for task in draft["tasks"]:
                if any(task["start"] < e["end"] and e["start"] < task["end"] for e in others):
                    raise PlanConflictError  # the free time was taken since the draft was checked
                start, end = datetime.fromisoformat(task["start"]), datetime.fromisoformat(task["end"])
                pieces.append(_entry(entry, task, start, end, depth))
            plan["entries"] = sorted(others + pieces, key=lambda e: e["start"])
            if draft["carry_over_minutes"]:
                plan.setdefault("pendingTasks", []).append({
                    "title": entry["title"], "minutes": draft["carry_over_minutes"], "doneWhen": entry["doneWhen"],
                    "dueDate": entry["dueDate"], "reason": CARRY_OVER_REASON,
                })
            close_draft(state, task_id, strategy)

        try:
            self.store.change(base_revision, mutate)
        except ConflictError as exc:
            raise PlanConflictError from exc
