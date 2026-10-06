"""Rule-based checks for every draft before anyone can approve it.

Drafts come from the LLM (shrink, fit_deadline) or from code (reschedule).
Code places LLM pieces into free time, and every draft is checked again at
approval time against fresh free time.  Error messages start with the field
path so a regenerating LLM knows what to fix.
"""
from __future__ import annotations

from datetime import datetime
from itertools import pairwise
from typing import Any

from pydantic import ValidationError

from .scheduling import longest_window, minutes_between, pack, parse_windows
from .state import DRAFT_STRATEGY, PlannerState, RecoveryDraftModel


def error_path(section: str | None, loc: tuple[Any, ...]) -> str:
    parts = ((section,) if section else ()) + tuple(str(part) for part in loc)
    return ".".join(parts) or "(root)"


def remaining_minutes(state: PlannerState) -> int:
    """Work left on the task: the user's estimate, or the whole task when unknown."""
    return (state.get("check_in") or {}).get("remaining_minutes") or state["current_task"]["minutes"]


def gap_minutes(state: PlannerState) -> int:
    context = state["execution_context"]
    if context["schedule_style"] != "time_blocks":
        return 0
    return context.get("break_minutes") or 0


def piece_cap(state: PlannerState) -> int | None:
    """One focus session for time_blocks users; flexible_queue users take whole windows."""
    context = state["execution_context"]
    return context["focus_minutes"] if context["schedule_style"] == "time_blocks" else None


def shrinkable_minutes(state: PlannerState) -> int:
    """Work a shrink replaces: the task, or less when the user said less is left."""
    return min(state["current_task"]["minutes"], remaining_minutes(state))


def max_piece_minutes(state: PlannerState) -> int:
    """Longest piece a shrink may produce: shorter than the work left, and within
    one focus session for time_blocks users.  Call after the shrink precheck."""
    cap = piece_cap(state)
    longest = shrinkable_minutes(state) - 1
    return longest if cap is None else min(longest, cap)


def shrink_limits(state: PlannerState) -> dict[str, int]:
    """Size limits for a shrink, also bounded by the free time its pieces go into."""
    windows = parse_windows(state["schedule_context"]["free_windows"])
    return {
        "max_total_minutes": min(shrinkable_minutes(state) - 1, sum(minutes_between(s, e) for s, e in windows)),
        "max_piece_minutes": min(max_piece_minutes(state), longest_window(windows)),
    }


def _content(tasks: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [(t["title"], t["minutes"], t["done_when"]) for t in tasks]


def _shrink_errors(result: dict[str, Any], state: PlannerState) -> list[str]:
    work = shrinkable_minutes(state)
    min_minutes = state["min_task_minutes"]
    cap = piece_cap(state)
    errors = []
    for index, item in enumerate(result["tasks"]):
        if item["minutes"] >= work:
            errors.append(f"tasks.{index}.minutes: 축소 작업은 남은 작업({work}분)보다 짧아야 합니다.")
        elif item["minutes"] < min_minutes:
            errors.append(f"tasks.{index}.minutes: 축소 작업은 최소 {min_minutes}분 이상이어야 합니다.")
        elif cap is not None and item["minutes"] > cap:
            errors.append(f"tasks.{index}.minutes: 축소 작업이 사용자의 집중 가능 시간({cap}분)을 초과합니다.")
    total = sum(t["minutes"] for t in result["tasks"])
    if total >= work:
        errors.append(f"tasks: 축소 계획의 총 작업 시간({total}분)은 남은 작업({work}분)보다 짧아야 합니다.")
    return errors


def _fit_errors(result: dict[str, Any], state: PlannerState) -> list[str]:
    """Sizes of fresh LLM output for fit_deadline; placing it is the next step."""
    limits = state["fit_limits"]
    min_minutes = state["min_task_minutes"]
    errors = []
    for index, item in enumerate(result["tasks"]):
        if item["minutes"] < min_minutes:
            errors.append(f"tasks.{index}.minutes: 작업은 최소 {min_minutes}분 이상이어야 합니다.")
        elif item["minutes"] > limits["max_piece_minutes"]:
            errors.append(f"tasks.{index}.minutes: 작업은 {limits['max_piece_minutes']}분 이하여야 합니다.")
    total = sum(t["minutes"] for t in result["tasks"])
    if total > limits["max_total_minutes"]:
        errors.append(f"tasks: 총 작업 시간({total}분)이 마감 전 빈 시간({limits['max_total_minutes']}분)을 넘습니다.")
    return errors


def _place(result: dict[str, Any], state: PlannerState) -> list[str]:
    """Put fresh LLM pieces into free time in order; the times always come from code."""
    windows = parse_windows(state["schedule_context"]["free_windows"])
    placements = pack([t["minutes"] for t in result["tasks"]], windows, gap=gap_minutes(state))
    if placements is None:
        return [f"tasks: 작업을 순서대로 빈 시간에 넣을 수 없습니다. 가장 긴 빈 시간은 {longest_window(windows)}분입니다."]
    for item, (start, end) in zip(result["tasks"], placements, strict=True):
        item["start"], item["end"] = start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes")
    return []


def _placement_errors(result: dict[str, Any], state: PlannerState) -> list[str]:
    """Timed drafts must sit in free time from now on, without overlaps."""
    schedule = state.get("schedule_context")
    if not schedule:
        return ["schedule_context: 시간 배치에 필요한 빈 시간 정보가 없습니다."]
    now = datetime.fromisoformat(schedule["now"])
    windows = parse_windows(schedule["free_windows"])
    min_minutes = state["min_task_minutes"]
    cap = piece_cap(state)
    errors: list[str] = []
    spans = []
    for index, item in enumerate(result["tasks"]):
        try:
            start, end = datetime.fromisoformat(item["start"]), datetime.fromisoformat(item["end"])
        except (TypeError, ValueError):
            errors.append(f"tasks.{index}: 배치 시각이 없거나 올바르지 않습니다.")
            continue
        if minutes_between(start, end) != item["minutes"]:
            errors.append(f"tasks.{index}: 배치 시간과 작업 시간이 다릅니다.")
        if start < now:
            errors.append(f"tasks.{index}: 이미 지난 시각에 배치할 수 없습니다.")
        elif not any(ws <= start and end <= we for ws, we in windows):
            errors.append(f"tasks.{index}: 빈 시간이 아닌 곳에 배치되었습니다.")
        if item["minutes"] < min_minutes:
            errors.append(f"tasks.{index}.minutes: 작업은 최소 {min_minutes}분 이상이어야 합니다.")
        if cap is not None and item["minutes"] > cap:
            errors.append(f"tasks.{index}.minutes: 작업이 사용자의 집중 가능 시간({cap}분)을 초과합니다.")
        spans.append((start, end))
    spans.sort()
    if any(a_end > b_start for (_, a_end), (b_start, _) in pairwise(spans)):
        errors.append("tasks: 배치 시각이 서로 겹칩니다.")

    placed = sum(t["minutes"] for t in result["tasks"])
    remaining = remaining_minutes(state)
    if result["kind"] == "reschedule" and placed + result["carry_over_minutes"] != remaining:
        errors.append(f"tasks: 배치 {placed}분과 이월 {result['carry_over_minutes']}분의 합이 남은 작업 {remaining}분과 다릅니다.")
    if result["kind"] == "fit_deadline" and placed >= remaining:
        errors.append(f"tasks: 마감에 맞춘 계획({placed}분)은 남은 작업({remaining}분)보다 짧아야 합니다.")
    return errors


def draft_errors(
    draft: object, state: PlannerState, *, place: bool = False,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate any draft kind against the current task; never trust its producer.

    ``place`` is for freshly generated drafts: code places the LLM's pieces
    before the placement check.  A stored draft under approval keeps its times.
    """
    try:
        parsed = RecoveryDraftModel.model_validate(draft)
    except ValidationError as exc:
        return None, [f"{error_path(None, error['loc'])}: {error['msg']}" for error in exc.errors()]

    result = parsed.model_dump()
    errors: list[str] = []
    if result["replaces_task_id"] != state["current_task"]["id"]:
        errors.append("replaces_task_id: 복구 대상 작업이 현재 작업과 일치하지 않습니다.")
    if DRAFT_STRATEGY[result["kind"]] != state.get("strategy"):
        errors.append(f"kind: {result['kind']} 초안은 {state.get('strategy')} 복구로 처리할 수 없습니다.")
    if result["kind"] == "shrink":
        errors += _shrink_errors(result, state)
    elif result["kind"] == "fit_deadline" and place and state.get("fit_limits"):
        errors += _fit_errors(result, state)
    if not errors and place and result["kind"] != "reschedule":
        errors += _place(result, state)
    if not errors:
        errors += _placement_errors(result, state)

    pending = state.get("pending_draft")
    if state.get("decision") == "revise" and pending and _content(result["tasks"]) == _content(pending.get("tasks", [])):
        # An LLM can claim it applied feedback while returning the same draft.
        errors.append("tasks: 이전 초안과 같습니다. userFeedback을 반영해 고쳐야 합니다.")
    return result, errors
