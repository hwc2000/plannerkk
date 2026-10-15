"""Users stand alone: every request uses only the calling user's store.

Login is not built yet; these tests stand in for it by overriding
``current_user``, the one function the login work will replace.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from server.app.auth import CurrentUserStore, current_user
from server.app.execution_store import ExecutionStore
from server.app.main import create_app
from server.tests.test_adaptive_api import PLAIN_ANSWERS
from server.tests.test_project_independence import ESSAY, FakeLLM


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"})
class UserIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ExecutionStore(Path(self.temp.name) / "db.sqlite3")
        self.client = TestClient(create_app(execution_store=self.store, execution_llm=FakeLLM()))

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def as_user(self, user_id):
        self.client.app.dependency_overrides[current_user] = lambda: user_id
        return self.client.get("/api/execution").json()

    def call(self, state, path, method="post", **body):
        response = getattr(self.client, method)(path, json={"revision": state["revision"], **body})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def onboard(self, state):
        state = self.call(state, "/api/execution/profile", answers=PLAIN_ANSWERS)
        return self.call(state, "/api/execution/profile/confirm")

    def test_each_user_sees_and_changes_only_their_own_data(self):
        first = self.onboard(self.as_user("user1"))
        first = self.call(first, "/api/execution/projects/essay/profile", method="put", overrides={"blockMinutes": 15})
        first = self.call(first, "/api/execution/chat/message", text="에세이 얘기", consent=True, project=ESSAY)

        second = self.as_user("user2")
        self.assertIsNone(second["profile"])
        self.assertEqual((second["projectProfiles"], second["plannerThreads"], second["revision"]), ({}, {}, 0))
        second = self.onboard(second)
        self.assertEqual(second["profile"]["userId"], "user2")

        again = self.as_user("user1")
        self.assertEqual(again["profile"]["id"], first["profile"]["id"])
        self.assertEqual(again["projectProfiles"]["essay"]["userId"], "user1")
        self.assertEqual(list(again["plannerThreads"]), ["essay"])
        # Both live in the same database file, one document per user.
        self.assertEqual(ExecutionStore(self.store.path, user_id="user2").read()["profile"]["userId"], "user2")

    def test_the_local_user_keeps_the_existing_data(self):
        local = self.onboard(self.client.get("/api/execution").json())
        self.assertEqual(local["profile"]["userId"], "local")
        self.assertEqual(self.store.read()["profile"]["id"], local["profile"]["id"])

    def test_no_store_without_a_known_user(self):
        with self.assertRaises(RuntimeError):
            CurrentUserStore().read()


if __name__ == "__main__":
    unittest.main()
