"""Server-owned card dependencies, independent of the global mutation revision.

Call public_state from EVERY public state envelope (including adaptive routes). It
never rebases a stored card or mutates the document. Legacy cards without a basis
are only valid at their original revision; they must not be silently upgraded.
"""
from copy import deepcopy
from uuid import uuid4

from .plan_merge import entry_owner


def project_in_plan(state, project_id):
    plan = state.get("plan") or {}
    projects = [*(plan.get("projects") or []), *([plan["project"]] if plan.get("project") else [])]
    return next((p for p in projects if p.get("id") == project_id), None)


def action_basis(state, action, project_id):
    plan = state.get("plan") or {}
    entries = plan.get("entries") or []
    checkin = action.get("kind") == "check_in"
    ids = {r.get("taskId") for r in (action.get("payload") or {}).get("records", [])} if checkin else None
    tasks = [{**e, "projectId": entry_owner(plan, e)} for e in entries
             if e.get("kind") == "task" and (e.get("id") in ids if checkin else entry_owner(plan, e) == project_id)]
    records = [r for r in state.get("executionRecords") or []
               if (r.get("taskId") in ids if checkin else r.get("projectId") == project_id)]
    basis = {"version": 1, "project": project_in_plan(state, project_id),
             "closed": (state.get("closedProjects") or {}).get(project_id),
             "projectProfile": (state.get("projectProfiles") or {}).get(project_id),
             "tasks": sorted(tasks, key=lambda t: t["id"]), "records": records}
    if not checkin:
        # Display preference is not a scheduling dependency. A check-in depends
        # on its target tasks, not a shared plan's outer date range.
        settings = state.get("settings")
        settings = {k: v for k, v in settings.items() if k != "view"} if isinstance(settings, dict) else settings
        basis.update(period=[plan.get("startDate"), plan.get("endDate")],
                     profile=state.get("profile"), profileDraft=state.get("profileDraft"),
                     settings=settings, fixedSchedule=state.get("fixedSchedule"),
                     blockedTimes=state.get("blockedTimes"))
    return deepcopy(basis)


def scoped_action(state, action, project_id):
    """Stamp a NEW card once. Never use this function to refresh an existing card."""
    result = {**action, "id": action.get("id") or str(uuid4()), "projectId": project_id}
    result["basis"] = action_basis(state, result, project_id)
    return result


def action_valid(state, action, project_id):
    if not action:
        return False
    if project_id and (state.get("closedProjects") or {}).get(project_id):
        return False
    if "basis" not in action:
        return action.get("revision") == state.get("revision")
    if action.get("projectId") != project_id:
        return False
    return action["basis"] == action_basis(state, action, project_id)


def public_state(state):
    """Copy public document fields and attach a boolean valid to every thread card."""
    public = deepcopy({key: value for key, value in state.items() if not key.startswith("_")})
    for key, thread in (public.get("plannerThreads") or {}).items():
        action = thread.get("action")
        if action:
            action["valid"] = action_valid(state, action, None if key == "_free" else key)
            if action["valid"]:
                # Response-only revision: stored dependencies and approval evidence never change.
                action["revision"] = state["revision"]
    return public
