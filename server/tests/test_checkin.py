"""Check-in in a project's conversation: taps and one sentence become records, after confirming."""
import os
import unittest
from unittest import mock

from server.app.planner_checkin import CHECKIN_INSTRUCTIONS
from server.app.user_insights import SLOTS
from server.tests import test_project_independence as projects
from server.tests.test_project_independence import APP, ESSAY


def answer(tasks=(), note="", session=None, insights=None):
    """The model's check-in answer: each value with the words it was taken from."""
    told = lambda values, keys: {k: {"value": values[k][0], "quote": values[k][1]} if k in values else {"value": None, "quote": None} for k in keys}
    return {"tasks": list(tasks), "note": note, "session": told(session or {}, ("place", "atmosphere", "focus", "condition")),
            "insights": told(insights or {}, SLOTS)}


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"})
class CheckInTests(unittest.TestCase):
    # The project tests' app and helpers, without collecting their tests here again.
    _base = projects.ProjectIndependenceTests
    tearDown, call, draft, plan, tasks = _base.tearDown, _base.call, _base.draft, _base.plan, staticmethod(_base.tasks)

    def setUp(self):
        self._base.setUp(self)
        self.week = self.plan(ESSAY, "초안")
        self.first, self.second = self.tasks(self.week, "essay")

    def check_in(self, status=200, project=ESSAY, text="", asked=(), **results):
        return self.call("/api/execution/chat/check-in", status, consent=True, project=project, text=text, asked=list(asked),
                         results=[{"taskId": task_id, "result": result} for task_id, result in results.items()])

    def test_one_sentence_fills_the_fields_and_nothing_is_saved_before_confirming(self):
        self.llm.replies["planner_checkin"] = answer(
            [{"taskId": self.second["id"], "actualMinutes": 12, "reasonCode": "fatigue", "quote": "12분 했는데 피곤해서"}],
            session={"place": ("도서관", "도서관에서"), "focus": ("poor", "집중이 안 됐어"), "condition": ("poor", "피곤해서")})
        state = self.check_in(text="도서관에서 12분 했는데 피곤해서 집중이 안 됐어",
                              **{self.first["id"]: "completed", self.second["id"]: "partial"})
        call = self.llm.chat_calls[-1]
        self.assertEqual(call["instructions"], CHECKIN_INSTRUCTIONS)
        self.assertEqual([t["result"] for t in call["context"]["tasks"]], ["completed", "partial"])
        self.assertEqual(state["executionRecords"], [])  # only a card so far
        card = state["plannerThreads"]["essay"]["action"]
        self.assertEqual(card["kind"], "check_in")
        done, partly = card["payload"]["records"]
        self.assertEqual((done["result"], done["place"], done["focus"]), ("completed", "도서관", "poor"))
        self.assertEqual((partly["actualMinutes"], partly["reasonCode"], partly["condition"]), (12, "fatigue", "poor"))

        state = self.call("/api/execution/chat/check-in/confirm", project=ESSAY)
        records = state["executionRecords"]
        self.assertEqual([(r["result"], r["place"], r["projectId"]) for r in records],
                         [("completed", "도서관", "essay"), ("partial", "도서관", "essay")])
        self.assertIsNone(state["plannerThreads"]["essay"]["action"])
        self.assertIn("기록했어요", state["plannerThreads"]["essay"]["messages"][-1]["content"])
        task = next(e for e in state["plan"]["entries"] if e["id"] == self.first["id"])
        self.assertTrue(task["completed"])

    def test_code_keeps_the_taps_and_drops_what_does_not_fit(self):
        self.llm.replies["planner_checkin"] = answer(
            [{"taskId": self.first["id"], "actualMinutes": 999, "reasonCode": "made_up", "quote": "좀 했어"}],
            session={"place": ("  ", "좀 했어"), "focus": ("great", "좀 했어")})
        state = self.check_in(text="좀 했어", **{self.first["id"]: "partial", self.second["id"]: "not_started"})
        partly, missed = state["plannerThreads"]["essay"]["action"]["payload"]["records"]
        self.assertEqual((partly["result"], partly["actualMinutes"], partly["reasonCode"]), ("partial", None, None))
        self.assertEqual((missed["actualMinutes"], missed["reasonCode"]), (0, None))
        self.assertEqual((partly["place"], partly["focus"]), (None, None))

    def test_a_value_counts_only_with_the_users_own_words(self):
        # "응 다 했어" says nothing about where or how: a value without words from the message is dropped.
        self.llm.replies["planner_checkin"] = answer(
            session={"place": ("도서관", "도서관"), "focus": ("good", "집중 잘 됨"), "atmosphere": ("quiet", "다 했어"),
                     "condition": ("good", "컨디션 좋아")},
            insights={"tone": ("casual", "반말로 해 줘")})
        state = self.check_in(text="응 다 했어", **{self.first["id"]: "completed"})
        payload = state["plannerThreads"]["essay"]["action"]["payload"]
        [record] = payload["records"]
        self.assertEqual((record["place"], record["focus"]), (None, None))       # words not in the message
        self.assertEqual((record["atmosphere"], record["condition"]), ("quiet", None))  # condition's quote was not said
        self.assertEqual(payload["insights"], {})

    def test_saving_taps_alone_needs_no_ai(self):
        calls = len(self.llm.chat_calls)
        self.call("/api/execution/chat/check-in", consent=False, project=ESSAY, text="",
                  results=[{"taskId": self.first["id"], "result": "completed"}])
        self.assertEqual(len(self.llm.chat_calls), calls)
        state = self.call("/api/execution/chat/check-in/confirm", project=ESSAY)
        self.assertEqual(state["executionRecords"][0]["result"], "completed")

    def test_only_this_projects_tasks_and_telling_again_revises_the_record(self):
        self.check_in(status=400, project=APP, **{self.first["id"]: "completed"})
        self.llm.replies["planner_checkin"] = answer(session={"place": ("집", "집에서"), "focus": ("good", "집중 잘 됐어")})
        self.check_in(text="집에서 했고 집중 잘 됐어", **{self.first["id"]: "completed"})
        self.call("/api/execution/chat/check-in/confirm", project=ESSAY)
        self.check_in(**{self.first["id"]: "partial"})
        state = self.call("/api/execution/chat/check-in/confirm", project=ESSAY)
        [record] = state["executionRecords"]
        self.assertEqual(record["result"], "partial")
        task = next(e for e in state["plan"]["entries"] if e["id"] == self.first["id"])
        self.assertFalse(task["completed"])
        self.assertEqual(len(state["checkInSessions"]), 2)

    def test_the_screen_confirms_the_card_it_shows_by_its_id(self):
        card = self.check_in(**{self.first["id"]: "completed"})["plannerThreads"]["essay"]["action"]
        self.call("/api/execution/chat/check-in/confirm", 409, project=ESSAY, actionId="another-card")
        state = self.call("/api/execution/chat/check-in/confirm", project=ESSAY, actionId=card["id"])
        self.assertEqual(len(state["executionRecords"]), 1)

    def test_a_record_used_as_proposal_evidence_cannot_be_told_again(self):
        self.check_in(**{self.first["id"]: "completed"})
        state = self.call("/api/execution/chat/check-in/confirm", project=ESSAY)
        record_id = state["executionRecords"][0]["id"]
        self.revision = self.store.change(self.revision, lambda d: d["profileUpdateProposals"].append(
            {"id": "p1", "evidenceRecordIds": [record_id], "status": "pending"}))["revision"]
        self.check_in(status=400, **{self.first["id"]: "partial"})

    def test_a_task_ticked_off_earlier_gets_how_the_session_went(self):
        plan_id = self.week["id"]
        self.call("/api/execution/task", planId=plan_id, taskId=self.first["id"], completed=True)
        self.llm.replies["planner_checkin"] = answer(session={
            "place": ("도서관", "도서관에서"), "atmosphere": ("quiet", "조용히"), "focus": ("good", "잘 됐어"), "condition": ("ok", "괜찮았어")})
        self.check_in(text="도서관에서 조용히 했어. 집중 잘 됐어, 컨디션 괜찮았어", **{self.first["id"]: "completed"})
        state = self.call("/api/execution/chat/check-in/confirm", project=ESSAY)
        [record] = state["executionRecords"]
        self.assertEqual((record["result"], record["place"], record["atmosphere"], record["focus"]), ("completed", "도서관", "quiet", "good"))

    def test_the_planner_asks_a_few_empty_fields_and_keeps_what_the_user_says(self):
        first = self.client.get("/api/execution/insights").json()
        self.assertEqual([q["key"] for q in first["next"]], ["tone", "place"])
        self.llm.replies["planner_checkin"] = answer(insights={
            "tone": ("casual", "반말이 편해"), "focus_aids": ("음악 들으면서", "음악 들으면서 하면 잘 돼"), "task_order": ("sideways", "반말이 편해")})
        state = self.check_in(text="반말이 편해. 음악 들으면서 하면 잘 돼", asked=["tone", "place"], **{self.first["id"]: "completed"})
        self.assertEqual(self.llm.chat_calls[-1]["context"]["asked"], ["tone", "place"])
        self.assertEqual(state["plannerThreads"]["essay"]["action"]["payload"]["insights"], {"tone": "casual", "focus_aids": "음악 들으면서"})
        self.assertEqual(state["userInsights"], {})  # nothing kept before confirming
        state = self.call("/api/execution/chat/check-in/confirm", project=ESSAY)
        self.assertEqual(state["userInsights"]["tone"]["value"], "casual")
        self.assertIn("새로 알게 된 것: 말투 편한 반말, 집중에 도움 되는 습관 음악 들으면서", state["plannerThreads"]["essay"]["messages"][-1]["content"])
        # Asked ones wait before they come back; known ones are not asked again.
        self.assertEqual([q["key"] for q in self.client.get("/api/execution/insights").json()["next"]], ["atmosphere", "distractions"])

    def test_what_was_learned_reaches_replies_and_plans(self):
        self.store.change(self.revision, lambda doc: doc.update(userInsights={
            "tone": {"value": "casual", "history": ["casual"], "updatedAt": "", "source": "check_in"},
            "task_order": {"value": "hard_first", "history": ["hard_first"], "updatedAt": "", "source": "check_in"}}))
        self.revision += 1
        self.call("/api/execution/chat/message", text="안녕", consent=True, project=ESSAY)
        route = next(c for c in self.llm.chat_calls if c["name"] == "planner_route")
        self.assertIn("편한 반말", route["instructions"])
        self.assertNotIn("부드러운 존댓말", route["instructions"])
        self.draft(ESSAY, "다음 주 초안")
        self.assertEqual(self.llm.plan_calls[-1]["context"]["userInsights"]["알게 된 것"], {"말투": "편한 반말", "일하는 순서": "어려운 것부터"})

    def test_plan_feedback_belongs_to_the_project_and_ends_with_it(self):
        state = self.call("/api/execution/projects/essay/feedback", load="too_much", note="리허설이 너무 많았어")
        self.assertEqual(state["projectFeedback"]["essay"][0]["load"], "too_much")
        self.draft(ESSAY, "다음 주 초안")
        feedback = self.llm.plan_calls[-1]["context"]["projectFeedback"]["essay"]
        self.assertEqual(feedback, [{"load": "too_much", "timeFit": None,
                                     "date": state["projectFeedback"]["essay"][0]["date"],
                                     "note": "리허설이 너무 많았어"}])
        state = self.call("/api/execution/projects/essay/close", project=ESSAY, outcome="completed")
        self.assertNotIn("essay", state["projectFeedback"])


if __name__ == "__main__":
    unittest.main()
