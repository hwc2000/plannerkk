"""Ending a project: its habits move to the user profile, its open work leaves the week.

What a project teaches about the user, not about the project, carries over to
the user profile when the user ends it.  Only values the project's own records
proved carry: a value the user set for this project alone stays with it, and
values with no learning rule yet are left as they are.  Ending is the user's
approval: the screen shows what will carry before the button is pressed, and
the change is stored as an approved proposal with its evidence, like any other
learned change.

| Field                 | Carries when                                                                 |
|-----------------------|------------------------------------------------------------------------------|
| blockMinutes          | learned in this project, and 3+ tasks of that length with 2/3+ finished       |
| recoveryPreference    | 3+ recovery drafts approved in this project, 2/3+ of them the same way        |
| dailyPlannedMinutes, starterMinutes | never yet: no rule learns them; a value set here is this project's |
| focusTime             | never here: it is learned from every record, in any project                  |
"""
from datetime import datetime, timezone
from uuid import uuid4

from .adaptive.local import close_draft, drafts_for_plan
from .execution_service import resolve_plan_draft
from .plan_merge import entry_owner
from .project_profile import load_project_profile
from .user_profile import apply_profile_proposal

CLOSE_RULE_VERSION = "project-close-v1"
MIN_EVIDENCE = 3
MIN_SHARE = 2 / 3
BLOCK_SHARE = 0.5  # a task of at least half the block was planned at that block
# What an approved recovery draft says about the user's own way back.
RECOVERY_HABITS = {"shrink": "reduce", "reschedule": "replan"}
LABELS = {"blockMinutes": "한 번에 집중할 시간", "recoveryPreference": "계획이 틀어졌을 때",
          "dailyPlannedMinutes": "하루 계획량", "starterMinutes": "첫 작업 앞 시작 행동"}
RECOVERY_TEXT = {"replan": "시간을 다시 배치", "reduce": "할 일을 줄임", "continue": "밀린 일을 건너뛰고 계속",
                 "abandon": "그날 계획을 포기", "unknown": "잘 모르겠어요"}


def _text(key, value):
    return RECOVERY_TEXT.get(value, str(value)) if key == "recoveryPreference" else f"{value}분"


def _versions_with(state, project_id, key, value):
    """The project's settings versions in which ``key`` had ``value``."""
    return {rev["projectProfileId"] for rev in state.get("projectProfileRevisions") or []
            if rev["projectId"] == project_id
            and ((rev["snapshot"].get("overrides") or {}).get(key) or {}).get("value") == value}


def carry_over(state, user_id, project_id):
    """What ending this project would move to the user profile, and what stays, each with why."""
    profile = state["profile"]
    prefs = profile["planningPreferences"]
    records = [r for r in state.get("executionRecords") or []
               if r.get("projectId") == project_id and r.get("profileId") == profile["id"]]
    overrides = ((load_project_profile(state, user_id, project_id) or {}).get("overrides") or {})
    changes, carried, kept, evidence = {}, [], [], []

    block = overrides.get("blockMinutes")
    if block and block["source"] == "learned" and block["value"] != prefs["blockMinutes"]:
        versions = _versions_with(state, project_id, "blockMinutes", block["value"])
        tried = [r for r in records if r.get("projectProfileId") in versions and r["plannedMinutes"] >= block["value"] * BLOCK_SHARE]
        done = [r for r in tried if r["result"] == "completed"]
        if len(tried) >= MIN_EVIDENCE and len(done) >= len(tried) * MIN_SHARE:
            changes["blockMinutes"] = {"from": prefs["blockMinutes"], "to": block["value"]}
            evidence += [r["id"] for r in tried]
            carried.append({"key": "blockMinutes", "label": LABELS["blockMinutes"], "from": _text("blockMinutes", prefs["blockMinutes"]),
                            "to": _text("blockMinutes", block["value"]),
                            "because": f"이 프로젝트 기록으로 배운 값이고, {block['value']}분 작업 {len(tried)}건 중 {len(done)}건을 끝냈어요."})
        else:
            kept.append({"label": LABELS["blockMinutes"], "value": _text("blockMinutes", block["value"]),
                         "why": f"이 프로젝트에서 배운 값이지만 그 길이로 끝낸 작업이 아직 적어요({len(done)}/{len(tried)}건, "
                                f"{MIN_EVIDENCE}건 이상·3분의 2 이상 필요)."})

    approved = [r for r in records if r.get("recoveryAction") in RECOVERY_HABITS]
    if approved:
        counts = {}
        for record in approved:
            counts[record["recoveryAction"]] = counts.get(record["recoveryAction"], 0) + 1
        way, count = max(counts.items(), key=lambda item: item[1])
        habit = RECOVERY_HABITS[way]
        if len(approved) >= MIN_EVIDENCE and count >= len(approved) * MIN_SHARE:
            if habit != prefs["recoveryPreference"]:
                changes["recoveryPreference"] = {"from": prefs["recoveryPreference"], "to": habit}
                evidence += [r["id"] for r in approved]
                carried.append({"key": "recoveryPreference", "label": LABELS["recoveryPreference"],
                                "from": _text("recoveryPreference", prefs["recoveryPreference"]), "to": _text("recoveryPreference", habit),
                                "because": f"이 프로젝트에서 승인한 복구안 {len(approved)}건 중 {count}건이 ‘{_text('recoveryPreference', habit)}’ 방식이었어요."})
        else:
            kept.append({"label": LABELS["recoveryPreference"], "value": _text("recoveryPreference", prefs["recoveryPreference"]),
                         "why": f"승인한 복구안이 아직 적거나 한쪽으로 모이지 않았어요({len(approved)}건)."})

    for key, item in overrides.items():
        if item["source"] == "declared":
            kept.append({"label": LABELS.get(key, key), "value": _text(key, item["value"]),
                         "why": "이 프로젝트에만 정한 값이라 기본 프로필에는 넘기지 않아요."})
    return {"changes": changes, "carried": carried, "kept": kept, "evidenceRecordIds": list(dict.fromkeys(evidence))}


def _affects_open_work(state, plan, closing_id, changes):
    """Whether the new user-profile values change how this week's remaining tasks were planned.

    A recovery preference never does; a focus block does for tasks of projects
    that follow the user profile's block.
    """
    if "blockMinutes" not in changes:
        return False
    for entry in plan["entries"]:
        owner = entry_owner(plan, entry)
        if entry["kind"] != "task" or entry["completed"] or owner == closing_id:
            continue
        own = ((state.get("projectProfiles") or {}).get(owner) or {}).get("overrides") or {} if owner else {}
        if "blockMinutes" not in own:
            return True
    return False


def close_project(state, user_id, project, outcome):
    """End ``project``: carry its habits to the user profile, take its open work out of the week."""
    project_id = project["id"]
    if (state.get("closedProjects") or {}).get(project_id):
        raise ValueError("이미 끝낸 프로젝트예요.")
    profile = state.get("profile")
    if not profile or profile["status"] != "confirmed" or state.get("profileDraft"):
        raise ValueError("확정한 기본 프로필이 있어야 프로젝트를 끝낼 수 있어요.")
    summary = carry_over(state, user_id, project_id)
    now = datetime.now(timezone.utc).isoformat()
    plan = state.get("plan")
    planned_with = plan["profileId"] if plan else None

    draft = state.get("planDraft")
    if draft and (draft.get("projectId") == project_id
                  or any(entry_owner(draft, e) == project_id and not e["completed"] for e in draft["entries"] if e["kind"] == "task")):
        resolve_plan_draft(state, "keep_current_plan")

    if summary["changes"]:
        resolve_plan_draft(state, "keep_current_plan")
        proposal = {
            "id": str(uuid4()), "profileId": profile["id"], "projectId": None, "projectProfileId": None,
            "sourceProjectId": project_id,
            "proposedChanges": summary["changes"],
            "reason": f"‘{project['title']}’ 프로젝트를 끝내며 기본 프로필로 옮긴 습관: "
                      + ", ".join(f"{c['label']} {c['from']} → {c['to']}" for c in summary["carried"]),
            "sizing": " ".join(c["because"] for c in summary["carried"]), "sizedBy": "evidence",
            "evidenceRecordIds": summary["evidenceRecordIds"], "ruleVersion": CLOSE_RULE_VERSION,
            "status": "pending", "createdAt": now, "decidedAt": None,
        }
        state["profileUpdateProposals"].append(proposal)
        updated = apply_profile_proposal(state, proposal["id"], expected_version=profile["version"])
        if plan and planned_with == profile["id"] and not _affects_open_work(state, plan, project_id, summary["changes"]):
            # Nothing left this week was planned with the old values: the week stays current.
            plan.update(profileId=updated["id"], profileVersion=updated["version"])

    for proposal in state["profileUpdateProposals"]:
        if proposal.get("projectId") == project_id and proposal["status"] == "pending":
            proposal.update(status="rejected", decidedAt=now, closedBy="project_closed")

    removed = 0
    if plan:
        for task_id in [t for t, d in drafts_for_plan(state).items()
                        if entry_owner(plan, next((e for e in plan["entries"] if e["id"] == t), {})) == project_id]:
            close_draft(state, task_id, "plan_replaced")
        gone = [e for e in plan["entries"] if e["kind"] == "task" and not e["completed"] and entry_owner(plan, e) == project_id]
        ends = {e["end"] for e in gone}
        plan["entries"] = [e for e in plan["entries"] if e not in gone and not (e["kind"] == "break" and e["start"] in ends)]
        plan["pendingTasks"] = [t for t in plan.get("pendingTasks") or [] if (t.get("projectId") or plan.get("projectId")) != project_id]
        removed = len(gone)

    state.setdefault("closedProjects", {})[project_id] = {
        "title": project["title"], "outcome": outcome, "closedAt": now,
        "carried": summary["carried"], "kept": summary["kept"], "removedTasks": removed,
    }


def reopen_project(state, project_id):
    """Plan the project again.  What it carried to the user profile stays: that was approved."""
    if not (state.get("closedProjects") or {}).pop(project_id, None):
        raise ValueError("끝낸 프로젝트가 아니에요.")
