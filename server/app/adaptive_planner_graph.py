"""LangGraph skeleton for adapting an active plan after an execution check-in.

The graph deliberately consumes a small, normalized ``execution_context`` instead
of reaching into the team's pending UserProfile/ExecutionRecord schemas.  The
integration adapter can change later without rewriting routing nodes or loops.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, ConfigDict, Field, ValidationError


RecoveryRoute = Literal[
    "continue",
    "shrink",
    "reschedule",
    "replan",
    "request_information",
]
ApprovalStatus = Literal["not_required", "needs_input", "waiting", "fallback"]


class ExecutionContext(TypedDict):
    """Stable graph-facing view; not the final shared UserProfile schema."""

    focus_minutes: int | None
    recovery_preference: str | None
    recent_failure_count: int | None


class RecoveryTask(TypedDict):
    id: str
    title: str
    minutes: int
    done_when: str


class CheckInSignal(TypedDict):
    completed: bool
    actual_minutes: int | None
    reason_code: str | None
    note: str


class PlannerState(TypedDict, total=False):
    """State for one recovery run; durable team schemas enter through an adapter."""

    execution_context: ExecutionContext
    current_task: RecoveryTask
    check_in: CheckInSignal
    route: RecoveryRoute | None
    recovery_draft: dict[str, Any] | None
    validation_errors: list[str]
    retry_count: int
    retry_limit: int
    fallback: dict[str, Any] | None
    approval_status: ApprovalStatus
    error: str | None


RecoveryGenerator = Callable[[PlannerState], Mapping[str, Any]]
ContextConverter = Callable[[object | None, Sequence[object]], Mapping[str, Any]]


class _ExecutionContextModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    focus_minutes: int | None = Field(default=None, ge=1, strict=True)
    recovery_preference: str | None = None
    # None means "not measured yet"; zero must only come from real records.
    recent_failure_count: int | None = Field(default=None, ge=0, strict=True)


def to_execution_context(
    profile: object | None,
    records: Sequence[object],
    *,
    converter: ContextConverter,
) -> ExecutionContext:
    """Convert pending shared schemas at one replaceable integration boundary.

    The converter is required on purpose: this module must not guess the final
    UserProfile/ExecutionRecord field names or nesting.  Once teammates publish
    those contracts, only their converter implementation should need to change;
    graph nodes continue to consume the normalized ExecutionContext.
    """
    value = _ExecutionContextModel.model_validate(converter(profile, records))
    return value.model_dump()  # type: ignore[return-value]


class _DraftTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    minutes: int = Field(gt=0, strict=True)
    done_when: str = Field(min_length=1, max_length=500)


class _CurrentTaskModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=500)
    minutes: int = Field(gt=0, strict=True)
    done_when: str = Field(min_length=1, max_length=500)


class _CheckInSignalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completed: bool = Field(strict=True)
    actual_minutes: int | None = Field(default=None, ge=0, strict=True)
    reason_code: Literal[
        "task_too_large",
        "time_shortage",
        "interruption",
        "priority_changed",
    ] | None = None
    note: str = Field(default="", max_length=1500)


class _RecoveryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replaces_task_id: str = Field(min_length=1)
    tasks: list[_DraftTask] = Field(min_length=1, max_length=20)
    applied_reasons: list[str] = Field(min_length=1, max_length=10)


def _initialize(max_retries: int):
    def node(_state: PlannerState) -> dict[str, Any]:
        return {
            "route": None,
            "recovery_draft": None,
            "validation_errors": [],
            "retry_count": 0,
            "retry_limit": max_retries,
            "fallback": None,
            "approval_status": "not_required",
            "error": None,
        }

    return node


def _input_errors(state: PlannerState) -> tuple[list[str], list[str]]:
    """Return field paths without allowing malformed nested state to crash a node."""
    missing_fields: list[str] = []
    invalid_fields: list[str] = []
    sections = (
        ("current_task", state.get("current_task"), _CurrentTaskModel),
        ("check_in", state.get("check_in"), _CheckInSignalModel),
    )
    for section, raw_value, model in sections:
        if raw_value is None:
            missing_fields.append(section)
            continue
        try:
            model.model_validate(raw_value)
        except ValidationError as exc:
            for error in exc.errors():
                path = ".".join((section, *(str(part) for part in error["loc"])))
                target = missing_fields if error["type"] == "missing" else invalid_fields
                if path not in target:
                    target.append(path)

    context = state.get("execution_context")
    if context is not None:
        try:
            _ExecutionContextModel.model_validate(context)
        except ValidationError as exc:
            for error in exc.errors():
                path = ".".join(("execution_context", *(str(part) for part in error["loc"])))
                target = missing_fields if error["type"] == "missing" else invalid_fields
                if path not in target:
                    target.append(path)
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


def _analyze_execution(state: PlannerState) -> dict[str, Any]:
    missing_fields, invalid_fields = _input_errors(state)
    if missing_fields or invalid_fields:
        return _request_input(
            missing_fields=missing_fields,
            invalid_fields=invalid_fields,
        )

    check_in = _CheckInSignalModel.model_validate(state["check_in"])
    context = state.get("execution_context")
    if check_in.completed:
        return {"route": "continue", "approval_status": "not_required"}

    reason = check_in.reason_code
    route: RecoveryRoute
    if reason == "task_too_large":
        route = "shrink"
    elif reason in {"time_shortage", "interruption"}:
        route = "reschedule"
    elif reason == "priority_changed":
        route = "replan"
    else:
        return _request_input(missing_fields=["check_in.reason_code"])

    if route == "shrink" and (not context or context.get("focus_minutes") is None):
        return _request_input(missing_fields=["execution_context.focus_minutes"])
    return {"route": route}


def _after_analysis(state: PlannerState) -> str:
    if state["route"] == "shrink":
        return "generate_recovery"
    if state["route"] in {"continue", "request_information"}:
        return "finish"
    return "unsupported_route"


def _generate_recovery(generator: RecoveryGenerator):
    def node(state: PlannerState) -> dict[str, Any]:
        try:
            return {"recovery_draft": dict(generator(state)), "error": None}
        except Exception:  # generator may later be an LLM/network boundary
            return {
                "recovery_draft": None,
                "error": "recovery_generation_failed",
                "validation_errors": ["복구 계획 생성에 실패했습니다."],
            }

    return node


def _validate_recovery(state: PlannerState) -> dict[str, Any]:
    errors: list[str] = []
    draft = state.get("recovery_draft")
    task = state["current_task"]
    focus_minutes = state["execution_context"]["focus_minutes"]
    if draft is None:
        return {"validation_errors": state.get("validation_errors") or ["복구 계획이 없습니다."]}
    try:
        parsed = _RecoveryDraft.model_validate(draft)
    except ValidationError as exc:
        return {"validation_errors": [error["msg"] for error in exc.errors()]}
    if parsed.replaces_task_id != task["id"]:
        errors.append("복구 대상 작업이 현재 작업과 일치하지 않습니다.")
    if focus_minutes is None:
        errors.append("집중 가능 시간이 필요합니다.")
    elif any(item.minutes > focus_minutes for item in parsed.tasks):
        errors.append("축소 작업이 사용자의 집중 가능 시간을 초과합니다.")
    if sum(item.minutes for item in parsed.tasks) > task["minutes"]:
        errors.append("축소 계획의 총 작업 시간이 기존 작업보다 큽니다.")
    return {
        "recovery_draft": parsed.model_dump(),
        "validation_errors": errors,
    }


def _after_validation(state: PlannerState) -> str:
    if not state["validation_errors"]:
        return "await_approval"
    if state["retry_count"] < state["retry_limit"]:
        return "prepare_retry"
    return "safe_fallback"


def _prepare_retry(state: PlannerState) -> dict[str, Any]:
    return {
        "retry_count": state["retry_count"] + 1,
        "recovery_draft": None,
    }


def _await_approval(_state: PlannerState) -> dict[str, Any]:
    return {"approval_status": "waiting"}


def _safe_fallback(state: PlannerState) -> dict[str, Any]:
    return {
        "approval_status": "fallback",
        "recovery_draft": None,
        "fallback": {
            "action": "keep_current_plan",
            "reason": "복구 계획이 검증을 통과하지 못했습니다.",
            "source": "validation_policy",
            "validation_errors": state["validation_errors"],
        },
    }


def _unsupported_route(state: PlannerState) -> dict[str, Any]:
    return {
        "approval_status": "fallback",
        "fallback": {
            "action": "keep_current_plan",
            "reason": f"{state['route']} 복구 경로는 아직 연결되지 않았습니다.",
            "source": "route_not_connected",
        },
    }


def build_adaptive_planner_graph(
    recovery_generator: RecoveryGenerator,
    *,
    max_retries: int = 2,
):
    """Build the recovery graph without binding it to pending shared schemas.

    ``recovery_generator`` is injected rather than hardcoded.  It can be a fake
    in tests today and an LLM-backed implementation after the shared contracts
    are available. Missing required context asks for input; it never invents a
    numeric user preference.
    """
    if type(max_retries) is not int or not 0 <= max_retries <= 5:
        raise ValueError("max_retries must be an integer from 0 through 5")

    graph = StateGraph(PlannerState)
    graph.add_node("initialize", _initialize(max_retries))
    graph.add_node("analyze_execution", _analyze_execution)
    graph.add_node("generate_recovery", _generate_recovery(recovery_generator))
    graph.add_node("validate_recovery", _validate_recovery)
    graph.add_node("prepare_retry", _prepare_retry)
    graph.add_node("await_approval", _await_approval)
    graph.add_node("safe_fallback", _safe_fallback)
    graph.add_node("unsupported_route", _unsupported_route)

    graph.set_entry_point("initialize")
    graph.add_edge("initialize", "analyze_execution")
    graph.add_conditional_edges(
        "analyze_execution",
        _after_analysis,
        {
            "generate_recovery": "generate_recovery",
            "finish": END,
            "unsupported_route": "unsupported_route",
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
    graph.add_edge("await_approval", END)
    graph.add_edge("safe_fallback", END)
    graph.add_edge("unsupported_route", END)
    return graph.compile()
