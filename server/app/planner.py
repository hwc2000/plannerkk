"""Shared request shapes for planning: the project a plan is for and its existing tasks."""
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PlanGenerationError(ValueError):
    pass


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
    projectId: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_date_order(self):
        if self.dueDate < self.startDate:
            raise ValueError("existing task dueDate must not precede startDate")
        return self
