"""A's read-only loader shared by ordinary and graph planners."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .user_profile import UserProfile


class MemoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=2000)
    category: Literal["availability", "preference", "priority", "context"]
    source: Literal["user", "ai_approved"]
    createdAt: str
    updatedAt: str | None = None
    expiresAt: str | None = None
    sensitive: bool = False
    useForPlanning: bool = True
    userId: str | None = None
    projectId: str | None = None


def _timestamp(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("시간대가 포함된 시각이 필요합니다.")
    return dt


def get_planning_context(user, project=None, *, state, memories=None, now=None):
    """user is a trusted server-side identity; state comes from its scoped store.

    Browser-owned projects/memories are supplied by the existing local client.
    An authenticated deployment must resolve their ownership before this boundary.
    """
    now = now or datetime.now(timezone.utc)
    profile = state.get("profile")
    if not profile or profile.get("status") != "confirmed":
        raise ValueError("먼저 실행 프로필을 생성하고 확정해 주세요.")
    profile = UserProfile.model_validate(profile).model_dump()
    if profile["userId"] != user:
        raise ValueError("다른 사용자의 프로필입니다.")
    project = project.model_dump(mode="json") if hasattr(project, "model_dump") else deepcopy(project)
    project_id = project.get("id") if project else None
    if project and project.get("userId", user) != user:
        raise ValueError("다른 사용자의 프로젝트입니다.")
    warnings, selected = [], []
    for raw in state.get("memories", []) if memories is None else memories:
        try:
            memory = MemoryInput.model_validate(raw).model_dump()
            stamp = _timestamp(memory["updatedAt"] or memory["createdAt"])
            expired = memory["expiresAt"] is not None and _timestamp(memory["expiresAt"]) <= now
            if (memory["sensitive"] or not memory["useForPlanning"] or expired
                or stamp > now or stamp < now - timedelta(days=180)
                or memory["userId"] not in (None, user)
                or memory["projectId"] not in (None, project_id)):
                continue
            selected.append({k: memory[k] for k in ("id", "content", "category", "source", "createdAt")})
        except (ValueError, TypeError):
            warnings.append("INVALID_MEMORY_EXCLUDED")
    patterns = []
    approved = {p["id"] for p in state.get("profileUpdateProposals", []) if p.get("status") == "approved"}
    for pattern in profile["learnedPatterns"]:
        try:
            if (pattern["status"] == "active" and pattern["approvedProposalId"] in approved
                and pattern["projectId"] in (None, project_id)
                and _timestamp(pattern["approvedAt"]) <= now
                and (not pattern["expiresAt"] or _timestamp(pattern["expiresAt"]) > now)):
                patterns.append(pattern)
        except ValueError:
            warnings.append("INVALID_PATTERN_EXCLUDED")
    # Free-text survey notes may contain sensitive details; they stay in storage.
    facts = {k: v for k, v in profile["declaredFacts"].items() if k not in ("constraints", "context")}
    return deepcopy({"schemaVersion": "1.0", "userId": user, "profileId": profile["id"],
        "profileVersion": profile["version"], "generatedAt": now.isoformat(),
        "userProfile": {"declaredFacts": facts, "planningPreferences": profile["planningPreferences"],
                        "learnedPatterns": patterns},
        "projectContext": project, "availability": {"timezone": "Asia/Seoul", "slots": state["settings"]["slots"]},
        "memories": selected, "warnings": sorted(set(warnings))})
