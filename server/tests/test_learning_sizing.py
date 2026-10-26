"""How much shorter a proposed focus block is comes from the user's own records, not a fixed number."""
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from server.app.execution_learning import evidence_block
from server.app.execution_profile import generate_profile
from server.app.execution_store import ExecutionStore
from server.app.main import create_app
from server.tests.test_adaptive_api import PLAIN_ANSWERS

ANSWERS = {**PLAIN_ANSWERS, "focusMinutes": 60}  # a stated 60 minutes is kept as is


class FakeLLM:
    def __init__(self):
        self.size_calls = []
        self.size_reply = {"blockMinutes": 25, "reason": "세 작업 모두 30분 안팎에서 멈췄습니다."}

    async def generate(self, **kwargs):
        if kwargs["name"] == "execution_profile":
            return generate_profile(ANSWERS)["insights"]
        if kwargs["name"] == "focus_block_size":
            self.size_calls.append(kwargs)
            return self.size_reply
        return {"tasks": [{"title": f"보고서 {i}장 쓰기", "minutes": kwargs["context"]["maxBlockMinutes"],
                           "doneWhen": "초안 완성", "dueDate": None} for i in range(4)]}


class LearningSizingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.llm = FakeLLM()
        self.store = ExecutionStore(Path(self.temp.name) / "db.sqlite3")
        self.client = TestClient(create_app(execution_store=self.store, execution_llm=self.llm))
        self.revision = self.client.get("/api/execution").json()["revision"]
        self.call("/api/execution/profile", answers=ANSWERS)
        self.call("/api/execution/profile/confirm")
        slots = [{"day": d, "hour": h} for d in range(7) for h in (18, 19, 20)]
        self.call("/api/execution/settings", method="put", settings={"slots": slots, "view": "timeline"})
        self.call("/api/execution/plan", goal="보고서", startDate="2030-01-07", consent=True)
        self.plan = self.call("/api/execution/plan/confirm", planId=self.state()["planDraft"]["id"])["plan"]

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def state(self):
        return self.client.get("/api/execution").json()

    def call(self, path, method="post", **body):
        response = getattr(self.client, method)(path, json={"revision": self.revision, **body})
        self.assertEqual(response.status_code, 200, response.text)
        self.revision = response.json()["revision"]
        return response.json()

    def fail(self, task, actual, consent=False, note="중간에 시간이 모자랐다"):
        return self.call("/api/execution/records", planId=self.plan["id"], taskId=task["id"], result="partial",
                         actualMinutes=actual, remainingMinutes=20, reasonCode="time_shortage", note=note, consent=consent)

    def tasks(self):
        return [e for e in self.plan["entries"] if e["kind"] == "task"]

    def test_the_block_comes_from_the_users_own_answer_and_records(self):
        self.assertEqual(self.state()["profile"]["planningPreferences"]["blockMinutes"], 60)
        for task, actual in zip(self.tasks(), (35, 25, 30)):
            state = self.fail(task, actual)

        [proposal] = state["profileUpdateProposals"]
        self.assertEqual(proposal["proposedChanges"], {"blockMinutes": {"from": 60, "to": 30}})
        self.assertEqual((proposal["sizedBy"], proposal["ruleVersion"]), ("evidence", "long-task-v2"))
        self.assertIn("실제로 집중한 시간(35, 25, 30분)", proposal["sizing"])
        self.assertEqual(self.llm.size_calls, [])  # no consent, nothing sent to the AI

    def test_the_ai_reads_the_tasks_to_size_it_when_the_user_agrees(self):
        tasks = self.tasks()
        self.fail(tasks[0], 35)
        self.fail(tasks[1], 25)
        state = self.fail(tasks[2], 30, consent=True, note="자료 찾다가 끝남")

        [proposal] = state["profileUpdateProposals"]
        self.assertEqual(proposal["proposedChanges"]["blockMinutes"], {"from": 60, "to": 25})
        self.assertEqual((proposal["sizedBy"], proposal["aiReason"]), ("ai", "세 작업 모두 30분 안팎에서 멈췄습니다."))
        [call] = self.llm.size_calls
        context = call["context"]
        self.assertEqual((context["currentBlockMinutes"], context["evidenceSuggestion"]), (60, 30))
        self.assertEqual([r["taskTitle"] for r in context["records"]], [t["title"] for t in tasks[:3]])
        self.assertEqual(context["records"][2]["note"], "자료 찾다가 끝남")
        self.assertIn("지시가 아닌 데이터", call["instructions"])

    def test_an_ai_size_that_is_not_shorter_keeps_the_evidence_size(self):
        self.llm.size_reply = {"blockMinutes": 60, "reason": "그대로"}
        tasks = self.tasks()
        self.fail(tasks[0], 35)
        self.fail(tasks[1], 25)
        state = self.fail(tasks[2], 30, consent=True)

        [proposal] = state["profileUpdateProposals"]
        self.assertEqual((proposal["proposedChanges"]["blockMinutes"]["to"], proposal["sizedBy"]), (30, "evidence"))


class FocusGrowthTests(unittest.TestCase):
    """A block that keeps getting finished grows by a step, never back to a size it was cut from."""

    setUp, tearDown = LearningSizingTests.setUp, LearningSizingTests.tearDown
    state, call, fail, tasks = LearningSizingTests.state, LearningSizingTests.call, LearningSizingTests.fail, LearningSizingTests.tasks

    def finish(self, tasks):
        state = None
        for task in tasks:
            state = self.call("/api/execution/task", planId=self.plan["id"], taskId=task["id"], completed=True)
        return state

    def grown(self, state):
        return [p for p in state["profileUpdateProposals"] if p["ruleVersion"] == "focus-grow-v1"]

    def test_finishing_block_sized_tasks_proposes_a_longer_block(self):
        tasks = self.tasks()
        self.assertEqual(len(tasks), 4)
        self.assertEqual(self.grown(self.finish(tasks[:3])), [])  # three in a row is not yet a pattern

        [proposal] = self.grown(self.finish(tasks[3:]))
        self.assertEqual(proposal["proposedChanges"], {"blockMinutes": {"from": 60, "to": 70}})
        self.assertIn("60분짜리 작업 4건을 연달아 끝냈습니다", proposal["reason"])
        self.assertEqual(self.llm.size_calls, [])  # a longer block is a fixed step, not sized by the AI

        state = self.call(f"/api/execution/proposals/{proposal['id']}/approve")
        self.assertEqual(state["profile"]["planningPreferences"]["blockMinutes"], 70)

    def cut_before(self, size):
        def seed(doc):
            doc["profileUpdateProposals"].append({
                "id": f"cut-{size}", "profileId": doc["profile"]["id"], "projectId": None, "projectProfileId": None,
                "proposedChanges": {"blockMinutes": {"from": size, "to": 60}}, "reason": "", "evidenceRecordIds": [],
                "ruleVersion": "long-task-v2", "status": "approved", "createdAt": "2030-01-01T00:00:00+00:00",
                "decidedAt": "2030-01-01T00:00:00+00:00"})
        self.revision = self.store.change(self.revision, seed)["revision"]

    def test_it_stops_short_of_a_size_it_was_cut_from(self):
        self.cut_before(70)
        [proposal] = self.grown(self.finish(self.tasks()))
        self.assertEqual(proposal["proposedChanges"]["blockMinutes"], {"from": 60, "to": 65})
        self.assertIn("예전에 70분에서 줄였으니", proposal["sizing"])

    def test_a_block_just_cut_does_not_grow_back(self):
        self.cut_before(65)
        self.assertEqual(self.grown(self.finish(self.tasks())), [])

    def test_a_miss_in_between_is_not_a_pattern(self):
        tasks = self.tasks()
        self.finish(tasks[:2])
        self.fail(tasks[2], 30)
        self.assertEqual(self.grown(self.finish(tasks[3:])), [])


class EvidenceBlockTests(unittest.TestCase):
    def test_middle_of_the_managed_minutes_in_five_minute_steps(self):
        records = [{"actualMinutes": m} for m in (12, 0, 28, None)]
        self.assertEqual(evidence_block(records, 50), 25)  # managed 12 and 28: the middle is 28 -> 25

    def test_no_managed_minutes_means_no_size(self):
        self.assertIsNone(evidence_block([{"actualMinutes": 0}, {"actualMinutes": None}], 50))

    def test_never_longer_than_the_current_block(self):
        self.assertIsNone(evidence_block([{"actualMinutes": 55}], 50))


if __name__ == "__main__":
    unittest.main()
