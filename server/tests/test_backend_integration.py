"""Public envelopes and scoped evidence regressions; temp SQLite and fake LLM only."""
import os
import unittest
from datetime import date, datetime
from unittest import mock

from server.tests import test_checkin as checkins
from server.tests.test_project_independence import APP, ESSAY
from server.app.execution_api import build_full_plan_context
from server.app.planner import ProjectContext
from server.app.planner_skills import ChatContext, profile_view
from server.app.user_insights import insights_for_ai


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"})
class BackendIntegrationTests(unittest.TestCase):
    _base = checkins.CheckInTests._base
    setUp, tearDown = checkins.CheckInTests.setUp, _base.tearDown
    call, draft, plan, tasks = _base.call, _base.draft, _base.plan, staticmethod(_base.tasks)
    check_in = checkins.CheckInTests.check_in

    def test_get_and_execution_mutations_expose_valid_current_card_without_rebasing_storage(self):
        self.check_in(**{self.first["id"]: "completed"})
        original = self.store.read()["plannerThreads"]["essay"]["action"]
        self.plan(APP, "로그인")
        state = self.client.get("/api/execution").json()
        card = state["plannerThreads"]["essay"]["action"]
        self.assertTrue(card["valid"])
        self.assertEqual(card["revision"], self.revision)
        state = self.call("/api/execution/projects/app/feedback", load="right")
        self.assertTrue(state["plannerThreads"]["essay"]["action"]["valid"])
        state = self.call("/api/execution/settings", settings=state["settings"], method="put")
        self.assertTrue(state["plannerThreads"]["essay"]["action"]["valid"])
        self.assertEqual(self.store.read()["plannerThreads"]["essay"]["action"], original)

    def test_adaptive_response_preserves_other_project_card(self):
        week = self.plan(APP, "로그인")
        self.check_in(**{self.first["id"]: "completed"})
        task = self.tasks(week, "app")[0]
        state = self.call("/api/adaptive/check-in", taskId=task["id"], checkIn={"completed": True})
        card = state["plannerThreads"]["essay"]["action"]
        self.assertTrue(card["valid"])
        self.assertEqual(card["revision"], self.revision)
        self.call("/api/execution/chat/check-in/confirm", project=ESSAY)

    def test_general_chat_confirm_keeps_original_scope_after_other_project_mutation(self):
        from server.app.planner_actions import scoped_action
        def seed(doc):
            doc["plannerThreads"]["essay"] = {"messages": [], "action": scoped_action(doc,
                {"kind": "project_settings", "payload": {"projectId": "essay", "overrides": {"blockMinutes": 15}}}, "essay")}
        self.revision = self.store.change(self.revision, seed)["revision"]
        original = self.store.read()["plannerThreads"]["essay"]["action"]
        self.plan(APP, "로그인")
        self.llm.route = {"skill": "confirm", "lookups": [], "reply": ""}
        state = self.call("/api/execution/chat/message", project=ESSAY, text="응", consent=True)
        card = state["plannerThreads"]["essay"]["action"]
        self.assertTrue(card["valid"])
        self.assertEqual((card["id"], card["basis"]), (original["id"], original["basis"]))
        self.assertEqual(self.llm.chat_calls[-1]["context"]["waitingCard"]["kind"], "project_settings")
        self.assertEqual(self.store.read()["plannerThreads"]["essay"]["action"], original)
        # A relevant change makes confirm see no pending card rather than silently restamping it.
        self.revision = self.store.change(self.revision, lambda d: d["projectProfiles"].update(essay={"id": "changed"}))["revision"]
        state = self.call("/api/execution/chat/message", project=ESSAY, text="응", consent=True)
        self.assertIsNone(state["plannerThreads"]["essay"]["action"])

    def test_inherited_daily_values_are_visible_but_not_new_project_evidence(self):
        self.llm.replies["planner_checkin"] = checkins.answer(session={
            "place": ("도서관", "도서관에서"), "focus": ("good", "집중 좋았어")})
        self.check_in(text="도서관에서 집중 좋았어", **{self.first["id"]: "completed"})
        self.call("/api/execution/chat/check-in/confirm", project=ESSAY)
        week = self.plan(APP, "로그인")
        task = self.tasks(week, "app")[0]
        state = self.check_in(project=APP, **{task["id"]: "completed"})
        payload = state["plannerThreads"]["app"]["action"]["payload"]
        self.assertEqual(payload["session"]["place"], "도서관")
        state = self.call("/api/execution/chat/check-in/confirm", project=APP)
        self.assertEqual(insights_for_ai(state, project_id="app")["candidatePatterns"], [])
        self.assertIsNone(state["executionRecords"][-1]["focus"])
        self.assertEqual(state["checkInSessions"][-1]["inheritedDaily"]["place"], "도서관")

    def test_reported_place_does_not_inherit_positive_focus_evidence(self):
        self.llm.replies["planner_checkin"] = checkins.answer(session={"focus": ("good", "집중 좋았어")})
        self.check_in(text="집중 좋았어", **{self.first["id"]: "completed"})
        self.call("/api/execution/chat/check-in/confirm", project=ESSAY)
        week = self.plan(APP, "로그인")
        task = self.tasks(week, "app")[0]
        self.llm.replies["planner_checkin"] = checkins.answer(session={"place": ("도서관", "도서관에서")})
        state = self.check_in(project=APP, text="도서관에서 했어", **{task["id"]: "completed"})
        self.assertEqual(state["plannerThreads"]["app"]["action"]["payload"]["session"]["focus"], "good")
        state = self.call("/api/execution/chat/check-in/confirm", project=APP)
        pattern = insights_for_ai(state, project_id="app")["candidatePatterns"][0]
        self.assertEqual((pattern["knownFocus"], pattern["unknownFocus"]), (0, 1))
        response = self.client.get("/api/execution/insights?projectId=app").json()
        self.assertEqual(response["scope"], {"kind": "project", "projectId": "app"})
        self.assertEqual(response["candidatePatterns"][0]["knownFocus"], 0)

    def test_mixed_plan_llm_receives_per_project_insights(self):
        self.call("/api/execution/plan", goal="함께 계획", startDate="2030-01-07", consent=True, projects=[ESSAY, APP])
        by_project = self.llm.plan_calls[-1]["context"]["userInsights"]["byProject"]
        self.assertEqual(by_project["essay"]["scope"]["projectId"], "essay")
        self.assertEqual(by_project["app"]["scope"]["projectId"], "app")

    def context(self, projects):
        state = self.store.read()
        return build_full_plan_context(state=state, user_id=self.store.user_id, goal="다음 계획",
            start_date=date.fromisoformat(self.week["startDate"]), project=projects[0] if len(projects) == 1 else None,
            projects=projects, current_plan=None, events=[], now=datetime.fromisoformat(self.week["startDate"]))

    def test_plan_context_preserves_timefit_date_and_project_scoping(self):
        self.call("/api/execution/projects/essay/feedback", load="too_much", timeFit="too_short", note="시간 부족")
        context = self.context([ProjectContext.model_validate(ESSAY)])
        feedback = context["project_feedback"]["essay"][-1]
        self.assertEqual(feedback["timeFit"], "too_short")
        self.assertRegex(feedback["date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(context["user_insights"]["scope"]["projectId"], "essay")
        mixed = self.context([ProjectContext.model_validate(ESSAY), ProjectContext.model_validate(APP)])
        self.assertEqual(mixed["project_settings"]["app"]["user_insights"]["scope"]["projectId"], "app")

    def test_chat_profile_insights_are_project_scoped(self):
        state = self.store.read()
        ctx = ChatContext(state=state, user_id=self.store.user_id, project=ESSAY,
                          today=date.today(), now=datetime.now())
        self.assertEqual(profile_view(ctx)["scope"], {"kind": "project", "projectId": "essay"})

    def test_confirmed_declaration_exposes_kind_source_and_event_evidence(self):
        self.llm.replies["planner_checkin"] = checkins.answer(insights={"place": ("집", "보통 집에서")})
        self.check_in(text="보통 집에서 해", **{self.first["id"]: "completed"})
        state = self.call("/api/execution/chat/check-in/confirm", project=ESSAY)
        session = state["checkInSessions"][-1]
        response = self.client.get("/api/execution/insights").json()
        slot = next(s for s in response["slots"] if s["key"] == "place")
        self.assertEqual((slot["kind"], slot["source"]), ("declared", "check_in"))
        sample = slot["evidence"]["samples"][-1]
        self.assertEqual((sample["eventId"], sample["date"], sample["projectId"]),
                         (session["id"], session["date"], "essay"))
        self.assertIn("candidatePatterns", response)
