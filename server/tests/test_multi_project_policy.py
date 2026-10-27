"""Offline regressions for shared calendars with project-owned policies."""
from copy import deepcopy
from datetime import datetime

import unittest

from server.app.adaptive.full_plan_generator import LLMFullPlanGenerator
from server.app.adaptive.ports import PlanValidationError
from server.app.execution_scheduler import schedule, validate_tasks


def task(title, minutes=20, project="alpha", **extra):
    return dict(title=title, minutes=minutes, projectId=project, doneWhen="결과 저장", dueDate=None, **extra)


def profile(cap=120, starter=None):
    return {"declaredFacts": {"focusMinutes": 40}, "planningPreferences": {
        "blockMinutes": 40, "dailyPlannedMinutes": cap, "starterMinutes": starter,
        "focusTime": "variable", "scheduleStyle": "time_blocks"}, "learnedPatterns": []}


PROJECTS = [{"id": pid, "title": pid, "startDate": "2030-01-07", "dueDate": "2030-01-08"}
            for pid in ("alpha", "beta")]


def state():
    return {"retry_count": 0, "retry_limit": 0, "planning_context": {
        "available_windows": [["2030-01-07T09:00", "2030-01-07T12:00"]],
        "source_planning_context": {"userProfile": profile()}, "project_settings": {
            "alpha": {"max_block_minutes": 40, "user_profile": profile(25, 5), "project_profile_id": "pa"},
            "beta": {"max_block_minutes": 40, "user_profile": profile(37, 7), "project_profile_id": "pb"}},
        "goal": "공동 계획", "profile": {}, "schedule_style": "time_blocks", "max_block_minutes": 40,
        "budget_minutes": 9999, "start_date": "2030-01-07", "end_date": "2030-01-08",
        "projects": deepcopy(PROJECTS), "profile_id": "user", "profile_version": 1, "slots": []}}


class FakeLLM:
    def __init__(self, tasks):
        self.tasks = tasks
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return {"tasks": deepcopy(self.tasks)}


def generate(tasks, value=None):
    llm = FakeLLM(tasks)
    return LLMFullPlanGenerator(llm)(value or state()), llm


def test_unknown_explicit_project_is_rejected():
    for projects in [[], PROJECTS[:1], PROJECTS]:
        with unittest.TestCase().assertRaisesRegex(ValueError, "프로젝트"):
            validate_tasks({"tasks": [task("잘못된 소유자", project="unknown")]}, 40, projects)


def test_missing_project_still_uses_single_project_fallback():
    result = validate_tasks({"tasks": [task("작업", project=None)]}, 40, PROJECTS[:1])
    assert result[0]["projectId"] == "alpha"


def test_mixed_project_caps_starters_and_shared_calendar():
    plan, llm = generate([task("A"), task("B", 30, "beta"), task("A 초과")])
    work = [e for e in plan["entries"] if e["kind"] == "task"]
    assert sum(e["minutes"] for e in work if e.get("projectId") == "alpha") == 25
    assert sum(e["minutes"] for e in work if e.get("projectId") == "beta") == 37
    assert [(e["projectId"], e["minutes"]) for e in work if e.get("starter")] == [("alpha", 5), ("beta", 7)]
    assert plan["pendingTasks"][0]["projectId"] == "alpha"
    assert "25분" in plan["pendingTasks"][0]["reason"]
    assert all(a["end"] <= b["start"] for a, b in zip(plan["entries"], plan["entries"][1:]))
    assert all(e["projectProfileId"] == {"alpha": "pa", "beta": "pb"}[e["projectId"]] for e in work)
    assert llm.calls[0]["schema"]["properties"]["tasks"]["items"]["properties"].get("starter")
    assert llm.calls[0]["context"]["budgetMinutes"] <= 120
    assert llm.calls[0]["context"]["projects"][0]["dailyCapMinutes"] == 25


def test_global_cap_counts_project_starters_once():
    value = state()
    value["planning_context"]["source_planning_context"]["userProfile"] = profile(50, 3)
    plan, _ = generate([task("A"), task("B", 30, "beta")], value)
    work = [e for e in plan["entries"] if e["kind"] == "task"]
    assert sum(e["minutes"] for e in work) <= 50
    assert not any(e.get("starter") and e["minutes"] == 3 for e in work)
    # Out of retries, B is shortened to the time the cap leaves (at least half of it) instead of left out.
    assert [(e["title"], e["minutes"]) for e in work if not e.get("starter")] == [("A", 20), ("B", 18)]
    assert plan["pendingTasks"] == []


def test_previous_pending_identity_includes_project_and_preserves_metadata():
    value = state()
    previous = task("같은 이름", 30, "beta", notBefore="2030-01-08", projectProfileId="pb", custom={"keep": True})
    value["planning_context"]["pending_tasks"] = [previous]
    plan, _ = generate([task("같은 이름")], value)
    restored = next(e for e in plan["pendingTasks"] if e["projectId"] == "beta")
    assert all(restored[k] == v for k, v in previous.items())


def test_scheduler_pending_keeps_not_before():
    raw = task("나중", notBefore="2030-02-01", projectProfileId="pa")
    _, pending = schedule([raw], [(datetime(2030, 1, 7, 9), datetime(2030, 1, 7, 10))])
    assert pending[0]["notBefore"] == raw["notBefore"]
    assert pending[0]["projectProfileId"] == "pa"


def test_unknown_project_becomes_validation_error_in_generator():
    with unittest.TestCase().assertRaises(PlanValidationError):
        generate([task("유령", project="unknown")])


def test_project_cap_does_not_block_other_projects_earlier_day():
    value = state()
    value["planning_context"]["available_windows"].append(["2030-01-08T09:00", "2030-01-08T12:00"])
    plan, _ = generate([task("A1"), task("A2"), task("B", 30, "beta")], value)
    b = next(e for e in plan["entries"] if e["title"] == "B")
    assert b["start"].startswith("2030-01-07")


def test_single_project_only_fills_daily_cap_after_retries_exhausted():
    value = state()
    ctx = value["planning_context"]
    ctx["projects"] = PROJECTS[:1]
    ctx["project_settings"] = {}
    ctx["source_planning_context"]["userProfile"] = profile(60)
    ctx["available_windows"].append(["2030-01-08T09:00", "2030-01-08T12:00"])
    value["retry_limit"] = 1
    with unittest.TestCase().assertRaises(PlanValidationError):
        generate([task("A", 40), task("B", 40)], value)
    value["retry_count"] = 1
    plan, _ = generate([task("A", 40), task("B", 40)], value)
    assert any("(1/2)" in e["title"] for e in plan["entries"])


def test_each_project_starts_once_per_day_and_resets_next_day():
    value = state()
    ctx = value["planning_context"]
    ctx["project_settings"]["alpha"]["user_profile"] = profile(45, 5)
    ctx["available_windows"].append(["2030-01-08T09:00", "2030-01-08T12:00"])
    plan, _ = generate([task("A1"), task("A2"), task("A3"), task("B", 30, "beta")], value)
    for day, expected in [("2030-01-07", 45), ("2030-01-08", 25)]:
        work = [e for e in plan["entries"] if e["kind"] == "task" and e.get("projectId") == "alpha"
                and e["start"].startswith(day)]
        assert sum(e["minutes"] for e in work) == expected
        assert len([e for e in work if e.get("starter")]) == 1


def test_failed_project_allocation_rolls_back_starter_budget_and_breaks():
    plan, _ = generate([task("too big", 30), task("fits"), task("B", 30, "beta")])
    assert [e["title"] for e in plan["pendingTasks"]] == ["too big"]
    work = [e for e in plan["entries"] if e["kind"] == "task"]
    assert sum(e["minutes"] for e in work) == 62
    assert sum(bool(e.get("starter")) for e in work) == 2
    assert all(a["end"] <= b["start"] for a, b in zip(plan["entries"], plan["entries"][1:]))


def test_shared_availability_gaps_and_non_project_work_remain_reserved():
    value = state()
    ctx = value["planning_context"]
    ctx["available_windows"] = [["2030-01-07T09:00", "2030-01-07T09:30"],
                                ["2030-01-07T10:00", "2030-01-07T11:05"]]
    plan, _ = generate([task("A"), task("personal", 20, None), task("B", 30, "beta")], value)
    assert not plan["pendingTasks"]
    for entry in plan["entries"]:
        assert any(begin <= entry["start"] < entry["end"] <= end for begin, end in ctx["available_windows"])
    assert all(a["end"] <= b["start"] for a, b in zip(plan["entries"], plan["entries"][1:]))


def test_unknown_owner_cannot_be_hidden_by_short_task_repair():
    value = state()
    value["planning_context"]["projects"] = deepcopy(PROJECTS[:1])
    with unittest.TestCase().assertRaises(PlanValidationError):
        generate([task("valid", 10), task("invalid", 10, "unknown")], value)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(fn) for name, fn in sorted(globals().items())
                              if name.startswith("test_") and callable(fn))

