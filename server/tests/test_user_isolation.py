"""Users stand alone: every request uses only the logged-in user's store."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException
from fastapi.testclient import TestClient

from server.app.auth import UserScopedStore
from server.app.execution_store import ExecutionStore
from server.app.main import create_app
from server.tests.test_adaptive_api import PLAIN_ANSWERS
from server.tests.test_project_independence import ESSAY, FakeLLM


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test", "DEMO_PASSWORD": "", "REPLAN_AUTH": ""})
class UserIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "db.sqlite3"
        self.app = create_app(execution_llm=FakeLLM(), auth=True, db_path=self.db)
        self.clients = []

    def tearDown(self):
        for client in self.clients:
            client.close()
        self.temp.cleanup()

    def sign_up(self, email):
        """A browser of its own: each client keeps its own session cookie."""
        client = TestClient(self.app)
        self.clients.append(client)
        response = client.post("/api/auth/signup", json={"email": email, "password": "planner-pass-1", "displayName": email[0]})
        self.assertEqual(response.status_code, 200, response.text)
        return client, response.json()["user"]["id"]

    def call(self, client, state, path, method="post", **body):
        response = getattr(client, method)(path, json={"revision": state["revision"], **body})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def onboard(self, client, state):
        state = self.call(client, state, "/api/execution/profile", answers=PLAIN_ANSWERS)
        return self.call(client, state, "/api/execution/profile/confirm")

    def test_each_user_sees_and_changes_only_their_own_data(self):
        first_client, first_id = self.sign_up("a@example.com")
        first = self.onboard(first_client, first_client.get("/api/execution").json())
        first = self.call(first_client, first, "/api/execution/projects/essay/profile", method="put", overrides={"blockMinutes": 15})
        first = self.call(first_client, first, "/api/execution/chat/message", text="에세이 얘기", consent=True, project=ESSAY)

        second_client, second_id = self.sign_up("b@example.com")
        second = second_client.get("/api/execution").json()
        self.assertIsNone(second["profile"])
        self.assertEqual((second["projectProfiles"], second["plannerThreads"], second["revision"]), ({}, {}, 0))
        second = self.onboard(second_client, second)
        self.assertEqual(second["profile"]["userId"], second_id)

        again = first_client.get("/api/execution").json()
        self.assertEqual(again["profile"]["id"], first["profile"]["id"])
        self.assertEqual(again["projectProfiles"]["essay"]["userId"], first_id)
        self.assertEqual(list(again["plannerThreads"]), ["essay"])
        # Both live in the same database file, one document per user.
        self.assertEqual(ExecutionStore(self.db, user_id=second_id).read()["profile"]["userId"], second_id)

    def test_the_local_user_keeps_the_existing_data(self):
        store = ExecutionStore(self.db)
        with TestClient(create_app(execution_store=store, execution_llm=FakeLLM())) as client:
            local = self.onboard(client, client.get("/api/execution").json())
        self.assertEqual(local["profile"]["userId"], "local")
        self.assertEqual(store.read()["profile"]["id"], local["profile"]["id"])

    def test_no_store_without_a_known_user(self):
        with self.assertRaises(HTTPException) as caught:
            UserScopedStore(self.db).read()
        self.assertEqual(caught.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
