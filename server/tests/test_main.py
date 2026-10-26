import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from server.app.execution_store import ExecutionStore
from server.app.main import create_app
from server.app.planner import ProjectContext


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(execution_store=ExecutionStore(Path(self.temp.name) / "db.sqlite3")))

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_health_endpoint(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_invalid_input_has_readable_detail(self):
        response = self.client.post("/api/execution/plan", json={"revision": 0, "goal": "", "startDate": "2030-01-07"})
        self.assertEqual(response.status_code, 422)
        self.assertIsInstance(response.json()["detail"], str)

    def test_full_project_from_older_client_is_accepted(self):
        project = ProjectContext.model_validate({"id": "p", "title": "시험", "goal": "통과", "startDate": "2030-01-07",
                                                 "dueDate": "2030-01-10", "priority": "high", "status": "active"})
        self.assertEqual(project.id, "p")


if __name__ == "__main__":
    unittest.main()
