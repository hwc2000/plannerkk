"""Optional place hints must be evidence-backed and never take over the plan."""
import unittest
from copy import deepcopy

from server.app.environment_suggestions import suggest_environments


def evidence(value, days=3):
    return {"field": "place", "value": value, "optional": True, "maxShare": .6,
            "evidence": {"status": "supported", "knownFocus": days, "knownFocusDays": days,
                         "goodFocus": days, "goodFocusRatio": 1.0}}


def entries(count=5, owner="a"):
    return [{"id": str(i), "kind": "task", "title": "공부하기", "minutes": 30,
             "projectId": owner, "start": f"2030-01-07T{9+i:02}:00", "completed": False}
            for i in range(count)]


class EnvironmentSuggestionTests(unittest.TestCase):
    def test_never_adds_location_without_supported_evidence(self):
        source = entries()
        self.assertEqual(suggest_environments(source, {"recommendations": []}), source)

    def test_location_is_optional_metadata_not_title_and_no_more_than_sixty_percent(self):
        source = entries()
        before = deepcopy(source)
        result = suggest_environments(source, {"recommendations": [evidence("카페")]})
        hints = [e for e in result if e.get("environmentSuggestion")]
        self.assertEqual(len(hints), 3)
        self.assertTrue(all(e["title"] == "공부하기" for e in result))
        self.assertTrue(all(e["environmentSuggestion"]["optional"] for e in hints))
        self.assertEqual(source, before)
        self.assertTrue(all(e["environmentSuggestion"]["place"] == "카페" for e in hints))

    def test_single_task_is_not_locked_to_a_place(self):
        self.assertNotIn("environmentSuggestion", suggest_environments(entries(1), {"recommendations": [evidence("집")]})[0])

    def test_rotates_only_observed_supported_alternatives(self):
        result = suggest_environments(entries(6), {"recommendations": [evidence("집"), evidence("도서관")]})
        values = [e["environmentSuggestion"]["place"] for e in result if e.get("environmentSuggestion")]
        self.assertEqual(values, ["집", "도서관", "집"])

    def test_project_evidence_does_not_leak_to_other_project(self):
        source = entries(3, "a") + entries(3, "b")
        result = suggest_environments(source, {"byProject": {"a": {"recommendations": [evidence("집")]}, "b": {"recommendations": []}}})
        self.assertTrue(any(e.get("environmentSuggestion") for e in result if e["projectId"] == "a"))
        self.assertFalse(any(e.get("environmentSuggestion") for e in result if e["projectId"] == "b"))

    def test_completed_and_starter_tasks_do_not_get_new_hints(self):
        source = entries()
        source[0]["completed"] = True
        source[1]["starter"] = True
        result = suggest_environments(source, {"recommendations": [evidence("집")]})
        self.assertNotIn("environmentSuggestion", result[0])
        self.assertNotIn("environmentSuggestion", result[1])

    def test_generator_connects_project_evidence_to_optional_entry_hints(self):
        from server.tests.test_multi_project_policy import generate, state, task
        value = state()
        value["planning_context"]["project_settings"]["alpha"]["user_profile"]["planningPreferences"].update(
            dailyPlannedMinutes=120, starterMinutes=None)
        value["planning_context"]["user_insights"] = {"byProject": {
            "alpha": {"recommendations": [evidence("도서관")]}, "beta": {"recommendations": []}}}
        plan, _ = generate([task("개념 복습"), task("문제 풀이"), task("정리")], value)
        work = [entry for entry in plan["entries"] if entry["kind"] == "task" and not entry.get("starter")]
        self.assertEqual(sum(bool(e.get("environmentSuggestion")) for e in work), 1)
        self.assertEqual(next(e["environmentSuggestion"]["place"] for e in work if e.get("environmentSuggestion")), "도서관")

    def test_refuses_unsupported_or_unscoped_metadata(self):
        bad = evidence("카페")
        bad["evidence"]["status"] = "insufficient"
        result = suggest_environments(entries(), {"recommendations": [bad]})
        self.assertFalse(any(e.get("environmentSuggestion") for e in result))
