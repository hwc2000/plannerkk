import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from server.app.execution_store import ExecutionStore
from server.app.main import create_app


def task(task_id, start, end):
    return {"id": task_id, "kind": "task", "title": task_id, "minutes": 30, "doneWhen": "끝", "dueDate": None,
            "start": start, "end": end, "completed": False, "projectId": "p1"}


def pause(break_id, start, end):
    return {"id": break_id, "kind": "break", "title": "휴식", "minutes": 5, "doneWhen": "", "dueDate": None,
            "start": start, "end": end, "completed": False}


class RemoveTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ExecutionStore(Path(self.temp.name) / "db.sqlite3")
        self.client = TestClient(create_app(execution_store=self.store, auth=False))
        entries = [task("a", "2030-01-07T19:00", "2030-01-07T19:30"), pause("b1", "2030-01-07T19:30", "2030-01-07T19:35"),
                   task("c", "2030-01-07T19:35", "2030-01-07T20:05")]

        def seed(doc):
            doc["plan"] = {"id": "week", "entries": entries, "pendingTasks": [], "startDate": "2030-01-07", "endDate": "2030-01-13"}
            doc["planDraft"] = {"id": "draft", "entries": [dict(e) for e in entries], "pendingTasks": []}
            doc["recoveryDrafts"] = {"a": {"id": "r1", "planId": "week"}}
        self.store.change(0, seed)

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def remove(self, task_id, plan_id="week"):
        return self.client.post("/api/execution/task/remove", json={"revision": self.store.read()["revision"], "planId": plan_id, "taskId": task_id})

    def test_removes_the_task_and_its_break_from_plan_and_draft(self):
        response = self.remove("a")
        self.assertEqual(response.status_code, 200, response.text)
        state = response.json()
        self.assertEqual([e["id"] for e in state["plan"]["entries"]], ["c"])
        self.assertEqual([e["id"] for e in state["planDraft"]["entries"]], ["c"])
        self.assertEqual(state["recoveryDrafts"], {})

    def test_rejects_an_unknown_task_or_an_old_plan(self):
        self.assertEqual(self.remove("b1").status_code, 400)
        self.assertEqual(self.remove("a", plan_id="old").status_code, 400)
        self.assertEqual(len(self.store.read()["plan"]["entries"]), 3)


if __name__ == "__main__":
    unittest.main()
