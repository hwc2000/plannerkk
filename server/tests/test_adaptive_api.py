import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from server.app.adaptive.llm_generator import STYLE_INSTRUCTIONS
from server.app.execution_llm import LLMUnavailableError
from server.app.execution_profile import generate_profile
from server.app.execution_store import ExecutionStore
from server.app.main import create_app
from server.tests.test_execution import ANSWERS

SHRINK = {
    "tasks": [
        {"title": "문제 1~2번만 풀기", "minutes": 8, "doneWhen": "두 문제 풀이 기록"},
        {"title": "오답 이유 한 줄 쓰기", "minutes": 10, "doneWhen": "오답 이유 기록"},
    ],
    "appliedReasons": ["작업이 너무 컸다는 체크인을 반영함"],
}


class FakeLLM:
    """Plays the profile and weekly-plan calls; shrink answers come from a queue."""

    def __init__(self):
        self.plan_minutes = 20
        self.plan_due = None
        self.shrink_replies = []
        self.shrink_calls = []

    async def generate(self, **kwargs):
        if kwargs["name"] == "execution_profile":
            return generate_profile(ANSWERS)["insights"]
        if kwargs["name"] == "execution_tasks":
            return {"tasks": [{"title": f"연습문제 {i} 풀기", "minutes": self.plan_minutes, "doneWhen": "풀이 기록", "dueDate": self.plan_due} for i in range(4)]}
        self.shrink_calls.append(kwargs)
        reply = self.shrink_replies.pop(0) if self.shrink_replies else SHRINK
        if isinstance(reply, Exception):
            raise reply
        return reply


class AdaptiveApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.llm = FakeLLM()
        self.client = TestClient(create_app(
            execution_store=ExecutionStore(Path(self.temp.name) / "db.sqlite3"), execution_llm=self.llm,
        ))
        self.revision = self.client.get("/api/execution").json()["revision"]

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def call(self, path, status=200, **body):
        response = self.client.post(path, json={"revision": self.revision, **body})
        self.assertEqual(response.status_code, status, response.text)
        data = response.json()
        if status == 200:
            self.revision = data["revision"]
        return data

    def setup_plan(self, answers=ANSWERS):
        return next(e for e in self.setup_plan_entries(answers) if e["kind"] == "task")

    def setup_plan_entries(self, answers=ANSWERS):
        self.call("/api/execution/profile", answers=answers)
        self.call("/api/execution/profile/confirm")
        settings = {"slots": [{"day": 0, "hour": 18}, {"day": 0, "hour": 19}], "view": "timeline"}
        response = self.client.put("/api/execution/settings", json={"revision": self.revision, "settings": settings})
        self.revision = response.json()["revision"]
        self.call("/api/execution/plan", goal="연습문제 공부", startDate="2030-01-07", consent=True)
        return self.call("/api/execution/plan/confirm", planId=self.state()["planDraft"]["id"])["plan"]["entries"]

    def state(self):
        return self.client.get("/api/execution").json()

    def check_in(self, task, status=200, **fields):
        check_in = {"completed": False, "actualMinutes": 10, "reasonCode": "task_too_large", "note": "한 번에 너무 많았다"}
        check_in.update(fields)
        return self.call("/api/adaptive/check-in", status, taskId=task["id"], checkIn=check_in, consent=True)

    def records(self):
        return self.state()["executionRecords"]

    def test_failed_check_in_stores_record_and_waiting_draft(self):
        task = self.setup_plan()

        data = self.check_in(task)

        self.assertEqual(data["result"]["approvalStatus"], "waiting")
        self.assertEqual(data["recoveryDraft"]["draft"]["replacesTaskId"], task["id"])
        self.assertEqual(data["recoveryDraft"]["recordId"], data["recordId"])
        self.assertEqual(self.state()["recoveryDrafts"], {task["id"]: data["recoveryDraft"]})
        [record] = self.records()
        self.assertEqual(
            {k: record[k] for k in ("taskId", "taskTitle", "plannedMinutes", "actualMinutes", "result", "reasonCode", "recoveryAction")},
            {"taskId": task["id"], "taskTitle": task["title"], "plannedMinutes": 20, "actualMinutes": 10,
             "result": "incomplete", "reasonCode": "task_too_large", "recoveryAction": None},
        )
        context = self.llm.shrink_calls[0]["context"]
        self.assertEqual(context["originalTask"], {"title": task["title"], "minutes": 20, "doneWhen": task["doneWhen"]})
        self.assertEqual(context["scheduleStyle"], "flexible_queue")
        self.assertEqual((context["minTaskMinutes"], context["maxTaskMinutes"], context["maxTotalMinutes"]), (5, 19, 19))
        self.assertEqual(context["goal"], "연습문제 공부")
        self.assertIn(STYLE_INSTRUCTIONS["flexible_queue"], self.llm.shrink_calls[0]["instructions"])

    def test_completed_check_in_marks_task_done_without_llm(self):
        task = self.setup_plan()

        response = self.client.post("/api/adaptive/check-in", json={
            "revision": self.revision, "taskId": task["id"], "checkIn": {"completed": True, "actualMinutes": 25},
        })

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["result"]["route"], "continue")
        entry = next(e for e in self.state()["plan"]["entries"] if e["id"] == task["id"])
        self.assertTrue(entry["completed"])
        [record] = self.records()
        self.assertEqual((record["result"], record["actualMinutes"], record["plannedMinutes"]), ("completed", 25, 20))
        self.assertEqual(self.llm.shrink_calls, [])

    def test_approve_replaces_task_and_records_action(self):
        task = self.setup_plan()
        draft = self.check_in(task)["recoveryDraft"]

        data = self.call("/api/adaptive/review", draftId=draft["id"], decision="approve")

        self.assertEqual(data["result"]["approvalStatus"], "approved")
        self.assertIsNone(data["recoveryDraft"])
        state = self.state()
        self.assertEqual(state["revision"], self.revision)
        self.assertEqual(state["recoveryDrafts"], {})
        self.assertEqual(state["executionRecords"][0]["recoveryAction"], "shrink")
        entries = state["plan"]["entries"]
        self.assertFalse(any(e["id"] == task["id"] for e in entries))
        pieces = [e for e in entries if e["title"] in {"문제 1~2번만 풀기", "오답 이유 한 줄 쓰기"}]
        # Saved exactly where the user saw them: the earliest free time (see the plan note below).
        self.assertEqual([(p["start"], p["end"]) for p in pieces],
                         [(t["start"], t["end"]) for t in draft["draft"]["tasks"]])
        self.assertEqual([(p["start"], p["end"]) for p in pieces],
                         [("2030-01-07T19:15", "2030-01-07T19:23"), ("2030-01-07T19:23", "2030-01-07T19:33")])
        self.assertEqual({p["recoveryDepth"] for p in pieces}, {1})

    def test_shrink_checked_in_after_its_slot_is_never_placed_in_the_past(self):
        task = self.setup_plan()  # 18:00~18:20
        with mock.patch("server.app.adaptive.api.local_now", return_value=datetime(2030, 1, 7, 19, 20)):
            draft = self.check_in(task)["recoveryDraft"]
            self.assertEqual([t["start"] for t in draft["draft"]["tasks"]], ["2030-01-07T19:21", "2030-01-07T19:29"])
            self.call("/api/adaptive/review", draftId=draft["id"], decision="approve")
        starts = [e["start"] for e in self.state()["plan"]["entries"] if e.get("recoveryDepth")]
        self.assertEqual(starts, ["2030-01-07T19:21", "2030-01-07T19:29"])

    def test_shrink_approved_after_its_time_passed_is_not_saved(self):
        task = self.setup_plan()
        draft_id = self.check_in(task)["recoveryDraft"]["id"]  # pieces from 19:15
        before = self.state()["plan"]

        with mock.patch("server.app.adaptive.api.local_now", return_value=datetime(2030, 1, 7, 19, 20)):
            data = self.call("/api/adaptive/review", draftId=draft_id, decision="approve")

        self.assertEqual(data["result"]["fallback"]["source"], "approval_validation")
        self.assertEqual(self.state()["plan"], before)

    def test_shrink_is_bounded_by_the_work_left(self):
        task = self.setup_plan()  # 20 minutes; SHRINK adds up to 18

        data = self.check_in(task, remainingMinutes=12)

        self.assertEqual(self.llm.shrink_calls[0]["context"]["maxTotalMinutes"], 11)
        self.assertEqual(data["result"]["fallback"]["source"], "validation_policy")
        self.assertIsNone(data["recoveryDraft"])

    def test_too_little_work_left_offers_other_strategies(self):
        task = self.setup_plan()

        data = self.check_in(task, remainingMinutes=5)

        self.assertEqual(data["result"]["fallback"]["source"], "shrink_not_possible")
        self.assertEqual(self.llm.shrink_calls, [])

    def test_approve_cannot_switch_strategy(self):
        task = self.setup_plan()
        draft_id = self.check_in(task)["recoveryDraft"]["id"]
        before = self.state()["plan"]

        self.call("/api/adaptive/review", 400, draftId=draft_id, decision="approve", strategy="reschedule")

        self.assertEqual(self.state()["plan"], before)
        self.assertIsNone(self.records()[0]["recoveryAction"])

    def test_new_plan_closes_waiting_drafts(self):
        task = self.setup_plan()
        self.check_in(task)

        self.call("/api/execution/plan", goal="다음 주 공부", startDate="2030-01-14", consent=True)
        self.call("/api/execution/plan/confirm", planId=self.state()["planDraft"]["id"])

        self.assertEqual(self.state()["recoveryDrafts"], {})
        self.assertEqual(self.records()[0]["recoveryAction"], "plan_replaced")

    def test_shrunk_piece_is_not_shrunk_again(self):
        task = self.setup_plan()
        self.call("/api/adaptive/review", draftId=self.check_in(task)["recoveryDraft"]["id"], decision="approve")
        piece = next(e for e in self.state()["plan"]["entries"] if e.get("recoveryDepth") == 1)

        data = self.check_in(piece)

        self.assertEqual(data["result"]["fallback"]["source"], "shrink_not_possible")
        self.assertEqual(data["result"]["fallback"]["options"], ["reschedule", "replan"])
        self.assertEqual(len(self.llm.shrink_calls), 1)
        self.assertEqual(len(self.records()), 2)  # the repeat failure is still recorded

    def test_reject_clears_draft_records_choice_and_keeps_plan(self):
        task = self.setup_plan()
        before = self.state()["plan"]
        draft_id = self.check_in(task)["recoveryDraft"]["id"]

        data = self.call("/api/adaptive/review", draftId=draft_id, decision="reject")

        self.assertEqual(data["result"]["approvalStatus"], "rejected")
        self.assertEqual(self.state()["recoveryDrafts"], {})
        self.assertEqual(self.records()[0]["recoveryAction"], "keep_current_plan")
        self.assertEqual(self.state()["plan"], before)

    def test_drafts_are_kept_per_task_and_superseded_consistently(self):
        task, other = [e for e in self.setup_plan_entries() if e["kind"] == "task"][:2]
        first = self.check_in(task)["recoveryDraft"]
        self.check_in(other)
        self.assertEqual(set(self.state()["recoveryDrafts"]), {task["id"], other["id"]})

        # A new check-in on the same task that ends without a draft removes the stale one.
        data = self.check_in(task, reasonCode="other")

        self.assertEqual(data["result"]["fallback"]["missingFields"], ["strategy"])
        self.assertIsNone(data["recoveryDraft"])
        self.assertEqual(set(self.state()["recoveryDrafts"]), {other["id"]})
        self.call("/api/adaptive/review", 400, draftId=first["id"], decision="approve")
        # ...and it updated the same open record instead of counting the failure twice.
        self.assertEqual([r["reasonCode"] for r in self.records()], ["other", "task_too_large"])

    def test_profile_change_blocks_recovery_but_not_completion(self):
        task, other = [e for e in self.setup_plan_entries() if e["kind"] == "task"][:2]
        draft_id = self.check_in(task)["recoveryDraft"]["id"]
        self.call("/api/execution/profile", answers={**ANSWERS, "focusMinutes": 50})
        self.call("/api/execution/profile/confirm")

        self.check_in(other, 400)
        self.call("/api/adaptive/review", 400, draftId=draft_id, decision="approve")
        self.call("/api/adaptive/review", draftId=draft_id, decision="reject")
        self.call("/api/adaptive/check-in", taskId=other["id"], checkIn={"completed": True})

    # Plan used below (Monday 18~20시, 40% buffer): three 20-minute tasks with breaks
    # until 19:15, the fourth does not fit; 19:15~20:00 is free.

    def test_reschedule_moves_work_into_free_time_and_records_action(self):
        task = self.setup_plan()

        data = self.check_in(task, reasonCode="time_shortage")

        draft = data["recoveryDraft"]["draft"]
        self.assertEqual(draft["kind"], "reschedule")
        self.assertEqual([(t["start"], t["end"]) for t in draft["tasks"]], [("2030-01-07T19:15", "2030-01-07T19:35")])
        self.assertEqual(self.llm.shrink_calls, [])
        self.call("/api/adaptive/review", draftId=data["recoveryDraft"]["id"], decision="approve")
        entries = self.state()["plan"]["entries"]
        self.assertFalse(any(e["id"] == task["id"] for e in entries))
        self.assertEqual([e["start"] for e in entries], sorted(e["start"] for e in entries))
        moved = next(e for e in entries if e["start"] == "2030-01-07T19:15")
        self.assertEqual((moved["title"], moved["recoveryDepth"]), (task["title"], 0))
        self.assertEqual(self.records()[0]["recoveryAction"], "reschedule")

    def test_reschedule_avoids_calendar_events_and_carries_the_rest_over(self):
        task = self.setup_plan()
        event = {"date": "2030-01-07", "startTime": "19:15", "endTime": "19:45"}

        data = self.call("/api/adaptive/check-in", taskId=task["id"], consent=True, events=[event], checkIn={
            "completed": False, "reasonCode": "interruption", "remainingMinutes": 20,
        })

        draft = data["recoveryDraft"]["draft"]
        self.assertEqual([(t["start"], t["minutes"]) for t in draft["tasks"]], [("2030-01-07T19:45", 15)])
        self.assertEqual(draft["carryOverMinutes"], 5)
        self.call("/api/adaptive/review", draftId=data["recoveryDraft"]["id"], decision="approve", events=[event])
        pending = self.state()["plan"]["pendingTasks"]
        self.assertEqual((pending[-1]["title"], pending[-1]["minutes"]), (task["title"], 5))

    def test_waiting_drafts_do_not_offer_the_same_free_time(self):
        first, second = [e for e in self.setup_plan_entries() if e["kind"] == "task"][:2]

        a = self.check_in(first, reasonCode="time_shortage")["recoveryDraft"]["draft"]["tasks"]
        b = self.check_in(second, reasonCode="time_shortage")["recoveryDraft"]["draft"]["tasks"]

        self.assertEqual(a[0]["start"], "2030-01-07T19:15")
        self.assertEqual(b[0]["start"], "2030-01-07T19:35")

    def test_deadline_too_close_asks_ai_to_fit_and_code_places_it(self):
        self.llm.plan_due = "2030-01-07"
        task = self.setup_plan()
        self.llm.shrink_replies = [{
            "tasks": [{"title": "핵심 문제만", "minutes": 30, "doneWhen": "핵심 문제 풀이"},
                      {"title": "오답 정리", "minutes": 10, "doneWhen": "오답 한 줄"}],
            "appliedReasons": ["마감 전 45분에 맞춰 핵심만 남김"],
            "droppedScope": ["나머지 연습문제"],
        }]

        data = self.check_in(task, reasonCode="underestimated", remainingMinutes=60)

        call = self.llm.shrink_calls[0]
        self.assertEqual(call["name"], "fit_deadline_recovery")
        self.assertEqual((call["context"]["mode"], call["context"]["deadline"], call["context"]["maxTotalMinutes"]),
                         ("fit_deadline", "2030-01-07", 45))
        draft = data["recoveryDraft"]["draft"]
        self.assertEqual(draft["kind"], "fit_deadline")
        self.assertEqual([(t["start"], t["end"]) for t in draft["tasks"]],
                         [("2030-01-07T19:15", "2030-01-07T19:45"), ("2030-01-07T19:45", "2030-01-07T19:55")])
        self.assertEqual(draft["droppedScope"], ["나머지 연습문제"])

    def test_revise_sends_feedback_and_previous_draft(self):
        task = self.setup_plan()
        draft_id = self.check_in(task)["recoveryDraft"]["id"]
        revised = {**SHRINK, "tasks": [{**SHRINK["tasks"][0], "minutes": 5}, SHRINK["tasks"][1]],
                   "appliedReasons": ["피드백대로 첫 작업을 더 줄임"]}
        self.llm.shrink_replies = [revised]

        data = self.call("/api/adaptive/review", draftId=draft_id, decision="revise", feedback="첫 작업을 더 작게", consent=True)

        context = self.llm.shrink_calls[-1]["context"]
        self.assertEqual(context["userFeedback"], "첫 작업을 더 작게")
        self.assertEqual(context["previousDraft"]["tasks"], SHRINK["tasks"])
        self.assertEqual(data["recoveryDraft"]["revisionCount"], 1)
        self.assertEqual(data["recoveryDraft"]["draft"]["appliedReasons"], ["피드백대로 첫 작업을 더 줄임"])

    def test_invalid_reply_is_retried_with_errors(self):
        task = self.setup_plan()
        too_long = {**SHRINK, "tasks": [{"title": "그대로", "minutes": 20, "doneWhen": "완료"}]}
        self.llm.shrink_replies = [too_long, SHRINK]

        data = self.check_in(task)

        self.assertEqual(data["result"]["approvalStatus"], "waiting")
        self.assertEqual(data["result"]["retryCount"], 1)
        self.assertTrue(self.llm.shrink_calls[1]["context"]["validationErrors"])

    def test_unavailable_llm_is_not_retried(self):
        task = self.setup_plan()
        self.llm.shrink_replies = [LLMUnavailableError("키 없음")]

        data = self.check_in(task)

        self.assertEqual(len(self.llm.shrink_calls), 1)
        self.assertEqual(data["result"]["fallback"]["source"], "generation_unavailable")
        self.assertIsNone(data["recoveryDraft"])

    def test_unknown_focus_is_asked_not_defaulted(self):
        self.llm.plan_minutes = 15  # the profile's default block when focus is unknown
        task = self.setup_plan({**ANSWERS, "regularity": "regular", "focusMinutes": None})

        data = self.check_in(task)

        self.assertEqual(data["result"]["approvalStatus"], "needs_input")
        self.assertEqual(data["result"]["fallback"]["missingFields"], ["execution_context.focus_minutes"])
        self.assertEqual(self.llm.shrink_calls, [])

    def test_guards(self):
        task = self.setup_plan()
        self.check_in(task)
        self.call("/api/adaptive/check-in", 400, taskId=task["id"], checkIn={"completed": False}, consent=False)
        self.call("/api/adaptive/review", 400, draftId="other", decision="approve")
        response = self.client.post("/api/adaptive/review", json={"revision": 0, "draftId": "x", "decision": "approve"})
        self.assertEqual(response.status_code, 409)
        self.call("/api/execution/task", planId=self.state()["plan"]["id"], taskId=task["id"], completed=True)
        self.check_in(task, 400)


if __name__ == "__main__":
    unittest.main()
