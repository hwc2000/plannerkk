"""Focused regressions: check-in evidence, session identity and scoped cards (fake LLM/temp DB)."""
import os
import unittest
from unittest import mock

from server.tests import test_checkin as checkins
from server.tests.test_project_independence import ESSAY, APP
from server.app.execution_service import ExecutionRecordInput


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"})
class CheckInScopeTests(unittest.TestCase):
    _base = checkins.CheckInTests._base
    setUp, tearDown = checkins.CheckInTests.setUp, _base.tearDown
    call, draft, plan, tasks = _base.call, _base.draft, _base.plan, staticmethod(_base.tasks)
    check_in = checkins.CheckInTests.check_in

    def mutate(self, fn):
        self.revision = self.store.change(self.revision, fn)["revision"]

    def test_partial_can_overrun_completed_has_minutes_and_missing_reason_stays_null(self):
        self.llm.replies["planner_checkin"] = checkins.answer([
            {"taskId": self.first["id"], "actualMinutes": 45, "reasonCode": None, "quote": "45분"},
            {"taskId": self.second["id"], "actualMinutes": 35, "reasonCode": None, "quote": "35분"}])
        self.check_in(text="45분 했고 두번째는 35분에 끝냈어", **{self.first["id"]: "partial", self.second["id"]: "completed"})
        state = self.call("/api/execution/chat/check-in/confirm", project=ESSAY)
        self.assertEqual([(r["actualMinutes"], r["reasonCode"]) for r in state["executionRecords"]], [(45, None), (35, None)])

    def test_record_input_accepts_unspecified_failure_reason(self):
        record = ExecutionRecordInput(planId="p", taskId="t", result="partial", actualMinutes=45)
        self.assertIsNone(record.reasonCode)

    def test_session_is_stored_once_and_telling_again_revises_the_same_records(self):
        self.call("/api/execution/task", planId=self.week["id"], taskId=self.first["id"], completed=True)
        card = self.check_in(**{self.first["id"]: "completed", self.second["id"]: "completed"})["plannerThreads"]["essay"]["action"]
        self.assertTrue(card["valid"])
        self.assertEqual(card["projectId"], "essay")
        payload = card["payload"]
        self.assertEqual(payload["session"]["id"], card["id"])
        self.assertEqual(payload["date"], payload["session"]["date"])
        state = self.call("/api/execution/chat/check-in/confirm", project=ESSAY)
        self.assertEqual(len(state["checkInSessions"]), 1)
        session = state["checkInSessions"][0]
        self.assertEqual(session["projectId"], "essay")
        for r in state["executionRecords"]:
            self.assertEqual((r["checkInId"], r["checkInDate"]), (session["id"], session["date"]))
        self.check_in(**{self.first["id"]: "completed"})
        state = self.call("/api/execution/chat/check-in/confirm", project=ESSAY)
        self.assertEqual(len(state["executionRecords"]), 2)
        self.assertEqual(len(state["checkInSessions"]), 2)

    def test_bare_record_must_belong_to_the_task_project(self):
        self.call("/api/execution/task", planId=self.week["id"], taskId=self.first["id"], completed=True)
        self.mutate(lambda d: d["executionRecords"][-1].update(projectId="app"))
        self.check_in(status=400, **{self.first["id"]: "completed"})

    def test_bare_record_survives_other_project_merge_and_gets_actual_minutes(self):
        self.call("/api/execution/task", planId=self.week["id"], taskId=self.first["id"], completed=True)
        self.llm.replies["planner_checkin"] = checkins.answer([
            {"taskId": self.first["id"], "actualMinutes": 35, "reasonCode": None, "quote": "35분"}])
        self.check_in(text="35분", **{self.first["id"]: "completed"})
        self.plan(APP, "로그인")
        state = self.call("/api/execution/chat/check-in/confirm", project=ESSAY)
        self.assertEqual(len(state["executionRecords"]), 1)
        self.assertEqual(state["executionRecords"][0]["actualMinutes"], 35)
        self.assertEqual(state["executionRecords"][0]["checkInId"], state["checkInSessions"][0]["id"])

    def test_unrelated_plan_merge_preserves_card_and_confirms_against_current_plan(self):
        self.check_in(**{self.first["id"]: "completed"})
        week = self.plan(APP, "로그인")
        state = self.call("/api/execution/chat/check-in/confirm", project=ESSAY)
        self.assertEqual(state["executionRecords"][-1]["planId"], week["id"])

    def test_stale_global_revision_still_conflicts(self):
        self.check_in(**{self.first["id"]: "completed"})
        stale = self.revision
        self.mutate(lambda d: d.update(unrelated=True))
        response = self.client.post("/api/execution/chat/check-in/confirm", json={"revision": stale, "project": ESSAY})
        self.assertEqual(response.status_code, 409)

    def test_relevant_task_change_invalidates_card_even_after_chat(self):
        self.check_in(**{self.first["id"]: "completed"})
        def change(d):
            next(t for t in d["plan"]["entries"] if t["id"] == self.first["id"])["minutes"] += 5
        self.mutate(change)
        state = self.call("/api/execution/chat/message", project=ESSAY, text="안녕", consent=True)
        action = state["plannerThreads"]["essay"]["action"]
        self.assertTrue(action is None or action["valid"] is False)
        self.call("/api/execution/chat/check-in/confirm", 409, project=ESSAY)
        self.assertEqual(self.store.read()["executionRecords"], [])

    def test_confirm_revalidates_ownership_record_and_closed_project(self):
        for mutation in (lambda d: next(t for t in d["plan"]["entries"] if t["id"] == self.first["id"]).update(projectId="app"),
                         lambda d: d.setdefault("closedProjects", {}).update(essay={"title": "closed"}),
                         lambda d: d["executionRecords"].append({"id": "new", "planId": d["plan"]["id"], "taskId": self.first["id"], "result": "completed"})):
            with self.subTest(mutation=mutation):
                original = self.store.read()
                self.check_in(**{self.first["id"]: "completed"})
                self.mutate(mutation)
                self.call("/api/execution/chat/check-in/confirm", 409, project=ESSAY)
                self.mutate(lambda d: (d.clear(), d.update(original)))

    def test_duplicate_task_ids_are_rejected_and_max20_remains_enforced(self):
        item = {"taskId": self.first["id"], "result": "completed"}
        self.call("/api/execution/chat/check-in", 422, project=ESSAY, results=[item, item])
        self.call("/api/execution/chat/check-in", 422, project=ESSAY, results=[item] * 21)

    def test_known_daily_state_shared_across_projects_and_repeated_quotes_are_allowed(self):
        self.llm.replies["planner_checkin"] = checkins.answer(session={
            "place": ("도서관", "도서관에서 집중과 컨디션 좋았어"),
            "focus": ("good", "도서관에서 집중과 컨디션 좋았어"),
            "condition": ("good", "도서관에서 집중과 컨디션 좋았어")})
        self.check_in(text="도서관에서 집중과 컨디션 좋았어", **{self.first["id"]: "completed"})
        state = self.call("/api/execution/chat/check-in/confirm", project=ESSAY)
        session = state["checkInSessions"][0]
        self.assertEqual((session["focus"], session["condition"]), ("good", "good"))
        week = self.plan(APP, "로그인")
        task = self.tasks(week, "app")[0]
        state = self.check_in(project=APP, **{task["id"]: "completed"})
        payload = state["plannerThreads"]["app"]["action"]["payload"]
        self.assertEqual(payload["knownDaily"]["place"], "도서관")
        self.assertEqual(payload["session"]["place"], "도서관")
        self.assertIsNone(payload["session"]["atmosphere"])

    def test_feedback_has_timefit_date_and_rejects_ghost_or_closed_projects(self):
        self.call("/api/execution/projects/ghost/feedback", 400, load="right")
        state = self.call("/api/execution/projects/essay/feedback", load="right", timeFit="too_short")
        item = state["projectFeedback"]["essay"][-1]
        self.assertEqual(item["timeFit"], "too_short")
        self.assertRegex(item["date"], r"^\d{4}-\d{2}-\d{2}$")
        self.call("/api/execution/projects/essay/feedback", 422, load="right", timeFit="invented")
        self.call("/api/execution/projects/essay/close", project=ESSAY, outcome="completed")
        self.call("/api/execution/projects/essay/feedback", 400, load="right")

    def test_public_action_helper_keeps_safe_cards_without_refreshing_unsafe_ones(self):
        from server.app import planner_actions
        state = self.store.read()
        action = planner_actions.scoped_action(state, {"kind": "project_settings", "payload": {"overrides": {"blockMinutes": 15}}}, "essay")
        state["plannerThreads"]["essay"] = {"messages": [], "action": action}
        state["revision"] += 1
        state["projectProfiles"]["app"] = {"overrides": {"blockMinutes": 40}}
        public = planner_actions.public_state(state)
        self.assertTrue(public["plannerThreads"]["essay"]["action"]["valid"])
        self.assertEqual(public["plannerThreads"]["essay"]["action"]["revision"], state["revision"])
        self.assertNotIn("valid", action)
        state["projectProfiles"]["essay"] = {"overrides": {"blockMinutes": 50}}
        self.assertFalse(planner_actions.public_state(state)["plannerThreads"]["essay"]["action"]["valid"])
        legacy = {"kind": "project_settings", "payload": {}, "revision": state["revision"] - 1}
        self.assertFalse(planner_actions.action_valid(state, legacy, "essay"))

    def test_feedback_accepts_independent_fields_and_rejects_empty_answers(self):
        for fields in ({"timeFit": "too_short"}, {"timeFit": "unknown"}, {"note": "  일정은 좋아요  "}):
            with self.subTest(fields=fields):
                state = self.call("/api/execution/projects/essay/feedback", **fields)
                item = state["projectFeedback"]["essay"][-1]
                self.assertIsNone(item["load"])
                self.assertEqual(item["note"], fields.get("note", "").strip())
        for fields in ({}, {"load": None, "timeFit": None, "note": "  \t"}):
            self.call("/api/execution/projects/essay/feedback", 422, **fields)

    def test_display_view_does_not_invalidate_planning_card(self):
        from server.app.planner_actions import scoped_action, action_valid
        state = self.store.read()
        action = scoped_action(state, {"kind": "project_settings", "payload": {}}, "essay")
        state["settings"]["view"] = "different-display"
        self.assertTrue(action_valid(state, action, "essay"))
        state["settings"]["slots"] = [{"day": 1, "hour": 10}]
        self.assertFalse(action_valid(state, action, "essay"))

    def test_checkin_survives_shared_period_change_but_not_project_profile_change(self):
        self.check_in(**{self.first["id"]: "partial"})
        self.mutate(lambda d: d["plan"].update(startDate="2020-01-01", endDate="2030-01-01"))
        state = self.call("/api/execution/chat/check-in/confirm", project=ESSAY)
        self.assertIsNone(state["executionRecords"][-1]["reasonCode"])
        self.check_in(**{self.second["id"]: "partial"})
        self.mutate(lambda d: d["projectProfiles"].update(essay={"overrides": {"blockMinutes": 55}}))
        self.call("/api/execution/chat/check-in/confirm", 409, project=ESSAY)

    def test_checkin_correction_normalizes_hours_and_confirms_exact_minutes(self):
        for text, minutes in (("한 시간 했어", 60), ("아니 1시간 반 했어", 90)):
            self.llm.replies["planner_checkin"] = checkins.answer([
                {"taskId": self.first["id"], "actualMinutes": minutes, "reasonCode": None, "quote": text}])
            state = self.check_in(text=text, **{self.first["id"]: "partial"})
            self.assertEqual(state["plannerThreads"]["essay"]["action"]["payload"]["records"][0]["actualMinutes"], minutes)
        state = self.call("/api/execution/chat/check-in/confirm", project=ESSAY)
        self.assertEqual(state["executionRecords"][-1]["actualMinutes"], 90)
        self.assertIsNone(state["executionRecords"][-1]["reasonCode"])

    def test_client_cannot_forge_recovery_approval(self):
        self.call("/api/execution/records", 400, planId=self.week["id"], taskId=self.first["id"], result="partial", actualMinutes=5,
                  reasonCode="fatigue", recoveryAction="shrink")
        self.assertEqual(self.store.read()["executionRecords"], [])
