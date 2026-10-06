"""A-owned profile contract and transactional update boundary (camelCase)."""
from copy import deepcopy
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from .execution_profile import validate_answers


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class SurveyAnswers(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roles: list[Literal["student", "employee", "job_seeker", "freelancer", "other"]] = Field(min_length=1)
    regularity: Literal["regular", "mixed", "irregular", "unknown"]
    barriers: list[Literal["starting", "overplanning", "distraction", "fatigue", "interruptions", "unclear", "none", "unknown"]] = Field(min_length=1)
    focusMinutes: int | None = Field(ge=5, le=180, strict=True)
    dailyMinutes: int | None = Field(ge=5, le=720, strict=True)
    energy: Literal["morning", "afternoon", "evening", "variable", "unknown"]
    recovery: Literal["replan", "reduce", "continue", "abandon", "unknown"]
    constraints: str = Field(max_length=1500)
    context: str = Field(max_length=1500)
    scheduleStyle: Literal["time_blocks", "flexible_queue", "unknown"] = "unknown"

    @model_validator(mode="after")
    def valid_answers(self):
        validate_answers(self.model_dump())
        return self


class PlanningPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    blockMinutes: int = Field(ge=1, le=180, strict=True)
    breakMinutes: int = Field(ge=0, le=60, strict=True)
    bufferPercent: int = Field(ge=0, le=90, strict=True)
    dailyPlannedMinutes: int | None = Field(default=None, ge=1, le=720, strict=True)
    scheduleStyle: Literal["time_blocks", "flexible_queue"]
    scheduleStyleSource: Literal["user", "rule", "legacy"] = "legacy"
    recoveryPreference: Literal["replan", "reduce", "continue", "abandon", "unknown"]
    starterMinutes: int | None = Field(default=None, ge=1, le=180, strict=True)
    status: Literal["provisional", "confirmed"]

    @model_validator(mode="after")
    def bounded(self):
        if self.dailyPlannedMinutes is not None and self.blockMinutes > self.dailyPlannedMinutes:
            raise ValueError("집중 구간은 하루 작업 예산을 넘을 수 없습니다.")
        if self.starterMinutes is not None and self.starterMinutes > self.blockMinutes:
            raise ValueError("시작 작업은 집중 구간을 넘을 수 없습니다.")
        return self


class LearnedPattern(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    observation: str = Field(min_length=1, max_length=2000)
    proposedChanges: dict
    evidenceRecordIds: list[str] = Field(min_length=1)
    approvedProposalId: str
    projectId: str | None = None
    status: Literal["active", "revoked", "superseded"] = "active"
    approvedAt: str
    expiresAt: str | None = None


class UserProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    userId: str
    schemaVersion: Literal["2.0"] = "2.0"
    version: int = Field(ge=1)
    status: Literal["draft", "confirmed"]
    source: Literal["demo", "llm"]
    declaredFacts: dict
    facts: dict  # deprecated read-compatible alias for existing B/C/UI
    planningPreferences: PlanningPreferences
    insights: dict
    learnedPatterns: list[LearnedPattern] = Field(default_factory=list)
    surveyResponseId: str | None = None
    createdAt: str
    updatedAt: str
    confirmedAt: str | None = None

    @model_validator(mode="after")
    def valid_facts(self):
        SurveyAnswers.model_validate(self.declaredFacts)
        validated = validate_answers(self.declaredFacts)
        if validated != self.declaredFacts or self.facts != self.declaredFacts:
            raise ValueError("설문 정보와 호환 필드가 일치하지 않습니다.")
        if self.status == "confirmed" and (self.planningPreferences.status != "confirmed" or not self.confirmedAt):
            raise ValueError("확정 프로필에는 확정된 선호와 승인 시각이 필요합니다.")
        return self


def upgrade_profile(profile, user_id):
    """Preserve legacy confirmation and IDs; never confirm an old draft."""
    p = deepcopy(profile)
    p.setdefault("userId", user_id)
    if p["userId"] != user_id:
        raise ValueError("다른 사용자의 프로필입니다.")
    p.setdefault("declaredFacts", deepcopy(p["facts"]))
    p["schemaVersion"] = "2.0"
    p.setdefault("version", 1)
    p.setdefault("updatedAt", p["createdAt"])
    p.setdefault("confirmedAt", p["createdAt"] if p["status"] == "confirmed" else None)
    p.setdefault("surveyResponseId", None)
    p.setdefault("learnedPatterns", [])
    prefs = p["planningPreferences"]
    prefs.setdefault("scheduleStyleSource", "legacy")
    prefs["status"] = "confirmed" if p["status"] == "confirmed" else "provisional"
    return UserProfile.model_validate(p).model_dump()


def normalize_profile_state(state, user_id):
    state.setdefault("surveyResponses", [])
    state.setdefault("profileRevisions", [])
    state.setdefault("profileUpdateProposals", [])
    state.setdefault("memories", [])
    for key in ("profile", "profileDraft"):
        if state.get(key):
            state[key] = upgrade_profile(state[key], user_id)
    # Legacy facts are a recovered normalized snapshot, not the original raw survey.
    p = state.get("profile")
    if p and not state["profileRevisions"]:
        state["profileRevisions"].append({"version": p["version"], "profileId": p["id"],
            "source": "legacy_snapshot", "sourceId": None, "createdAt": p["updatedAt"], "snapshot": deepcopy(p)})
    return state


def save_profile_draft(state, profile, raw_answers, user_id):
    timestamp = utc_now()
    survey_id = str(uuid4())
    state["surveyResponses"].append({"id": survey_id, "userId": user_id,
        "surveyVersion": "1.1", "answers": deepcopy(raw_answers), "submittedAt": timestamp})
    profile = deepcopy(profile)
    profile.update(userId=user_id, surveyResponseId=survey_id, updatedAt=timestamp,
        version=(state["profile"]["version"] + 1) if state.get("profile") else 1)
    state["profileDraft"] = upgrade_profile(profile, user_id)


def record_revision(state, profile, source, source_id):
    state["profileRevisions"].append({"version": profile["version"], "profileId": profile["id"],
        "source": source, "sourceId": source_id, "createdAt": profile["updatedAt"], "snapshot": deepcopy(profile)})


def confirm_profile_draft(state):
    if not state.get("profileDraft"):
        raise ValueError("확정할 프로필 초안이 없습니다.")
    p = deepcopy(state["profileDraft"])
    p.update(status="confirmed", confirmedAt=utc_now(), updatedAt=utc_now())
    p["planningPreferences"]["status"] = "confirmed"
    p["version"] = state["profile"]["version"] + 1 if state.get("profile") else 1
    # Resurvey explicitly replaces learned settings; historical evidence remains in revisions.
    p = UserProfile.model_validate(p).model_dump()
    record_revision(state, p, "survey_confirmed", p["surveyResponseId"])
    state["settings"]["view"] = "checklist" if p["planningPreferences"].get("scheduleStyle") == "flexible_queue" else "timeline"
    state.update(profile=p, profileDraft=None, planDraft=None)


def apply_profile_proposal(state, proposal_id, *, expected_version):
    """Called INSIDE B's store.change after an explicit approval request.

    Accepts PR #8's stored proposal, not arbitrary client-supplied changes.
    This function marks approval, rotates the profile ID (PR #8 semantics),
    advances A's version and records evidence atomically with the caller.
    """
    from .execution_store import ConflictError
    proposal = next((p for p in state.get("profileUpdateProposals", []) if p["id"] == proposal_id), None)
    if not proposal:
        raise ValueError("변경 후보를 찾을 수 없습니다.")
    p = state.get("profile")
    if proposal["status"] != "pending":
        raise ConflictError("이미 처리한 변경 후보입니다.")
    if not p or p["status"] != "confirmed" or p["id"] != proposal["profileId"] or p["version"] != expected_version or state.get("profileDraft"):
        raise ConflictError("프로필이 변경되었거나 수정 중입니다.")
    ids = proposal.get("evidenceRecordIds", [])
    records = {r["id"]: r for r in state.get("executionRecords", [])}
    if not ids or any(i not in records or records[i].get("profileId") != p["id"] for i in ids):
        raise ValueError("제안의 근거 실행 기록이 올바르지 않습니다.")
    changes = proposal.get("proposedChanges", {})
    if set(changes) != {"blockMinutes"}:
        raise ValueError("PR #8 계약에서는 blockMinutes 변경만 지원합니다.")
    updated = deepcopy(p)
    for key, change in changes.items():
        if set(change) != {"from", "to"} or updated["planningPreferences"][key] != change["from"]:
            raise ConflictError("제안 이후 프로필 값이 변경되었습니다.")
        updated["planningPreferences"][key] = change["to"]
    prefs = updated["planningPreferences"]
    if prefs["starterMinutes"] is not None:
        prefs["starterMinutes"] = min(prefs["starterMinutes"], prefs["blockMinutes"])
    timestamp = utc_now()
    for pattern in updated["learnedPatterns"]:
        if pattern["status"] == "active":
            pattern["status"] = "superseded"
    updated["learnedPatterns"].append(LearnedPattern(id=str(uuid4()), observation=proposal["reason"],
        proposedChanges=deepcopy(changes), evidenceRecordIds=ids, approvedProposalId=proposal_id,
        approvedAt=timestamp).model_dump())
    updated.update(id=str(uuid4()), version=p["version"] + 1, updatedAt=timestamp)
    updated = UserProfile.model_validate(updated).model_dump()
    proposal.update(status="approved", decidedAt=timestamp, appliedProfileId=updated["id"])
    record_revision(state, updated, "proposal_approved", proposal_id)
    state.update(profile=updated, planDraft=None)
    return updated
