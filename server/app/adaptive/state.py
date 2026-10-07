"""PlannerState schema: the state of one planner graph run.

This is the file teammates review.  Durable shared schemas (UserProfile,
ExecutionRecord) do not enter here directly: A's planning context is carried
as-is for the generator, and the few values graph code decides on are
normalized into ``ExecutionContext`` by ``context.to_execution_context``.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal, TypedDict

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

PlanRequest = Literal["new_plan", "replan", "recovery", "review"]
Route = Literal["new_plan", "replan", "recovery", "review", "continue", "request_information"]
Strategy = Literal["shrink", "reschedule", "replan"]
# What the user did with a waiting draft (request = "review").
ReviewDecision = Literal["approve", "reject", "revise"]
# shrink: AI-made smaller pieces; reschedule: same work moved (rule-based);
# fit_deadline: AI-reduced scope before the deadline.  Code places all of them in free time.
DraftKind = Literal["shrink", "reschedule", "fit_deadline"]
# The strategy a draft of each kind carries out; approval must not record another one.
DRAFT_STRATEGY: dict[str, Strategy] = {
    "shrink": "shrink",
    "reschedule": "reschedule",
    "fit_deadline": "reschedule",
}
# Same values as UserProfile.planningPreferences.scheduleStyle.
ScheduleStyle = Literal["time_blocks", "flexible_queue"]
ApprovalStatus = Literal[
    "not_required",
    "needs_input",
    "waiting",
    "approved",
    "rejected",
    "fallback",
]
# Same codes as teammate B's ExecutionRecord.reasonCode draft.
ReasonCode = Literal[
    "time_shortage",
    "task_too_large",
    "fatigue",
    "interruption",
    "priority_changed",
    "unclear_task",
    "underestimated",
    "other",
]
# "other" has no automatic strategy; the user is asked to pick one.
REASON_STRATEGY: dict[str, Strategy] = {
    "task_too_large": "shrink",
    "unclear_task": "shrink",
    "fatigue": "shrink",
    "time_shortage": "reschedule",
    "interruption": "reschedule",
    "underestimated": "reschedule",
    "priority_changed": "replan",
}


class ExecutionContext(TypedDict):
    """Stable graph-facing view; not the final shared UserProfile schema."""

    schedule_style: ScheduleStyle | None
    focus_minutes: int | None  # required only for time_blocks
    break_minutes: int | None  # gap between pieces in one window for time_blocks; None = no gap


class ProfileChangeContext(TypedDict):
    """C-owned normalized view of an approved external profile proposal."""

    before: dict[str, Any]
    after: dict[str, Any]
    changed_fields: list[str]
    reason: str
    evidence_record_ids: list[str]
    source_profile_id: str
    applied_profile_id: str


class RecoveryTask(TypedDict, total=False):
    id: str
    title: str
    minutes: int
    done_when: str
    recovery_depth: int  # how many times this task came out of an approved shrink; 0 if never


class CheckInSignal(TypedDict, total=False):
    completed: bool
    actual_minutes: int | None
    remaining_minutes: int | None  # user's estimate of work left; None = the whole task
    reason_code: ReasonCode | None
    note: str
    difficulty: int | None


class ScheduleContext(TypedDict):
    """Free time computed by the caller from availability, calendar and the plan."""

    now: str  # ISO datetime; placements must not start before it
    free_windows: list[list[str]]  # [[start, end], ...] ISO datetimes, sorted, already cut at the deadline
    deadline: str | None  # ISO date of the task or project deadline
    deadline_within_plan: bool  # True: work left over cannot move to the next plan


class PlannerState(TypedDict, total=False):
    """State for one graph run, not a DB record.  Nothing here is persisted
    until the user approves the draft."""

    # Input: set by the caller before invoke.
    request: PlanRequest
    user_id: str | None
    project_id: str | None
    planning_context: dict[str, Any] | None  # A's get_planning_context(user, project), read-only
    execution_context: ExecutionContext
    profile_change_context: ProfileChangeContext | None
    current_task: RecoveryTask  # recovery only
    check_in: CheckInSignal  # recovery only; converted from B's ExecutionRecord
    schedule_context: ScheduleContext | None  # required for shrink, reschedule and approval
    base_revision: int | None  # storage revision the caller read; the writer must not write past it
    strategy: Strategy | None  # optional user choice; otherwise derived from reason_code

    # Review input: the caller loads the waiting draft from storage, never from the client.
    decision: ReviewDecision | None
    pending_draft: dict[str, Any] | None  # the draft the user is reviewing
    user_feedback: str | None  # revise only; passed to the generator as data
    revision_count: int | None  # revisions already made to this draft (stored with it)

    # Progress: written by graph nodes.
    route: Route | None
    draft: dict[str, Any] | None
    plan_draft: dict[str, Any] | None
    validation_errors: list[str]
    retry_count: int
    retry_limit: int
    min_task_minutes: int  # copied from the policy so the generator can tell the LLM
    fit_limits: dict[str, int] | None  # set when work must be cut to fit before the deadline

    # Result.
    approval_status: ApprovalStatus
    fallback: dict[str, Any] | None
    error: str | None


# Validation models for the TypedDicts above.  Whitespace-only text counts as
# empty so a generator cannot pass validation with titles like " ".
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Id = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def _local_datetime(value: str) -> str:
    # Plans hold naive local times; an offset would make comparisons raise.
    if datetime.fromisoformat(value).tzinfo is not None:
        raise ValueError("시간대 없이 현지 시각으로 보내야 합니다.")
    return value


def _iso_date(value: str) -> str:
    date.fromisoformat(value)
    return value


# Checked with the same parser the nodes use, so a value that passes never crashes a node.
LocalDateTime = Annotated[str, Field(strict=True), AfterValidator(_local_datetime)]
IsoDate = Annotated[str, Field(strict=True), AfterValidator(_iso_date)]


class RequestModel(BaseModel):
    """Top-level input fields; the nested sections are validated separately."""

    model_config = ConfigDict(extra="ignore")

    request: PlanRequest
    user_id: Id | None = None
    project_id: Id | None = None
    planning_context: dict[str, Any] | None = None
    profile_change_context: dict[str, Any] | None = None
    base_revision: int | None = Field(default=None, ge=0, strict=True)
    strategy: Strategy | None = None
    decision: ReviewDecision | None = None
    pending_draft: dict[str, Any] | None = None
    user_feedback: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ] | None = None
    revision_count: int | None = Field(default=None, ge=0, strict=True)


class ExecutionContextModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schedule_style: ScheduleStyle | None = None
    focus_minutes: int | None = Field(default=None, ge=1, strict=True)
    break_minutes: int | None = Field(default=None, ge=0, strict=True)


class ProfileChangeContextModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    before: dict[Id, Any]
    after: dict[Id, Any]
    changed_fields: list[Id] = Field(min_length=1)
    reason: Text
    evidence_record_ids: list[Id] = Field(min_length=1)
    source_profile_id: Id
    applied_profile_id: Id

    @model_validator(mode="after")
    def consistent_change(self) -> "ProfileChangeContextModel":
        if len(set(self.changed_fields)) != len(self.changed_fields):
            raise ValueError("changed_fields: 중복 필드는 허용하지 않습니다.")
        if set(self.before) != set(self.changed_fields) or set(self.after) != set(self.changed_fields):
            raise ValueError("before와 after는 changed_fields와 정확히 일치해야 합니다.")
        if any(self.before[field] == self.after[field] for field in self.changed_fields):
            raise ValueError("changed_fields의 변경 전후 값은 달라야 합니다.")
        if len(set(self.evidence_record_ids)) != len(self.evidence_record_ids):
            raise ValueError("evidence_record_ids: 중복 ID는 허용하지 않습니다.")
        if self.source_profile_id == self.applied_profile_id:
            raise ValueError("적용 프로필 ID는 원본 프로필 ID와 달라야 합니다.")
        return self


class CurrentTaskModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Id
    title: Text
    minutes: int = Field(gt=0, strict=True)
    done_when: Text
    recovery_depth: int = Field(default=0, ge=0, strict=True)


class CheckInSignalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completed: bool = Field(strict=True)
    actual_minutes: int | None = Field(default=None, ge=0, strict=True)
    remaining_minutes: int | None = Field(default=None, ge=1, strict=True)
    reason_code: ReasonCode | None = None
    note: str = Field(default="", max_length=1500)
    difficulty: int | None = Field(default=None, ge=1, le=5, strict=True)


class ScheduleContextModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    now: LocalDateTime
    free_windows: list[tuple[LocalDateTime, LocalDateTime]]
    deadline: IsoDate | None = None
    deadline_within_plan: bool = Field(strict=True)

    @model_validator(mode="after")
    def ordered_windows(self) -> ScheduleContextModel:
        if any(datetime.fromisoformat(start) >= datetime.fromisoformat(end) for start, end in self.free_windows):
            raise ValueError("free_windows: 시작 시각이 끝 시각보다 빨라야 합니다.")
        return self


class DraftTaskModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Text
    minutes: int = Field(gt=0, strict=True)
    done_when: Text
    start: LocalDateTime | None = None  # set by code for every kind, never by the LLM
    end: LocalDateTime | None = None


class RecoveryDraftModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: DraftKind = "shrink"
    replaces_task_id: str = Field(min_length=1)
    tasks: list[DraftTaskModel] = Field(max_length=20)
    applied_reasons: list[Text] = Field(min_length=1, max_length=10)
    dropped_scope: list[Text] = Field(default_factory=list, max_length=5)  # what the AI chose to leave out
    carry_over_minutes: int = Field(default=0, ge=0, strict=True)  # moved to the next plan

    @model_validator(mode="after")
    def has_work(self) -> RecoveryDraftModel:
        if not self.tasks and not self.carry_over_minutes:
            raise ValueError("tasks: 작업이 하나 이상 필요합니다.")
        return self
