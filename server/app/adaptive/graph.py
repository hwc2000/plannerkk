"""LangGraph planner: routes a request, then generates, validates and retries a
draft until it waits for the user's review.

Routing and loop control are rule-based so every branch is testable and
bounded.  The injected generator (later an LLM) only writes draft content, and
its output is validated before anyone can approve it.

Connected today:
- recovery / shrink: LLM splits the task, code places the pieces in free time
  (generate → validate → bounded retry)
- recovery / reschedule: code moves the remaining work into free time; when it
  cannot all fit before the deadline, the LLM cuts the scope to what fits and
  code places it (fit_deadline)
- review of a waiting draft: approve (re-validate → PlanWriter), reject, revise
new_plan and replan are routed but end in ``route_not_connected``.

The graph is stateless between requests: a waiting draft and its
revision_count are stored by the caller and passed back in for review, so the
storage can move from the local DB to the shared DB without touching the graph.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from .ports import GenerationUnavailableError, PlanConflictError, PlanWriter
from .scheduling import fill, longest_window, parse_windows
from .state import (
    REASON_STRATEGY,
    CheckInSignalModel,
    CurrentTaskModel,
    ExecutionContextModel,
    PlannerState,
    RequestModel,
    ScheduleContextModel,
)
from .validation import (
    draft_errors,
    error_path,
    gap_minutes,
    max_piece_minutes,
    piece_cap,
    remaining_minutes,
    shrink_limits,
    shrinkable_minutes,
)

RecoveryGenerator = Callable[[PlannerState], Mapping[str, Any]]

GENERATION_UNAVAILABLE = "generation_unavailable"


@dataclass(frozen=True)
class RecoveryPolicy:
    """System limits, not user traits; user values always come from the profile."""

    max_retries: int  # automatic regenerations after a validation failure
    max_revisions: int  # user "revise" requests per draft
    min_task_minutes: int  # smallest piece a shrink may produce
    max_shrink_depth: int  # shrinks allowed on the same work before other strategies are offered


def _bounded_int(name: str, value: object, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} through {high}")
    return value


def _initialize(policy: RecoveryPolicy):
    def node(_state: PlannerState) -> dict[str, Any]:
        return {
            "route": None,
            "draft": None,
            "validation_errors": [],
            "retry_count": 0,
            "retry_limit": policy.max_retries,
            "min_task_minutes": policy.min_task_minutes,
            "fit_limits": None,
            "fallback": None,
            "approval_status": "not_required",
            "profile_update_proposal": None,
            "error": None,
        }

    return node


def _collect_errors(
    model: type[Any],
    raw_value: object,
    section: str | None,
    missing_fields: list[str],
    invalid_fields: list[str],
) -> None:
    try:
        model.model_validate(raw_value)
    except ValidationError as exc:
        for error in exc.errors():
            path = error_path(section, error["loc"])
            target = missing_fields if error["type"] == "missing" else invalid_fields
            if path not in target:
                target.append(path)


def _input_errors(state: PlannerState) -> tuple[list[str], list[str]]:
    """Return field paths without allowing malformed nested state to crash a node."""
    missing_fields: list[str] = []
    invalid_fields: list[str] = []
    _collect_errors(RequestModel, dict(state), None, missing_fields, invalid_fields)
    if "request" in missing_fields or "request" in invalid_fields:
        return missing_fields, invalid_fields

    request = state["request"]
    decision = state.get("decision")
    reviews_draft = request == "review" and decision in {"approve", "revise"}
    sections = (
        ("current_task", CurrentTaskModel, request == "recovery" or reviews_draft),
        ("check_in", CheckInSignalModel, request == "recovery"),
        ("execution_context", ExecutionContextModel, False),
        ("schedule_context", ScheduleContextModel, False),
    )
    for section, model, required in sections:
        raw_value = state.get(section)
        if raw_value is None:
            if required:
                missing_fields.append(section)
            continue
        _collect_errors(model, raw_value, section, missing_fields, invalid_fields)

    required: list[str] = []
    if request == "new_plan":
        # A new plan without the user's context would be a generic plan.
        required.append("planning_context")
    if request == "review":
        required.append("decision")
        if reviews_draft:
            required += ["pending_draft", "strategy"]
        if decision == "approve":
            required.append("base_revision")
        if decision == "revise":
            required += ["user_feedback", "revision_count"]
    for field in required:
        if state.get(field) is None:
            missing_fields.append(field)
    return missing_fields, invalid_fields


def _request_input(
    *,
    missing_fields: list[str] | None = None,
    invalid_fields: list[str] | None = None,
) -> dict[str, Any]:
    fallback: dict[str, Any] = {
        "action": "request_input",
        "source": "required_input_policy",
    }
    if missing_fields:
        fallback["missing_fields"] = missing_fields
    if invalid_fields:
        fallback["invalid_fields"] = invalid_fields
    return {
        "route": "request_information",
        "approval_status": "needs_input",
        "fallback": fallback,
    }


def _fallback(state: PlannerState, *, source: str, reason: str, **extra: Any) -> dict[str, Any]:
    """End without changing the plan.

    A failed revision keeps the draft the user is reviewing; anything else
    keeps the confirmed plan.
    """
    if state.get("decision") == "revise" and state.get("pending_draft") is not None:
        return {
            "approval_status": "waiting",
            "draft": state["pending_draft"],
            "fallback": {"action": "keep_pending_draft", "source": source, "reason": reason, **extra},
        }
    return {
        "approval_status": "fallback",
        "draft": None,
        "fallback": {"action": "keep_current_plan", "source": source, "reason": reason, **extra},
    }


def _choose_other_strategy(reason: str) -> dict[str, Any]:
    return {
        "route": "request_information",
        "approval_status": "needs_input",
        "fallback": {
            "action": "choose_strategy",
            "options": ["reschedule", "replan"],
            "source": "shrink_not_possible",
            "reason": reason,
        },
    }


def _style_precheck(state: PlannerState) -> dict[str, Any] | None:
    """Both strategies size pieces by the user's planning style."""
    context = state.get("execution_context") or {}
    style = context.get("schedule_style")
    if style is None:
        return _request_input(missing_fields=["execution_context.schedule_style"])
    if style == "time_blocks" and context.get("focus_minutes") is None:
        return _request_input(missing_fields=["execution_context.focus_minutes"])
    return None


def _shrink_precheck(state: PlannerState, policy: RecoveryPolicy) -> dict[str, Any] | None:
    """Stop before calling the generator when a valid shrink cannot exist."""
    depth = state["current_task"].get("recovery_depth", 0)
    if depth >= policy.max_shrink_depth:
        # Shrinking the pieces of a shrink spirals into 5-minute tasks; a repeat
        # failure on the same work needs a different strategy (or a profile change).
        return _choose_other_strategy(f"이미 {depth}번 줄인 작업입니다. 다른 시간으로 옮기거나 계획을 다시 짜 주세요.")
    blocked = _placement_precheck(state)
    if blocked:
        return blocked
    if max_piece_minutes(state) < policy.min_task_minutes:
        return _choose_other_strategy(
            f"{shrinkable_minutes(state)}분 작업은 최소 작업 시간({policy.min_task_minutes}분) "
            "기준으로 더 나눌 수 없습니다."
        )
    if shrink_limits(state)["max_piece_minutes"] < policy.min_task_minutes:
        return _choose_other_strategy(
            f"줄인 작업을 넣을 {policy.min_task_minutes}분 이상의 빈 시간이 이번 계획에 없습니다."
        )
    return None


def _placement_precheck(state: PlannerState) -> dict[str, Any] | None:
    """Every draft is placed in free time, so its pieces need the style and the free time."""
    blocked = _style_precheck(state)
    if blocked:
        return blocked
    if not state.get("schedule_context"):
        return _request_input(missing_fields=["schedule_context"])
    return None


def _strategy_precheck(state: PlannerState, strategy: str, policy: RecoveryPolicy) -> dict[str, Any] | None:
    if strategy == "shrink":
        return _shrink_precheck(state, policy)
    if strategy == "reschedule":
        return _placement_precheck(state)
    return None


def _analyze_review(state: PlannerState, policy: RecoveryPolicy) -> dict[str, Any]:
    if state["decision"] == "approve":
        # Approval re-checks the placements against fresh free time.
        return _placement_precheck(state) or {"route": "review"}
    if state["decision"] != "revise":
        return {"route": "review"}
    count = state["revision_count"]
    if count >= policy.max_revisions:
        # Revising is over; the user can still approve or reject the waiting draft.
        return {
            "route": "review",
            "approval_status": "waiting",
            "draft": state["pending_draft"],
            "fallback": {
                "action": "approve_or_reject",
                "source": "revision_limit",
                "revision_limit": policy.max_revisions,
            },
        }
    blocked = _strategy_precheck(state, state["strategy"], policy)
    if blocked:
        return blocked
    return {"route": "review", "revision_count": count + 1}


def _analyze_execution(policy: RecoveryPolicy):
    def node(state: PlannerState) -> dict[str, Any]:
        missing_fields, invalid_fields = _input_errors(state)
        if missing_fields or invalid_fields:
            return _request_input(
                missing_fields=missing_fields,
                invalid_fields=invalid_fields,
            )
        if state["request"] == "new_plan":
            return {"route": "new_plan"}
        if state["request"] == "review":
            return _analyze_review(state, policy)

        check_in = CheckInSignalModel.model_validate(state["check_in"])
        if check_in.completed:
            return {"route": "continue", "approval_status": "not_required"}

        # A strategy the user picked wins over the one derived from the reason.
        strategy = state.get("strategy") or REASON_STRATEGY.get(check_in.reason_code or "")
        if strategy is None:
            field = "check_in.reason_code" if check_in.reason_code is None else "strategy"
            return _request_input(missing_fields=[field])
        blocked = _strategy_precheck(state, strategy, policy)
        if blocked:
            return blocked
        return {"route": "recovery", "strategy": strategy}

    return node


def _after_analysis(state: PlannerState) -> str:
    if state["fallback"] is not None or state["route"] == "continue":
        return "finish"
    if state["route"] == "review" and state["decision"] == "reject":
        return "reject_draft"
    strategy = state.get("strategy")
    if strategy not in {"shrink", "reschedule"}:
        return "unsupported_route"
    if state["route"] == "review" and state["decision"] == "approve":
        return "validate_approval"
    return "generate_recovery" if strategy == "shrink" else "plan_reschedule"


def _format(start: Any) -> str:
    return start.strftime("%m/%d %H:%M")


def _plan_reschedule(policy: RecoveryPolicy):
    def node(state: PlannerState) -> dict[str, Any]:
        """Move the remaining work into free time, earliest first, without wasting any.

        If it all fits (or may spill into the next plan), the draft is built by
        code.  If the deadline makes that impossible, the LLM is asked to cut the
        scope to the free time that is left (fit_deadline).
        """
        task = state["current_task"]
        schedule = state["schedule_context"]
        windows = parse_windows(schedule["free_windows"])
        remaining = remaining_minutes(state)
        placements, left = fill(
            remaining, windows,
            min_piece=policy.min_task_minutes, max_piece=piece_cap(state), gap=gap_minutes(state),
        )
        placed = remaining - left
        if left and schedule["deadline_within_plan"]:
            if placed < policy.min_task_minutes:
                return {
                    "route": "request_information",
                    "approval_status": "needs_input",
                    "fallback": {
                        "action": "choose_strategy",
                        "options": ["replan"],
                        "source": "no_time_before_deadline",
                        "reason": f"마감({schedule['deadline']}) 전에 쓸 수 있는 빈 시간이 없습니다. "
                                  "가용 시간을 늘리거나 다른 작업의 우선순위를 조정해야 합니다.",
                    },
                }
            cap = piece_cap(state)
            longest = longest_window(windows)
            return {"fit_limits": {
                "max_total_minutes": placed,
                "max_piece_minutes": longest if cap is None else min(cap, longest),
            }}

        count = len(placements)
        tasks = [
            {
                "title": task["title"] if count == 1 else f"{task['title']} ({i}/{count})",
                "minutes": int((end - start).total_seconds() // 60),
                "done_when": task["done_when"] if i == count else f"{task['done_when']} — {i}/{count} 구간까지 진행",
                "start": start.isoformat(timespec="minutes"),
                "end": end.isoformat(timespec="minutes"),
            }
            for i, (start, end) in enumerate(placements, 1)
        ]
        # Reasons are written by code from the placement, so they are always true.
        spots = ", ".join(f"{_format(s)}~{e.strftime('%H:%M')}({t['minutes']}분)" for (s, e), t in zip(placements, tasks))
        reasons = [f"남은 {remaining}분을 가장 이른 빈 시간부터 채웠습니다: {spots}" if tasks
                   else f"이번 계획에는 남은 {remaining}분을 넣을 빈 시간이 없습니다."]
        if left:
            reasons.append(f"넣지 못한 {left}분은 다음 계획으로 넘깁니다.")
        return {"draft": {
            "kind": "reschedule", "replaces_task_id": task["id"], "tasks": tasks,
            "applied_reasons": reasons, "carry_over_minutes": left,
        }}

    return node


def _after_reschedule_plan(state: PlannerState) -> str:
    if state["fallback"] is not None:
        return "finish"
    if state["fit_limits"]:
        return "generate_recovery"
    if state.get("decision") == "revise":
        return "revise_not_supported"  # the same free time gives the same placement
    return "validate_recovery"


def _revise_not_supported(state: PlannerState) -> dict[str, Any]:
    return _fallback(
        state,
        source="revise_not_supported",
        reason="시간 재배치안은 빈 시간에서 계산한 결과라 피드백으로 바꿀 수 없습니다. "
               "승인·거절하거나 strategy를 shrink로 바꿔 수정을 요청해 주세요.",
    )


def _generate_recovery(generator: RecoveryGenerator):
    def node(state: PlannerState) -> dict[str, Any]:
        try:
            draft = dict(generator(state))
        except GenerationUnavailableError:
            return {
                "draft": None,
                "error": GENERATION_UNAVAILABLE,
                "validation_errors": ["AI 서비스를 사용할 수 없습니다. API 키와 사용 한도를 확인해 주세요."],
            }
        except Exception:  # noqa: BLE001 - LLM/network boundary; keep details out of state
            return {
                "draft": None,
                "error": "recovery_generation_failed",
                "validation_errors": ["복구 계획 생성에 실패했습니다."],
            }
        # The graph, not the generator, decides what kind of draft this is.
        draft["kind"] = "fit_deadline" if state.get("fit_limits") else "shrink"
        return {"draft": draft, "error": None}

    return node


def _validate_recovery(state: PlannerState) -> dict[str, Any]:
    draft = state.get("draft")
    if draft is None:
        return {"validation_errors": state.get("validation_errors") or ["복구 계획이 없습니다."]}
    parsed, errors = draft_errors(draft, state, place=True)
    result: dict[str, Any] = {"validation_errors": errors}
    if parsed is not None:
        result["draft"] = parsed
    return result


def _after_validation(state: PlannerState) -> str:
    if not state["validation_errors"]:
        return "await_approval"
    if state["error"] == GENERATION_UNAVAILABLE or (state.get("draft") or {}).get("kind") == "reschedule":
        return "safe_fallback"  # a retry would fail the same way (no key, or a code-built draft)
    if state["retry_count"] < state["retry_limit"]:
        return "prepare_retry"
    return "safe_fallback"


def _prepare_retry(state: PlannerState) -> dict[str, Any]:
    return {
        "retry_count": state["retry_count"] + 1,
        "draft": None,
    }


def _await_approval(_state: PlannerState) -> dict[str, Any]:
    return {"approval_status": "waiting"}


def _safe_fallback(state: PlannerState) -> dict[str, Any]:
    if state["error"] == GENERATION_UNAVAILABLE:
        return _fallback(
            state,
            source=GENERATION_UNAVAILABLE,
            reason="AI 서비스를 사용할 수 없어 복구 계획을 만들지 못했습니다.",
        )
    return _fallback(
        state,
        source="validation_policy",
        reason="복구 계획이 검증을 통과하지 못했습니다.",
        validation_errors=state["validation_errors"],
    )


def _unsupported_route(state: PlannerState) -> dict[str, Any]:
    return _fallback(
        state,
        source="route_not_connected",
        reason=f"{state.get('strategy') or state['route']} 경로는 아직 연결되지 않았습니다.",
    )


def _reject_draft(_state: PlannerState) -> dict[str, Any]:
    return {
        "approval_status": "rejected",
        "draft": None,
        "fallback": {"action": "keep_current_plan", "source": "user_rejected"},
    }


def _validate_approval(state: PlannerState) -> dict[str, Any]:
    # Re-check the stored draft: the task or profile may have changed since
    # it was generated, and an invalid draft must never reach storage.
    parsed, errors = draft_errors(state["pending_draft"], state)
    if errors:
        return {
            "validation_errors": errors,
            **_fallback(
                state,
                source="approval_validation",
                reason="승인하려는 초안이 현재 작업 기준 검증을 통과하지 못했습니다.",
                validation_errors=errors,
            ),
        }
    return {"draft": parsed, "validation_errors": []}


def _after_approval_check(state: PlannerState) -> str:
    return "finish" if state["fallback"] is not None else "apply_approved"


def _apply_approved(writer: PlanWriter | None):
    def node(state: PlannerState) -> dict[str, Any]:
        if writer is None:
            return _fallback(
                state,
                source="writer_not_connected",
                reason="승인된 계획을 저장할 저장소가 아직 연결되지 않았습니다.",
            )
        try:
            writer.apply_recovery(
                user_id=state.get("user_id"),
                project_id=state.get("project_id"),
                base_revision=state["base_revision"],
                task_id=state["current_task"]["id"],
                strategy=state["strategy"],
                draft=state["draft"],
            )
        except PlanConflictError:
            return _fallback(
                state,
                source="plan_changed",
                reason="초안을 만든 뒤 계획이 바뀌었습니다. 다시 생성해 주세요.",
            )
        except Exception:  # noqa: BLE001 - storage may be a network DB; keep details out of state
            return {
                "error": "plan_apply_failed",
                **_fallback(state, source="storage_error", reason="계획을 저장하지 못했습니다."),
            }
        return {"approval_status": "approved"}

    return node


def build_adaptive_planner_graph(
    recovery_generator: RecoveryGenerator,
    *,
    plan_writer: PlanWriter | None = None,
    max_retries: int = 2,
    max_revisions: int = 2,
    min_task_minutes: int = 5,
    max_shrink_depth: int = 1,
):
    """Build the planner graph without binding it to a schema or a store.

    ``recovery_generator`` and ``plan_writer`` are injected: fakes in tests,
    an LLM and a local/shared DB adapter later.  The numeric arguments are
    system limits; missing user values are asked for, never invented.
    """
    policy = RecoveryPolicy(
        max_retries=_bounded_int("max_retries", max_retries, 0, 5),
        max_revisions=_bounded_int("max_revisions", max_revisions, 0, 5),
        min_task_minutes=_bounded_int("min_task_minutes", min_task_minutes, 1, 60),
        max_shrink_depth=_bounded_int("max_shrink_depth", max_shrink_depth, 0, 3),
    )

    graph = StateGraph(PlannerState)
    graph.add_node("initialize", _initialize(policy))
    graph.add_node("analyze_execution", _analyze_execution(policy))
    graph.add_node("generate_recovery", _generate_recovery(recovery_generator))
    graph.add_node("plan_reschedule", _plan_reschedule(policy))
    graph.add_node("revise_not_supported", _revise_not_supported)
    graph.add_node("validate_recovery", _validate_recovery)
    graph.add_node("prepare_retry", _prepare_retry)
    graph.add_node("await_approval", _await_approval)
    graph.add_node("safe_fallback", _safe_fallback)
    graph.add_node("unsupported_route", _unsupported_route)
    graph.add_node("reject_draft", _reject_draft)
    graph.add_node("validate_approval", _validate_approval)
    graph.add_node("apply_approved", _apply_approved(plan_writer))

    graph.set_entry_point("initialize")
    graph.add_edge("initialize", "analyze_execution")
    graph.add_conditional_edges(
        "analyze_execution",
        _after_analysis,
        {
            "generate_recovery": "generate_recovery",
            "plan_reschedule": "plan_reschedule",
            "finish": END,
            "unsupported_route": "unsupported_route",
            "reject_draft": "reject_draft",
            "validate_approval": "validate_approval",
        },
    )
    graph.add_conditional_edges(
        "plan_reschedule",
        _after_reschedule_plan,
        {
            "generate_recovery": "generate_recovery",
            "validate_recovery": "validate_recovery",
            "revise_not_supported": "revise_not_supported",
            "finish": END,
        },
    )
    graph.add_edge("generate_recovery", "validate_recovery")
    graph.add_conditional_edges(
        "validate_recovery",
        _after_validation,
        {
            "await_approval": "await_approval",
            "prepare_retry": "prepare_retry",
            "safe_fallback": "safe_fallback",
        },
    )
    graph.add_edge("prepare_retry", "generate_recovery")
    graph.add_conditional_edges(
        "validate_approval",
        _after_approval_check,
        {"apply_approved": "apply_approved", "finish": END},
    )
    for node in ("await_approval", "safe_fallback", "unsupported_route", "reject_draft", "revise_not_supported", "apply_approved"):
        graph.add_edge(node, END)
    return graph.compile()
