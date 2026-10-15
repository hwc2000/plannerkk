"""Project profile: per-project settings layered on top of the user's profile.

The user profile holds what is true for the person (survey answers, approved
habits).  A project profile holds only what differs for one project: values
the user set for it and changes learned from that project's own execution
records.  It is never a copy, so a later change to the user profile still
reaches every project that does not override that value.
"""
from copy import deepcopy
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .execution_store import ConflictError
from .plan_merge import entry_owner
from .user_profile import LearnedPattern, PlanningPreferences

# Planning preferences a project may override.  Anything else stays a user trait.
OVERRIDE_KEYS = ("blockMinutes", "dailyPlannedMinutes", "bufferPercent", "starterMinutes", "recoveryPreference")
FIELD_LABELS = {
    "blockMinutes": "집중 구간", "dailyPlannedMinutes": "하루 계획량", "bufferPercent": "여유분",
    "starterMinutes": "시작 행동", "recoveryPreference": "복구 방식",
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class ProjectPreferenceValues(BaseModel):
    """One project's values; a key that is absent inherits the user's value."""
    model_config = ConfigDict(extra="forbid")
    blockMinutes: int = Field(default=None, ge=1, le=180, strict=True)
    dailyPlannedMinutes: int | None = Field(default=None, ge=1, le=720, strict=True)
    bufferPercent: int = Field(default=None, ge=0, le=90, strict=True)
    starterMinutes: int | None = Field(default=None, ge=1, le=180, strict=True)
    recoveryPreference: Literal["replan", "reduce", "continue", "abandon", "unknown"] = None

    def provided(self):
        return self.model_dump(include=self.model_fields_set)


class ProjectOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int | str | None
    source: Literal["declared", "learned"]
    proposalId: str | None = None


class ProjectProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    projectId: str = Field(min_length=1, max_length=100)
    userId: str
    version: int = Field(ge=1)
    overrides: dict[str, ProjectOverride] = Field(default_factory=dict)
    learnedPatterns: list[LearnedPattern] = Field(default_factory=list)
    createdAt: str
    updatedAt: str

    @model_validator(mode="after")
    def valid_overrides(self):
        unknown = set(self.overrides) - set(OVERRIDE_KEYS)
        if unknown:
            raise ValueError(f"프로젝트에서 바꿀 수 없는 설정입니다: {', '.join(sorted(unknown))}")
        ProjectPreferenceValues.model_validate({k: o.value for k, o in self.overrides.items()})
        if any(o.source == "learned" and not o.proposalId for o in self.overrides.values()):
            raise ValueError("학습으로 바꾼 프로젝트 설정에는 승인한 변경 후보가 필요합니다.")
        if any(p.projectId != self.projectId for p in self.learnedPatterns):
            raise ValueError("다른 프로젝트의 학습 패턴입니다.")
        return self


def _merge_error(exc: ValidationError) -> str:
    details = []
    for error in exc.errors():
        field = str(error["loc"][0]) if error["loc"] else ""
        if error["type"] == "extra_forbidden":
            details.append(f"프로젝트에서 바꿀 수 없는 항목 {field}")
        else:
            details.append(FIELD_LABELS.get(field) or error["msg"].removeprefix("Value error, "))
    return f"이 프로젝트 설정을 기본 프로필과 함께 쓸 수 없습니다: {', '.join(details)}. 프로젝트 설정을 고쳐 주세요."


def effective_preferences(profile, project_profile=None):
    """The user's planning preferences with the project's overrides on top.

    Returns (preferences, overrides) where overrides tells, per overridden key,
    where the value came from and what the user profile would have given.
    """
    prefs = deepcopy(profile["planningPreferences"])
    overrides = {}
    for key, item in ((project_profile or {}).get("overrides") or {}).items():
        overrides[key] = {"source": item["source"], "proposalId": item.get("proposalId"), "baseValue": prefs.get(key)}
        prefs[key] = item["value"]
    try:
        PlanningPreferences.model_validate(prefs)
    except ValidationError as exc:
        raise ValueError(_merge_error(exc)) from None
    return prefs, overrides


def load_project_profile(state, user_id, project_id):
    if not project_id:
        return None
    raw = (state.get("projectProfiles") or {}).get(project_id)
    if raw is None:
        return None
    profile = ProjectProfile.model_validate(raw).model_dump()
    if profile["userId"] != user_id or profile["projectId"] != project_id:
        raise ValueError("다른 사용자의 프로젝트 설정입니다.")
    return profile


def current_project_profile_id(state, project_id):
    """The project profile version a plan or record must match to be current."""
    if not project_id:
        return None
    return ((state.get("projectProfiles") or {}).get(project_id) or {}).get("id")


def project_preferences(state, user_id, project_id):
    """One project's preferences: the user's, with only this project's own values on top."""
    return effective_preferences(state["profile"], load_project_profile(state, user_id, project_id))


def entry_settings_version(plan, entry):
    """The project settings version an entry was planned with.

    A shared week holds several projects, so each entry carries its own.
    Entries saved before that share the plan's single project version.
    """
    if "projectProfileId" in entry:
        return entry["projectProfileId"]
    return plan.get("projectProfileId") if entry_owner(plan, entry) == plan.get("projectId") else None


def stale_project_ids(state, plan, entries=None):
    """Projects with open tasks planned under settings that have changed since.

    Only those projects need replanning; the rest of the week stays valid.
    """
    entries = plan["entries"] if entries is None else entries
    return {
        entry_owner(plan, e) for e in entries
        if e["kind"] == "task" and not e.get("completed")
        and entry_settings_version(plan, e) != current_project_profile_id(state, entry_owner(plan, e))
    }


def _save(state, current, user_id, project_id, overrides, patterns, source, source_id):
    timestamp = utc_now()
    new = ProjectProfile.model_validate({
        "id": str(uuid4()), "projectId": project_id, "userId": user_id,
        "version": current["version"] + 1 if current else 1,
        "overrides": overrides, "learnedPatterns": patterns,
        "createdAt": current["createdAt"] if current else timestamp, "updatedAt": timestamp,
    }).model_dump()
    effective_preferences(state["profile"], new)
    state.setdefault("projectProfiles", {})[project_id] = new
    state.setdefault("projectProfileRevisions", []).append({
        "projectId": project_id, "version": new["version"], "projectProfileId": new["id"],
        "source": source, "sourceId": source_id, "createdAt": timestamp, "snapshot": deepcopy(new),
    })
    return new


def _supersede(patterns, keys):
    for pattern in patterns:
        if pattern["status"] == "active" and set(pattern["proposedChanges"]) & set(keys):
            pattern["status"] = "superseded"


def set_declared_overrides(state, user_id, project_id, values):
    """Replace the values the user set for this project.

    Keys the user sets win over values learned for the same keys; learned
    values for other keys stay.  Keys left out inherit the user profile.
    """
    base = state.get("profile")
    if not base or base["status"] != "confirmed":
        raise ValueError("먼저 실행 프로필을 생성하고 확정해 주세요.")
    try:
        provided = ProjectPreferenceValues.model_validate(values).provided()
    except ValidationError as exc:
        raise ValueError(_merge_error(exc)) from None
    current = load_project_profile(state, user_id, project_id)
    overrides = {k: v for k, v in ((current or {}).get("overrides") or {}).items()
                 if v["source"] == "learned" and k not in provided}
    overrides.update({k: {"value": v, "source": "declared", "proposalId": None} for k, v in provided.items()})
    patterns = deepcopy((current or {}).get("learnedPatterns") or [])
    _supersede(patterns, provided)
    return _save(state, current, user_id, project_id, overrides, patterns, "declared", None)


def apply_project_proposal(state, proposal_id, *, user_id):
    """Approve a change learned from one project's records, for that project only.

    The user profile keeps its ID and version, so plans of other projects stay
    current.  Called inside the caller's store transaction.
    """
    proposal = next((p for p in state.get("profileUpdateProposals", []) if p["id"] == proposal_id), None)
    if not proposal:
        raise ValueError("변경 후보를 찾을 수 없습니다.")
    if proposal["status"] != "pending":
        raise ConflictError("이미 처리한 변경 후보입니다.")
    base = state.get("profile")
    if not base or base["status"] != "confirmed" or base["id"] != proposal["profileId"] or state.get("profileDraft"):
        raise ConflictError("프로필이 변경되었거나 수정 중입니다.")
    project_id = proposal["projectId"]
    current = load_project_profile(state, user_id, project_id)
    if (current or {}).get("id") != proposal.get("projectProfileId"):
        raise ConflictError("제안 이후 이 프로젝트 설정이 바뀌었습니다.")
    ids = proposal.get("evidenceRecordIds", [])
    records = {r["id"]: r for r in state.get("executionRecords", [])}
    if not ids or any(i not in records or records[i].get("profileId") != base["id"]
                      or records[i].get("projectId") != project_id
                      or records[i].get("projectProfileId") != proposal.get("projectProfileId") for i in ids):
        raise ValueError("제안의 근거 실행 기록이 올바르지 않습니다.")
    changes = proposal.get("proposedChanges", {})
    if set(changes) != {"blockMinutes"}:
        raise ValueError("현재는 집중 구간(blockMinutes) 변경만 지원합니다.")
    prefs, _ = effective_preferences(base, current)
    for key, change in changes.items():
        if set(change) != {"from", "to"} or prefs.get(key) != change["from"]:
            raise ConflictError("제안 이후 프로젝트 설정 값이 변경되었습니다.")
    overrides = deepcopy((current or {}).get("overrides") or {})
    for key, change in changes.items():
        overrides[key] = {"value": change["to"], "source": "learned", "proposalId": proposal_id}
    block = changes["blockMinutes"]["to"]
    # Same rule as the user profile: a starter never outgrows the focus block.
    if prefs.get("starterMinutes") is not None and prefs["starterMinutes"] > block:
        overrides["starterMinutes"] = {"value": block, "source": "learned", "proposalId": proposal_id}
    timestamp = utc_now()
    patterns = deepcopy((current or {}).get("learnedPatterns") or [])
    _supersede(patterns, changes)
    patterns.append(LearnedPattern(
        id=str(uuid4()), observation=proposal["reason"], proposedChanges=deepcopy(changes),
        evidenceRecordIds=ids, approvedProposalId=proposal_id, projectId=project_id, approvedAt=timestamp,
    ).model_dump())
    new = _save(state, current, user_id, project_id, overrides, patterns, "proposal_approved", proposal_id)
    proposal.update(status="approved", decidedAt=timestamp, appliedProfileId=base["id"], appliedProjectProfileId=new["id"])
    return new
