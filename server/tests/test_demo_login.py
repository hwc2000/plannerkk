import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from server.app.execution_store import ExecutionStore
from server.app.main import create_app


def basic(password):
    return {"Authorization": "Basic " + base64.b64encode(f"demo:{password}".encode()).decode()}


class DemoLoginTests(unittest.TestCase):
    def client(self, env):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        with mock.patch.dict(os.environ, env):
            app = create_app(execution_store=ExecutionStore(Path(temp.name) / "db.sqlite3"))
        return TestClient(app)

    def test_without_a_password_everything_stays_open(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEMO_PASSWORD", None)
            client = self.client({})
        self.assertEqual(client.get("/api/execution").status_code, 200)

    def test_a_demo_password_guards_pages_and_api_but_not_health(self):
        client = self.client({"DEMO_PASSWORD": "s3cret"})
        self.assertEqual(client.get("/api/health").status_code, 200)
        denied = client.get("/api/execution")
        self.assertEqual(denied.status_code, 401)
        self.assertIn("Basic", denied.headers["WWW-Authenticate"])
        self.assertEqual(client.get("/api/execution", headers=basic("wrong")).status_code, 401)
        self.assertEqual(client.get("/api/execution", headers={"Authorization": "Basic !!!"}).status_code, 401)
        self.assertEqual(client.get("/api/execution", headers=basic("s3cret")).status_code, 200)


if __name__ == "__main__":
    unittest.main()
