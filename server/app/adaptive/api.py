"""HTTP API for the adaptive planner graph (local single-user store).

Request and response JSON are camelCase like the rest of the API; the graph
works in snake_case.  The task and the waiting draft are always read from the
store, never trusted from the client.
"""
from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..execution_api import BusyEvent
from ..execution_llm import ExecutionLLM
from ..execution_store import ConflictError, ExecutionStore
from .context import to_execution_context
from ..planning_context import get_planning_context, MemoryInput
from .graph import build_adaptive_planner_graph
from .llm_generator import LLMRecoveryGenerator
from .local import (
    KEEP_CURRENT_PLAN,
    LocalPlanWriter,
    close_draft,
    current_task,
    drafts_for_plan,
    execution_context_from_profile,
    find_draft,
    local_now,
    put_draft,
    record_check_in,
    schedule_context,
)
from .state import ReasonCode, ReviewDecision, Strategy


class CheckInBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    completed: bool = Field(strict=True)
    actualMinutes: int | None = Field(default=None, ge=0, le=1440, strict=True)
    remainingMinutes: int | None = Field(default=None, ge=1, le=1440, strict=True)  # work left; default: the whole task
    reasonCode: ReasonCode | None = None
    note: str = Field(default="", max_length=1500)


class CheckInRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0, strict=True)
    taskId: str
    checkIn: CheckInBody
    strategy: Strategy | None = None
    consent: bool = False
    # Calendar events live in the browser, so the client sends them like /api/execution/plan.
    memories: list[MemoryInput] = Field(default_factory=list, max_length=200)
    events: list[BusyEvent] = Field(default_factory=list, max_length=500)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0, strict=True)
    draftId: str
    decision: ReviewDecision
    feedback: str | None = Field(default=None, max_length=1000)
    strategy: Strategy | None = None
    consent: bool = False
    memories: list[MemoryInput] = Field(default_factory=list, max_length=200)
    events: list[BusyEvent] = Field(default_factory=list, max_length=500)


def _convert_keys(value: Any, convert) -> Any:
    if isinstance(value, dict):
        return {convert(k): _convert_keys(v, convert) for k, v in value.items()}
    if isinstance(value, list):
        return [_convert_keys(v, convert) for v in value]
    return value


def to_camel(value: Any) -> Any:
    return _convert_keys(value, lambda k: re.sub(r"_([a-z])", lambda m: m.group(1).upper(), k))


def to_snake(value: Any) -> Any:
    return _convert_keys(value, lambda k: re.sub(r"[A-Z]", lambda m: "_" + m.group(0).lower(), k))


def _public(result: dict[str, Any]) -> dict[str, Any]:
    keys = ("route", "strategy", "approval_status", "draft", "fallback",
            "validation_errors", "retry_count", "revision_count", "error")
    return to_camel({k: result.get(k) for k in keys})


def adaptive_router(store: ExecutionStore | None = None, llm: ExecutionLLM | None = None) -> APIRouter:
    store = store or ExecutionStore()
    graph = build_adaptive_planner_graph(
        LLMRecoveryGenerator(llm),
        plan_writer=LocalPlanWriter(store),
    )
    router = APIRouter(prefix="/api/adaptive", tags=["adaptive planner"])

    def load(revision: int, *, needs_current_profile: bool) -> dict[str, Any]:
        state = store.read()
        if state["revision"] != revision:
            raise ConflictError("내용이 변경되었습니다. 다시 불러온 뒤 시도해 주세요.")
        if not state["profile"] or not state["plan"]:
            raise ValueError("확정된 실행 프로필과 주간 계획이 있어야 합니다.")
        if needs_current_profile and state["plan"]["profileId"] != state["profile"]["id"]:
            # Recovering with a newer profile's values would mix two profiles in one plan.
            raise ValueError("계획을 만든 뒤 실행 프로필이 바뀌었습니다. 새 프로필로 주간 계획을 다시 생성해 주세요.")
        return state

    def graph_input(state: dict[str, Any], task_id: str, events: list[BusyEvent], memories=None) -> dict[str, Any]:
        planning = get_planning_context(store.user_id, state["plan"].get("project"), state=state, memories=memories)
        return {
            "user_id": store.user_id,
            "project_id": state["plan"].get("projectId"),
            "execution_context": to_execution_context(planning["userProfile"], [], converter=execution_context_from_profile),
            "planning_context": {**planning, "goal": state["plan"]["goal"]},
            "current_task": current_task(state["plan"], task_id),
            "schedule_context": schedule_context(state, task_id, events, local_now()),
        }

    def respond(saved: dict[str, Any], task_id: str, result: dict[str, Any], **extra: Any) -> dict[str, Any]:
        return {
            "revision": saved["revision"],
            "recoveryDraft": drafts_for_plan(saved).get(task_id),
            **extra,
            "result": _public(result),
            "profileUpdateProposals": [p for p in saved.get("profileUpdateProposals", []) if p["status"] == "pending"],
        }

    @router.post("/check-in")
    def check_in(request: CheckInRequest):
        """Record how a task went.

        Every check-in is stored as an execution record.  A completed task is
        marked done; an incomplete one goes through the recovery graph and may
        leave a waiting draft for that task.
        """
        completed = request.checkIn.completed
        if not completed and not request.consent:
            raise HTTPException(400, "작업·체크인 정보의 LLM 전송에 동의해 주세요.")
        state = load(request.revision, needs_current_profile=not completed)
        task_input = graph_input(state, request.taskId, request.events, [m.model_dump() for m in request.memories])
        check_in = request.checkIn.model_dump()
        result = graph.invoke({
            "request": "recovery",
            **task_input,
            "check_in": to_snake(check_in),
            "strategy": request.strategy,
        })
        record_ids: list[str] = []

        def save(doc: dict[str, Any]) -> None:
            record_id = record_check_in(doc, task_input["current_task"], check_in)
            record_ids.append(record_id)
            draft = None
            if result["approval_status"] == "waiting":
                draft = {
                    "id": str(uuid4()), "planId": doc["plan"]["id"], "taskId": request.taskId,
                    "recordId": record_id, "strategy": result["strategy"], "checkIn": check_in,
                    "draft": to_camel(result["draft"]), "revisionCount": 0,
                }
            put_draft(doc, request.taskId, draft)

        saved = store.change(request.revision, save)
        return respond(saved, request.taskId, result, recordId=record_ids[0])

    @router.post("/review")
    def review(request: ReviewRequest):
        """Approve, reject or revise a task's waiting recovery draft."""
        if request.decision == "revise" and not request.consent:
            raise HTTPException(400, "수정 요청을 LLM에 전송하는 데 동의해 주세요.")
        state = load(request.revision, needs_current_profile=request.decision != "reject")
        stored = find_draft(state, request.draftId)
        if stored is None:
            raise ValueError("검토할 초안이 없거나 변경되었습니다. 다시 불러와 주세요.")
        task_id = stored["taskId"]
        if request.decision == "reject":
            # Rejecting needs nothing else, so even a stale draft can be dismissed.
            result = graph.invoke({"request": "review", "decision": "reject"})
            saved = store.change(request.revision, lambda doc: close_draft(doc, task_id, KEEP_CURRENT_PLAN))
            return respond(saved, task_id, result)

        if stored["planId"] != state["plan"]["id"]:
            raise ValueError("계획이 바뀌어 이 초안을 쓸 수 없습니다. 다시 생성해 주세요.")
        if request.decision == "approve" and request.strategy not in (None, stored["strategy"]):
            # The approved strategy is recorded on the check-in, so it must be the draft's own.
            raise ValueError("승인할 때는 복구 방법을 바꿀 수 없습니다. 다른 방법은 수정(revise)으로 요청해 주세요.")
        result = graph.invoke({
            "request": "review",
            **graph_input(state, task_id, request.events, [m.model_dump() for m in request.memories]),
            "check_in": to_snake(stored["checkIn"]),
            "decision": request.decision,
            "strategy": request.strategy or stored["strategy"],
            "pending_draft": to_snake(stored["draft"]),
            "user_feedback": request.feedback,
            "revision_count": stored["revisionCount"],
            "base_revision": request.revision,
        })
        if request.decision == "revise" and result["approval_status"] == "waiting":
            updated = {**stored, "revisionCount": result.get("revision_count", stored["revisionCount"])}
            if result["fallback"] is None:  # a new draft was generated and validated
                updated.update(draft=to_camel(result["draft"]), strategy=result["strategy"])
            if updated != stored:
                state = store.change(request.revision, lambda doc: put_draft(doc, task_id, updated))
        elif result["approval_status"] == "approved":
            state = store.read()  # LocalPlanWriter replaced the task and closed the draft
        return respond(state, task_id, result)

    return router
