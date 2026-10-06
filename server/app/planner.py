import json
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, model_validator
from .planning_context import MemoryInput


class PlanGenerationError(ValueError):
    pass


class PlanTask(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    start_date: date = Field(alias="startDate")
    due_date: date = Field(alias="dueDate")
    estimated_hours: float = Field(alias="estimatedHours", gt=0, le=1000)

    @model_validator(mode="after")
    def validate_date_order(self):
        if self.due_date < self.start_date:
            raise ValueError("dueDate must not precede startDate")
        return self


class PlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=500)
    tasks: list[PlanTask] = Field(min_length=1, max_length=12)


class ProjectContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def accept_ui_metadata(cls, value):
        # Older clients send the complete Project, including presentation fields.
        if isinstance(value, dict):
            return {k: v for k, v in value.items() if k not in {"priority", "status"}}
        return value

    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=1000)
    startDate: date
    dueDate: date

    @model_validator(mode="after")
    def validate_date_order(self):
        if self.dueDate < self.startDate:
            raise ValueError("project dueDate must not precede startDate")
        return self


class ExistingTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    startDate: date
    dueDate: date
    estimatedHours: float = Field(gt=0, le=1000)
    status: str = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_date_order(self):
        if self.dueDate < self.startDate:
            raise ValueError("existing task dueDate must not precede startDate")
        return self


class PlanDraftRequest(BaseModel):
    _planning_context: dict | None = PrivateAttr(default=None)
    memories: list[MemoryInput] = Field(default_factory=list, max_length=200)

    @property
    def planning_context(self):
        return self._planning_context

    @planning_context.setter
    def planning_context(self, value):
        self._planning_context = value

    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=3, max_length=2000)
    project: ProjectContext
    existingTasks: list[ExistingTask] = Field(default_factory=list, max_length=100)


def parse_plan_payload(payload: Any) -> PlanDraft:
    try:
        return PlanDraft.model_validate(payload)
    except ValidationError as exc:
        raise PlanGenerationError("AI가 유효하지 않은 계획을 반환했습니다.") from exc


def parse_plan_for_project(
    payload: Any,
    project_start: date,
    project_due: date,
) -> PlanDraft:
    draft = parse_plan_payload(payload)
    if any(
        task.start_date < project_start or task.due_date > project_due
        for task in draft.tasks
    ):
        raise PlanGenerationError("AI가 프로젝트 기간을 벗어난 계획을 반환했습니다.")
    return draft


def build_plan_prompt(goal: str, project: dict[str, Any], existing_tasks: list[dict[str, Any]], planning_context: dict | None = None) -> str:
    context = {
        "project": project,
        "existingTasks": existing_tasks,
        "userRequest": goal,
        "planningContext": planning_context,
    }
    return (
        "사용자가 검토할 프로젝트 실행 초안을 만드세요. "
        "큰 계획을 겹치지 않는 실행 가능한 단계별 할 일 3~8개로 나누고, "
        "프로젝트 기간 안에서 날짜와 예상 시간을 현실적으로 배정하세요. "
        "기존 할 일과 중복하지 마세요. 자동으로 저장하거나 확정하지 마세요.\n"
        f"입력 컨텍스트:\n{json.dumps(context, ensure_ascii=False, default=str)}"
    )
