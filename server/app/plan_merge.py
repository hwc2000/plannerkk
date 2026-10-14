"""Project-scoped planning inside one shared weekly plan.

Each project chat plans only its own part of the week.  Tasks of other projects
and every completed task stay exactly where they are, and the new tasks are
placed into the time they leave free.
"""
from datetime import date

FREE = "_free"  # thread and goal key for work that belongs to no project


def thread_key(project_id: str | None) -> str:
    return project_id or FREE


def entry_owner(plan: dict, entry: dict) -> str | None:
    # Entries saved before multi-project weeks carry the plan's single project.
    return entry.get("projectId") or plan.get("projectId")


def active_plan(state: dict, today: date) -> dict | None:
    plan = state.get("plan")
    return plan if plan and plan["endDate"] >= today.isoformat() else None


def kept_entries(plan: dict, scope_id: str | None) -> list[dict]:
    """Entries a project-scoped plan must not touch: other projects' tasks and finished work."""
    tasks = [{**e, "projectId": entry_owner(plan, e)} for e in plan["entries"]
             if e["kind"] == "task" and (entry_owner(plan, e) != scope_id or e["completed"])]
    ends = {e["end"] for e in tasks}
    breaks = [dict(e) for e in plan["entries"] if e["kind"] == "break" and e["start"] in ends]
    return tasks + breaks


def merge_into(current: dict, draft: dict, scope_project: dict | None, goal: str) -> dict:
    scope_id = scope_project["id"] if scope_project else None
    kept = kept_entries(current, scope_id)
    known = {p["id"]: p for p in (current.get("projects") or ([current["project"]] if current.get("project") else []))}
    if scope_project:
        known[scope_id] = scope_project
    entries = sorted([*kept, *draft["entries"]], key=lambda e: e["start"])
    owners = {e.get("projectId") for e in entries if e["kind"] == "task"} | {scope_id}
    projects = [p for pid, p in known.items() if pid in owners]
    goals = current.get("projectGoals") or {thread_key(current.get("projectId")): current["goal"]}
    goals = {key: value for key, value in {**goals, thread_key(scope_id): goal}.items()
             if key in {thread_key(o) for o in owners}}
    titles = {thread_key(p["id"]): p["title"] for p in projects}
    pending = [p for p in current.get("pendingTasks", [])
               if (p.get("projectId") or current.get("projectId")) != scope_id] + draft["pendingTasks"]
    single = projects[0] if len(projects) == 1 and None not in owners else None
    return {**draft, "entries": entries, "pendingTasks": pending, "projects": projects,
            "project": single, "projectId": single["id"] if single else None, "projectGoals": goals,
            "goal": next(iter(goals.values())) if len(goals) == 1 else "\n".join(
                f"[{titles.get(key, '자유 계획')}] {value}" for key, value in goals.items())}
