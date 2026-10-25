import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from server.app.auth import AuthStore, hash_password, verify_password
from server.app.main import create_app

USER_A = {"email": "a@example.com", "password": "planner-pass-1", "displayName": "에이"}
USER_B = {"email": "b@example.com", "password": "planner-pass-2", "displayName": "비"}


class PasswordTests(unittest.TestCase):
    def test_hash_round_trip_and_salt(self):
        first, second = hash_password("correct horse"), hash_password("correct horse")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("correct horse", first))
        self.assertFalse(verify_password("wrong horse", first))
        self.assertFalse(verify_password("anything", "garbage"))


class AuthApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "db.sqlite3"
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("DEMO_PASSWORD", None)
        os.environ.pop("REPLAN_AUTH", None)
        self.app = create_app(auth=True, db_path=self.db)

    def client(self):
        return TestClient(self.app)

    def test_api_requires_login_but_health_and_config_do_not(self):
        c = self.client()
        self.assertEqual(c.get("/api/health").status_code, 200)
        self.assertEqual(c.get("/api/auth/config").json(), {"enabled": True})
        self.assertEqual(c.get("/api/execution").status_code, 401)
        self.assertEqual(c.get("/api/workspace").status_code, 401)
        self.assertEqual(c.get("/api/auth/me").status_code, 401)

    def test_signup_login_logout_flow(self):
        c = self.client()
        signed = c.post("/api/auth/signup", json=USER_A)
        self.assertEqual(signed.status_code, 200, signed.text)
        self.assertEqual(signed.json()["user"]["email"], "a@example.com")
        self.assertIn("httponly", signed.headers["set-cookie"].lower())
        self.assertEqual(c.get("/api/auth/me").json()["user"]["displayName"], "에이")
        self.assertEqual(c.get("/api/execution").status_code, 200)

        self.assertEqual(c.post("/api/auth/logout").status_code, 200)
        self.assertEqual(c.get("/api/execution").status_code, 401)

        bad = c.post("/api/auth/login", json={"email": USER_A["email"], "password": "nope-nope"})
        self.assertEqual(bad.status_code, 401)
        good = c.post("/api/auth/login", json={"email": " A@Example.com ", "password": USER_A["password"]})
        self.assertEqual(good.status_code, 200)
        self.assertEqual(c.get("/api/execution").status_code, 200)

    def test_duplicate_email_and_weak_password_are_rejected(self):
        c = self.client()
        c.post("/api/auth/signup", json=USER_A)
        self.assertEqual(self.client().post("/api/auth/signup", json=USER_A).status_code, 409)
        weak = self.client().post("/api/auth/signup", json={**USER_B, "password": "aaaaaaaa"})
        self.assertEqual(weak.status_code, 422)
        bad_email = self.client().post("/api/auth/signup", json={**USER_B, "email": "not-an-email"})
        self.assertEqual(bad_email.status_code, 422)

    def test_repeated_failures_are_throttled(self):
        c = self.client()
        c.post("/api/auth/signup", json=USER_A)
        for _ in range(5):
            c.post("/api/auth/login", json={"email": USER_A["email"], "password": "wrong-pass"})
        locked = c.post("/api/auth/login", json={"email": USER_A["email"], "password": USER_A["password"]})
        self.assertEqual(locked.status_code, 429)

    def test_each_user_gets_their_own_execution_state_and_workspace(self):
        a, b = self.client(), self.client()
        a.post("/api/auth/signup", json=USER_A)
        b.post("/api/auth/signup", json=USER_B)

        state_a = a.get("/api/execution").json()
        saved = a.put("/api/execution/settings", json={
            "revision": state_a["revision"], "settings": {"slots": [{"day": 0, "hour": 9}], "view": "checklist"}})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(a.get("/api/execution").json()["settings"]["view"], "checklist")
        self.assertEqual(b.get("/api/execution").json()["revision"], 0)
        self.assertEqual(b.get("/api/execution").json()["settings"]["slots"], [])

        project = {"id": "p1", "title": "A의 프로젝트", "goal": "", "startDate": "2026-10-01",
                   "dueDate": "2026-10-31", "priority": "high", "status": "active"}
        self.assertFalse(a.get("/api/workspace").json()["exists"])
        put = a.put("/api/workspace", json={"projects": [project], "milestones": [], "events": [], "memories": []})
        self.assertEqual(put.status_code, 200)
        self.assertEqual(a.get("/api/workspace").json()["projects"][0]["title"], "A의 프로젝트")
        self.assertEqual(b.get("/api/workspace").json()["projects"], [])

    def test_first_account_inherits_legacy_single_user_data(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("CREATE TABLE execution_state (id INTEGER PRIMARY KEY CHECK(id=1), document TEXT NOT NULL)")
            db.execute("INSERT INTO execution_state VALUES (1, ?)", (json.dumps({
                "revision": 3, "settings": {"slots": [{"day": 1, "hour": 10}], "view": "timeline"},
                "surveyResponses": [{"id": "s1", "userId": "local"}]}),))
        a = self.client()
        signed = a.post("/api/auth/signup", json=USER_A).json()
        self.assertTrue(signed["user"]["claimedLegacyData"])
        state = a.get("/api/execution").json()
        self.assertEqual(state["revision"], 3)
        self.assertEqual(state["surveyResponses"][0]["userId"], signed["user"]["id"])

        b = self.client()
        self.assertFalse(b.post("/api/auth/signup", json=USER_B).json()["user"]["claimedLegacyData"])
        self.assertEqual(b.get("/api/execution").json()["revision"], 0)


class OpenModeTests(unittest.TestCase):
    def test_auth_can_be_turned_off_for_local_single_user(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        with mock.patch.dict(os.environ, {"REPLAN_AUTH": "off"}):
            os.environ.pop("DEMO_PASSWORD", None)
            app = create_app(db_path=Path(temp.name) / "db.sqlite3")
        c = TestClient(app)
        self.assertEqual(c.get("/api/auth/config").json(), {"enabled": False})
        self.assertEqual(c.get("/api/execution").status_code, 200)


class AuthStoreTests(unittest.TestCase):
    def test_expired_sessions_are_ignored(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = AuthStore(Path(temp.name) / "db.sqlite3")
        user = store.create_user("x@example.com", "long-password", "엑스")
        token = store.create_session(user["id"])
        self.assertEqual(store.session_user(token), user["id"])
        with closing(sqlite3.connect(store.path)) as db, db:
            db.execute("UPDATE sessions SET expires_at = 0")
        self.assertIsNone(store.session_user(token))
        self.assertIsNone(store.session_user("unknown"))


if __name__ == "__main__":
    unittest.main()
