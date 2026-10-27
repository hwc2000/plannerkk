"""Ending a project carries what its records proved about the user to the user profile.

Values the user set for that project alone stay with it; its open work leaves
the week; it cannot be planned or talked to until it is opened again.
"""
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from server.app.execution_learning import propose_update
from server.app.execution_store import ExecutionStore
from server.app.main import create_app
from server.tests.test_adaptive_api import PLAIN_ANSWERS
from server.tests.test_project_independence import APP, ESSAY, FakeLLM

BASE_BLOCK = 30  # PLAIN_ANSWERS' focus block


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"})
class ProjectCloseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ExecutionStore(Path(self.temp.name) / "db.sqlite3")
        self.client = TestClient(create_app(execution_store=self.store, execution_llm=FakeLLM()))
        self.revision = self.client.get("/api/execution").json()["revision"]
        self.call("/api/execution/profile", answers=PLAIN_ANSWERS)
        self.call("/api/execution/profile/confirm")
        slots = [{"day": d, "hour": h} for d in range(7) for h in (18, 19, 20)]
        self.call("/api/execution/settings", method="put", settings={"slots": slots, "view": "timeline"})
        for project, goal in ((ESSAY, "에세이 초안"), (APP, "로그인 화면")):
            draft = self.call("/api/execution/plan", goal=goal, startDate="2030-01-07", consent=True,
                              project=project, merge=True)["planDraft"]
            self.call("/api/execution/plan/confirm", planId=draft["id"], project=draft["project"])

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

    def state(self):
        return self.client.get("/api/execution").json()

    def seed(self, fn):
        self.revision = self.store.change(self.revision, fn)["revision"]

    @staticmethod
    def records(doc, project_id, count, **fields):
        for i in range(count):
            doc["executionRecords"].append({
                "id": f"{project_id}-{len(doc['executionRecords'])}", "planId": doc["plan"]["id"], "taskId": f"t{i}",
                "profileId": doc["profile"]["id"], "profileVersion": doc["profile"]["version"], "projectId": project_id,
                "projectProfileId": None, "taskTitle": "작업", "plannedMinutes": BASE_BLOCK, "actualMinutes": None,
                "remainingMinutes": None, "result": "completed", "reasonCode": None, "note": "", "difficulty": None,
                "recoveryAction": None, "createdAt": datetime.now(timezone.utc).isoformat(), **fields})

    def learn_essay_block(self):
        """The essay learns a 20-minute block from its records, then finishes most tasks at that length."""
        def failures(doc):
            self.records(doc, "essay", 3, result="partial", actualMinutes=20, remainingMinutes=10, reasonCode="time_shortage")
            propose_update(doc, "essay")
        self.seed(failures)
        proposal = self.state()["profileUpdateProposals"][-1]
        self.call(f"/api/execution/proposals/{proposal['id']}/approve")
        version = self.state()["projectProfiles"]["essay"]["id"]
        self.seed(lambda doc: self.records(doc, "essay", 3, plannedMinutes=20, projectProfileId=version))
        return version

    def preview(self, project_id="essay"):
        response = self.client.get(f"/api/execution/projects/{project_id}/close-preview")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def close(self, project=ESSAY, outcome="completed"):
        return self.call(f"/api/execution/projects/{project['id']}/close", project=project, outcome=outcome)

    def test_ending_a_project_carries_what_its_records_proved(self):
        self.learn_essay_block()
        self.seed(lambda doc: self.records(doc, "essay", 3, recoveryAction="shrink"))
        before = self.state()

        preview = self.preview()
        self.assertEqual([(c["key"], c["from"], c["to"]) for c in preview["carried"]],
                         [("blockMinutes", "30분", "20분"), ("recoveryPreference", "잘 모르겠어요", "할 일을 줄임")])
        # Only tasks planned at the learned length count, not the failures that taught it.
        self.assertIn("20분 작업 3건 중 3건", preview["carried"][0]["because"])
        open_essay = [e for e in before["plan"]["entries"] if e["kind"] == "task" and e.get("projectId") == "essay"]
        self.assertEqual(preview["openTasks"], len(open_essay))

        state = self.close()

        prefs = state["profile"]["planningPreferences"]
        self.assertEqual((prefs["blockMinutes"], prefs["recoveryPreference"]), (20, "reduce"))
        self.assertEqual(state["profile"]["version"], before["profile"]["version"] + 1)
        carried = state["profileUpdateProposals"][-1]
        self.assertEqual((carried["ruleVersion"], carried["status"], carried["sourceProjectId"]),
                         ("project-close-v1", "approved", "essay"))
        self.assertEqual(state["profile"]["learnedPatterns"][-1]["approvedProposalId"], carried["id"])
        tasks = [e for e in state["plan"]["entries"] if e["kind"] == "task"]
        self.assertFalse([e for e in tasks if e.get("projectId") == "essay" and not e["completed"]])
        self.assertTrue([e for e in tasks if e.get("projectId") == "app"])
        self.assertEqual(state["closedProjects"]["essay"]["outcome"], "completed")
        # The app still follows the user profile's block, so its remaining tasks need planning again.
        self.assertNotEqual(state["plan"]["profileId"], state["profile"]["id"])

    def test_values_set_for_the_project_alone_stay_with_it(self):
        self.call("/api/execution/projects/essay/profile", method="put", overrides={"blockMinutes": 15, "dailyPlannedMinutes": 60})
        before = self.state()

        preview = self.preview()
        self.assertEqual(preview["carried"], [])
        self.assertEqual({k["label"] for k in preview["kept"]}, {"한 번에 집중할 시간", "하루 계획량"})
        self.assertTrue(all("이 프로젝트에만 정한 값" in k["why"] for k in preview["kept"]))

        state = self.close(outcome="abandoned")
        self.assertEqual(state["profile"]["id"], before["profile"]["id"])
        self.assertEqual(state["plan"]["profileId"], state["profile"]["id"])
        self.assertEqual(state["closedProjects"]["essay"]["outcome"], "abandoned")

    def test_too_little_evidence_stays_with_the_project(self):
        def few(doc):
            self.records(doc, "essay", 2, recoveryAction="reschedule")
        self.seed(few)
        preview = self.preview()
        self.assertEqual(preview["carried"], [])
        self.assertIn("2건", preview["kept"][0]["why"])

    def test_a_change_that_does_not_touch_the_rest_of_the_week_keeps_it_current(self):
        self.seed(lambda doc: self.records(doc, "essay", 3, recoveryAction="reschedule"))
        state = self.close()
        self.assertEqual(state["profile"]["planningPreferences"]["recoveryPreference"], "replan")
        self.assertEqual(state["plan"]["profileId"], state["profile"]["id"])

    def test_an_ended_project_is_not_planned_or_talked_to_until_reopened(self):
        self.close()
        detail = self.call("/api/execution/chat/message", 400, text="계속하자", consent=True, project=ESSAY)["detail"]
        self.assertIn("끝낸 프로젝트", detail)
        self.call("/api/execution/plan", 400, goal="퇴고", startDate="2030-01-07", consent=True, project=ESSAY, merge=True)
        self.call("/api/execution/projects/essay/close", 400, project=ESSAY, outcome="completed")

        self.call("/api/execution/projects/essay/reopen")
        self.call("/api/execution/chat/message", text="계속하자", consent=True, project=ESSAY)


if __name__ == "__main__":
    unittest.main()
