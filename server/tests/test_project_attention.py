"""The home screen asks about projects past their deadline or left without check-ins.

Tasks nobody checked in are unknown, not failures: the learning rules never count them.
Results recorded afterwards keep the plan honest but never teach the profile.
"""
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from server.app.execution_api import project_history
from server.app.execution_learning import propose_update
from server.app.execution_store import ExecutionStore
from server.app.main import create_app
from server.app.planner import ProjectContext
from server.app.project_attention import IDLE_MISSES, KST
from server.tests.test_adaptive_api import PLAIN_ANSWERS
from server.tests import test_project_close as close_tests
from server.tests.test_project_independence import APP, ESSAY, FakeLLM

NOW = "server.app.project_attention.now_kst"


def at(day, hour=9):
    return datetime(2030, 1, day, hour, 0, tzinfo=KST)


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"})
class ProjectAttentionTests(unittest.TestCase):
    call = close_tests.ProjectCloseTests.call
    state = close_tests.ProjectCloseTests.state
    seed = close_tests.ProjectCloseTests.seed

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ExecutionStore(Path(self.temp.name) / "db.sqlite3")
        self.client = TestClient(create_app(execution_store=self.store, execution_llm=FakeLLM()))
        self.revision = self.client.get("/api/execution").json()["revision"]
        self.call("/api/execution/profile", answers=PLAIN_ANSWERS)
        self.call("/api/execution/profile/confirm")
        slots = [{"day": d, "hour": h} for d in range(7) for h in (18, 19, 20)]
        self.call("/api/execution/settings", method="put", settings={"slots": slots, "view": "timeline"})
        draft = self.call("/api/execution/plan", goal="에세이 초안", startDate="2030-01-07", consent=True,
                          project=ESSAY, merge=True)["planDraft"]
        self.call("/api/execution/plan/confirm", planId=draft["id"], project=draft["project"])

        def tasks(doc):
            # One essay task a day, Monday to Thursday, at the block the profile plans (30 minutes).
            doc["plan"]["entries"] = [
                {"id": f"t{day}", "kind": "task", "title": f"에세이 {day}", "minutes": 30, "doneWhen": "완료",
                 "dueDate": "2030-01-31", "projectId": "essay", "projectProfileId": None, "completed": False,
                 "start": f"2030-01-{day:02}T18:00", "end": f"2030-01-{day:02}T18:30"} for day in (7, 8, 9, 10)]
        self.seed(tasks)

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def attention(self, *projects):
        response = self.client.post("/api/execution/attention", json={"projects": list(projects or (ESSAY,))})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["items"]

    def check_in(self, task_id, result="completed"):
        body = {"planId": self.state()["plan"]["id"], "taskId": task_id, "result": result}
        if result == "not_started":
            body["actualMinutes"] = 0
        self.call("/api/execution/records", **body)

    def late(self, *items, status=200):
        return self.call("/api/execution/records/late", status=status, planId=self.state()["plan"]["id"],
                         items=[{"taskId": t, "result": r} for t, r in items])

    # --- when the home screen asks ---

    def test_three_planned_tasks_in_a_row_without_a_word_ask_about_the_project(self):
        with mock.patch(NOW, return_value=at(10)):  # Mon, Tue, Wed passed; Thursday's task is today
            [item] = self.attention()
        self.assertEqual((item["projectId"], item["kind"], item["silentInRow"]), ("essay", "idle", IDLE_MISSES))
        self.assertEqual([t["taskId"] for t in item["tasks"]], ["t7", "t8", "t9"])

    def test_todays_tasks_wait_for_the_evening_check_in(self):
        with mock.patch(NOW, return_value=at(9, 21)):  # two past days, the third task is today's
            self.assertEqual(self.attention(), [])

    def test_a_recent_check_in_means_the_project_is_alive(self):
        self.check_in("t9", "partial")
        with mock.patch(NOW, return_value=at(11)):
            self.assertEqual(self.attention(), [], "only the silent tasks after the last check-in count")

    def test_a_task_checked_off_counts_as_a_word(self):
        self.call("/api/execution/task", planId=self.state()["plan"]["id"], taskId="t10", completed=True)
        with mock.patch(NOW, return_value=at(11)):
            self.assertEqual(self.attention(), [])

    def test_a_project_past_its_deadline_is_asked_about_even_without_tasks(self):
        ended = {**APP, "dueDate": "2030-01-08"}
        with mock.patch(NOW, return_value=at(9)):
            [item] = self.attention(ended)
        self.assertEqual((item["projectId"], item["kind"], item["tasks"]), ("app", "overdue", []))

    def test_a_paused_or_ended_project_is_not_asked_about(self):
        with mock.patch(NOW, return_value=at(12)):
            self.assertEqual(self.attention(APP), [], "the client leaves paused projects out of the request")
        self.call("/api/execution/projects/essay/close", project=ESSAY, outcome="abandoned")
        with mock.patch(NOW, return_value=at(12)):
            self.assertEqual(self.attention(), [])

    # --- results recorded afterwards ---

    def test_late_results_are_kept_without_minutes(self):
        with mock.patch(NOW, return_value=at(12)):
            doc = self.late(("t7", "completed"), ("t8", "partial"), ("t9", "not_started"), ("t10", "incomplete"))
        records = {r["taskId"]: r for r in doc["executionRecords"]}
        self.assertTrue(all(r["recordedLate"] for r in records.values()))
        self.assertEqual({t: r["result"] for t, r in records.items()},
                         {"t7": "completed", "t8": "partial", "t9": "not_started", "t10": "incomplete"})
        self.assertEqual([records[t]["actualMinutes"] for t in ("t7", "t8", "t9", "t10")], [None, None, 0, None])
        done = {e["id"]: e["completed"] for e in doc["plan"]["entries"]}
        self.assertEqual(done, {"t7": True, "t8": False, "t9": False, "t10": False})
        with mock.patch(NOW, return_value=at(12)):
            self.assertEqual(self.attention(), [], "recorded tasks are no longer silent")

    def test_late_records_only_for_past_days_and_only_once(self):
        with mock.patch(NOW, return_value=at(9)):
            self.late(("t9", "completed"), status=400)  # today: the check-in is still to come
            self.late(("t7", "completed"), ("t7", "partial"), status=400)
            self.late(("t7", "completed"))
            self.late(("t7", "partial"), status=400)
        self.check_in("t8")
        with mock.patch(NOW, return_value=at(12)):
            self.late(("t8", "completed"), status=400)

    def test_late_results_never_teach_the_profile(self):
        """Three misses at the block would shrink it; recalled ones do not."""
        def misses(doc, late):
            for day in (7, 8, 9):
                doc["executionRecords"].append({
                    "id": f"r{day}{late}", "planId": doc["plan"]["id"], "taskId": f"t{day}", "profileId": doc["profile"]["id"],
                    "profileVersion": doc["profile"]["version"], "projectId": "essay", "projectProfileId": None,
                    "taskTitle": "에세이", "plannedMinutes": 30, "actualMinutes": 15, "remainingMinutes": 15,
                    "result": "partial", "reasonCode": "time_shortage", "note": "", "difficulty": None,
                    "recoveryAction": None, "plannedStart": f"2030-01-{day:02}T18:00",
                    "createdAt": datetime.now(KST).isoformat(), **({"recordedLate": True} if late else {})})
            propose_update(doc, "essay")

        self.seed(lambda doc: misses(doc, late=True))
        self.assertEqual(self.state()["profileUpdateProposals"], [])
        self.seed(lambda doc: (doc["executionRecords"].clear(), misses(doc, late=False)))
        self.assertEqual(len(self.state()["profileUpdateProposals"]), 1, "the same misses checked in at the time do teach")

    def test_late_results_keep_the_next_plan_honest(self):
        with mock.patch(NOW, return_value=at(12)):
            self.late(("t7", "completed"), ("t8", "incomplete"))
        history = project_history(self.store.read(), [ProjectContext(**ESSAY)], date(2030, 1, 14))["essay"]
        self.assertEqual(history["finished"], ["에세이 7"], "done work is not planned again")
        self.assertEqual([u["title"] for u in history["unfinished"]], ["에세이 8"], "unknown work stays to do")


if __name__ == "__main__":
    unittest.main()
