"""When the user focuses best is learned from their records, not asked up front.

Onboarding no longer asks for it.  Once tasks planned in two parts of the day
show a clear difference in how many were finished, a change is proposed; the
AI reads the tasks too when the user agreed, and nothing changes until approval.
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from uuid import uuid4

from fastapi.testclient import TestClient

from server.app.execution_store import ExecutionStore
from server.app.main import create_app
from server.app.user_profile import upgrade_profile
from server.tests.test_adaptive_api import PLAIN_ANSWERS
from server.tests.test_project_independence import ESSAY, FakeLLM

ANSWERS = {**PLAIN_ANSWERS, "energy": "unknown"}  # what onboarding stores now
MORNINGS = [f"2030-01-{d:02}T09:00" for d in (7, 8, 9, 10)]
EVENINGS = [f"2030-01-{d:02}T19:00" for d in (7, 8, 9, 10)]


class FocusLLM(FakeLLM):
    def __init__(self):
        super().__init__()
        self.focus_calls = []
        self.focus_reply = {"focusTime": "evening", "reason": "저녁에 계획한 작업은 모두 끝냈고 오전 작업 메모에는 피곤함이 남아 있습니다."}

    async def generate(self, **kwargs):
        if kwargs["name"] == "focus_time":
            self.focus_calls.append(kwargs)
            return self.focus_reply
        return await super().generate(**kwargs)


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"})
class FocusTimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.llm = FocusLLM()
        self.store = ExecutionStore(Path(self.temp.name) / "db.sqlite3")
        self.client = TestClient(create_app(execution_store=self.store, execution_llm=self.llm))
        self.revision = self.client.get("/api/execution").json()["revision"]
        self.call("/api/execution/profile", answers=ANSWERS)
        self.call("/api/execution/profile/confirm")

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def call(self, path, status=200, method="post", **body):
        response = getattr(self.client, method)(path, json={"revision": self.revision, **body})
        self.assertEqual(response.status_code, status, response.text)
        data = response.json()
        if status == 200:
            self.revision = data["revision"]
        return data

    def put_plan(self, starts):
        """A confirmed week with one 30-minute task at each start, made with the current profile."""
        profile = self.store.read()["profile"]
        entries = [{"id": str(uuid4()), "kind": "task", "title": f"공부 {i + 1}", "minutes": 30, "doneWhen": "한 단원",
                    "dueDate": None, "start": start, "completed": False,
                    "end": (datetime.fromisoformat(start) + timedelta(minutes=30)).isoformat(timespec="minutes")}
                   for i, start in enumerate(starts)]
        plan = {"id": str(uuid4()), "profileId": profile["id"], "profileVersion": profile["version"], "projectId": None,
                "project": None, "goal": "공부", "startDate": "2030-01-07", "endDate": "2030-01-13", "timezone": "Asia/Seoul",
                "status": "confirmed", "slots": [], "entries": entries, "pendingTasks": []}
        self.revision = self.store.change(self.revision, lambda state: state.update(plan=plan))["revision"]
        return plan["id"], entries

    def finish(self, plan_id, task):
        return self.call("/api/execution/task", planId=plan_id, taskId=task["id"], completed=True)

    def miss(self, plan_id, task, consent=False, reason="fatigue"):
        return self.call("/api/execution/records", planId=plan_id, taskId=task["id"], result="partial", actualMinutes=10,
                         remainingMinutes=20, reasonCode=reason, note="피곤해서 멈춤", consent=consent)

    def evenings_done_mornings_missed(self, consent=False):
        plan_id, entries = self.put_plan(MORNINGS + EVENINGS)
        for task in entries[4:]:
            self.finish(plan_id, task)
        for task in entries[:3]:
            self.miss(plan_id, task)
        return self.miss(plan_id, entries[3], consent=consent)

    def focus_proposals(self, state):
        return [p for p in state["profileUpdateProposals"] if "focusTime" in p["proposedChanges"]]

    def test_onboarding_leaves_it_unknown(self):
        self.assertEqual(self.client.get("/api/execution").json()["profile"]["planningPreferences"]["focusTime"], "unknown")

    def test_a_clear_difference_between_parts_of_the_day_is_proposed(self):
        state = self.evenings_done_mornings_missed()

        [proposal] = self.focus_proposals(state)
        self.assertEqual(proposal["proposedChanges"], {"focusTime": {"from": "unknown", "to": "evening"}})
        self.assertEqual((proposal["ruleVersion"], proposal["sizedBy"], proposal["projectId"]), ("focus-time-v1", "evidence", None))
        self.assertEqual(proposal["focusStats"], {"morning": {"planned": 4, "finished": 0}, "evening": {"planned": 4, "finished": 4}})
        self.assertEqual(proposal["reason"], "최근 기록에서 오전에 계획한 작업 4건 중 0건, 저녁에 계획한 작업 4건 중 4건을 끝냈습니다.")
        self.assertEqual(len(proposal["evidenceRecordIds"]), 8)
        self.assertEqual(self.llm.focus_calls, [])  # no consent, nothing sent to the AI
        self.assertEqual(state["executionRecords"][0]["plannedStart"], EVENINGS[0])

    def test_one_part_of_the_day_alone_proves_nothing(self):
        plan_id, entries = self.put_plan(EVENINGS + [f"2030-01-1{d}T20:00" for d in (1, 2, 3)] + ["2030-01-07T20:00"])
        for task in entries:
            state = self.finish(plan_id, task)
        self.assertEqual(self.focus_proposals(state), [])

    def test_the_ai_reads_the_tasks_when_the_user_agrees(self):
        state = self.evenings_done_mornings_missed(consent=True)

        [proposal] = self.focus_proposals(state)
        self.assertEqual((proposal["sizedBy"], proposal["aiReason"]), ("ai", self.llm.focus_reply["reason"]))
        [call] = self.llm.focus_calls
        self.assertEqual(call["context"]["comparable"], ["evening", "morning"])
        self.assertEqual({r["period"] for r in call["context"]["records"]}, {"morning", "evening"})
        self.assertIn("지시가 아닌 데이터", call["instructions"])

    def test_an_ai_answer_outside_the_evidence_keeps_the_evidence(self):
        self.llm.focus_reply = {"focusTime": "afternoon", "reason": "오후가 좋아 보입니다."}
        [proposal] = self.focus_proposals(self.evenings_done_mornings_missed(consent=True))
        self.assertEqual((proposal["proposedChanges"]["focusTime"]["to"], proposal["sizedBy"]), ("evening", "evidence"))

    def test_approving_places_work_in_that_part_of_the_day_and_says_why(self):
        [proposal] = self.focus_proposals(self.evenings_done_mornings_missed())
        state = self.call(f"/api/execution/proposals/{proposal['id']}/approve")
        self.assertEqual(state["profile"]["planningPreferences"]["focusTime"], "evening")

        slots = [{"day": d, "hour": h} for d in range(7) for h in (9, 10, 19, 20)]
        self.call("/api/execution/settings", method="put", settings={"slots": slots, "view": "timeline"})
        draft = self.call("/api/execution/plan", goal="에세이", startDate="2030-01-07", consent=True, project=ESSAY)["planDraft"]

        tasks = [e for e in draft["entries"] if e["kind"] == "task"]
        self.assertTrue(tasks and all(e["start"][11:13] in ("19", "20") for e in tasks))
        period = next(r for r in draft["personalization"] if r["key"] == "period")
        self.assertEqual(period["source"], "learned")
        self.assertIn("실행 기록 8건", period["because"])

    def test_a_rejected_proposal_needs_new_evidence(self):
        [proposal] = self.focus_proposals(self.evenings_done_mornings_missed())
        self.call(f"/api/execution/proposals/{proposal['id']}/reject")
        plan_id, entries = self.put_plan(["2030-01-11T19:00"])
        state = self.finish(plan_id, entries[0])
        self.assertEqual([p["status"] for p in self.focus_proposals(state)], ["rejected"])

    def test_learned_values_about_different_things_both_stay(self):
        # First a shorter focus block, learned from three tasks that ran out of time.
        plan_id, entries = self.put_plan(MORNINGS[:3])
        for task in entries:
            state = self.miss(plan_id, task, reason="time_shortage")
        [block] = [p for p in state["profileUpdateProposals"] if "blockMinutes" in p["proposedChanges"]]
        self.call(f"/api/execution/proposals/{block['id']}/approve")

        [focus] = self.focus_proposals(self.evenings_done_mornings_missed())
        state = self.call(f"/api/execution/proposals/{focus['id']}/approve")

        active = [p["proposedChanges"] for p in state["profile"]["learnedPatterns"] if p["status"] == "active"]
        self.assertEqual([set(c) for c in active], [{"blockMinutes"}, {"focusTime"}])

    def test_profiles_from_before_keep_their_answer_as_the_focus_time(self):
        profile = self.store.read()["profile"]
        profile["declaredFacts"]["energy"] = profile["facts"]["energy"] = "morning"
        del profile["planningPreferences"]["focusTime"]
        self.assertEqual(upgrade_profile(profile, "local")["planningPreferences"]["focusTime"], "morning")


if __name__ == "__main__":
    unittest.main()
