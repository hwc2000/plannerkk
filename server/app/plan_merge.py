from datetime import date

FREE = "_free"


def thread_key(project_id: str | None) -> str:
    return project_id or FREE


def entry_owner(plan: dict, entry: dict) -> str | None:
    return entry.get("projectId") or plan.get("projectId")


def active_plan(state: dict, today: date) -> dict | None:
    plan = state.get("plan")
    return plan if plan and plan["endDate"] >= today.isoformat() else None


def _scope(scope) -> set:
    """One project id (None: work outside projects) or several, as a set."""
    return set(scope) if isinstance(scope, (set, frozenset, list, tuple)) else {scope}


def kept_entries(plan: dict, scope_id) -> list[dict]:
    """The week's entries a plan of ``scope_id`` (one project id, or a set of them) leaves as they are:
    every other project's tasks, and finished tasks."""
    scope = _scope(scope_id)
    tasks = [{**e, "projectId": entry_owner(plan, e)} for e in plan["entries"]
             if e["kind"] == "task" and (entry_owner(plan, e) not in scope or e["completed"])]
    ends = {e["end"] for e in tasks}
    breaks = [dict(e) for e in plan["entries"] if e["kind"] == "break" and e["start"] in ends]
    return tasks + breaks


def merge_into(current: dict, draft: dict, scope_project, goal) -> dict:
    """Put a draft for one project (or several planned together) into the week, keeping the rest.

    ``scope_project``: the project dict, a list of them, or None (work outside projects).
    ``goal``: the goal text (one project), or {project id: goal} for several.
    """
    scope_projects = scope_project if isinstance(scope_project, list) else ([scope_project] if scope_project else [])
    scope_ids = {p["id"] for p in scope_projects} or {None}
    kept = kept_entries(current, scope_ids)
    kept_ids = {e["id"] for e in kept}
    known = {p["id"]: p for p in (current.get("projects") or ([current["project"]] if current.get("project") else []))}
    for p in scope_projects:
        known[p["id"]] = p
    # A replan of this project copies its finished tasks into the draft; keep one of each.
    entries = sorted([*kept, *(e for e in draft["entries"] if e["id"] not in kept_ids)], key=lambda e: e["start"])
    owners = {e.get("projectId") for e in entries if e["kind"] == "task"} | scope_ids
    projects = [p for pid, p in known.items() if pid in owners]
    goals = current.get("projectGoals") or {thread_key(current.get("projectId")): current["goal"]}
    new_goals = {thread_key(pid): text for pid, text in goal.items()} if isinstance(goal, dict) \
        else {thread_key(next(iter(scope_ids))): goal}
    goals = {key: value for key, value in {**goals, **new_goals}.items()
             if key in {thread_key(o) for o in owners}}
    titles = {thread_key(p["id"]): p["title"] for p in projects}
    pending = [p for p in current.get("pendingTasks", [])
               if (p.get("projectId") or current.get("projectId")) not in scope_ids] + draft["pendingTasks"]
    single = projects[0] if len(projects) == 1 and None not in owners else None
    return {**draft, "entries": entries, "pendingTasks": pending, "projects": projects,
            "project": single, "projectId": single["id"] if single else None, "projectGoals": goals,
            # Entries carry their own project's settings version; a plan-wide one only fits one project.
            "projectProfileId": draft.get("projectProfileId") if single else None,
            "goal": next(iter(goals.values())) if len(goals) == 1 else "\n".join(
                f"[{titles.get(key, '자유 계획')}] {value}" for key, value in goals.items())}
