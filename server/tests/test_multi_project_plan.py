import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from server.app.execution_profile import generate_profile
from server.app.execution_store import ExecutionStore
from server.app.main import create_app
from server.tests.test_execution import ANSWERS

ESSAY = {"id": "essay", "title": "에세이", "goal": "초안 제출", "startDate": "2030-01-07", "dueDate": "2030-01-08"}
APP = {"id": "app", "title": "앱 개발", "goal": "로그인 화면", "startDate": "2030-01-09", "dueDate": "2030-01-31"}


class FakeLLM:
    def __init__(self):
        self.plan_calls = []

    async def generate(self, **kwargs):
        if kwargs["name"] == "execution_profile":
            return generate_profile(ANSWERS)["insights"]
        self.plan_calls.append(kwargs)
        return {"tasks": [
            {"title": "에세이 개요", "minutes": 20, "doneWhen": "개요 작성", "dueDate": None, "projectId": "essay"},
            {"title": "로그인 화면", "minutes": 20, "doneWhen": "화면 완성", "dueDate": None, "projectId": "app"},
            {"title": "방 정리", "minutes": 20, "doneWhen": "정리 끝", "dueDate": None, "projectId": "unknown"},
        ]}


class MultiProjectPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.llm = FakeLLM()
        self.client = TestClient(create_app(
            execution_store=ExecutionStore(Path(self.temp.name) / "db.sqlite3"), execution_llm=self.llm))
        self.revision = self.client.get("/api/execution").json()["revision"]

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def call(self, path, **body):
        response = self.client.post(path, json={"revision": self.revision, **body})
        self.assertEqual(response.status_code, 200, response.text)
        self.revision = response.json()["revision"]
        return response.json()

    def test_one_week_plans_several_projects_inside_their_periods(self):
        self.call("/api/execution/profile", answers=ANSWERS)
        self.call("/api/execution/profile/confirm")
        slots = [{"day": d, "hour": 19} for d in range(7)]
        response = self.client.put("/api/execution/settings", json={
            "revision": self.revision, "settings": {"slots": slots, "view": "timeline"}})
        self.revision = response.json()["revision"]

        draft = self.call("/api/execution/plan", goal="에세이와 앱", startDate="2030-01-07", consent=True,
                          projects=[ESSAY, APP])["planDraft"]

        context = self.llm.plan_calls[0]["context"]
        self.assertEqual([p["id"] for p in context["projects"]], ["essay", "app"])
        tasks = {e["title"].split(" (")[0]: e for e in draft["entries"] if e["kind"] == "task"}
        self.assertEqual(tasks["에세이 개요"]["projectId"], "essay")
        self.assertLessEqual(tasks["에세이 개요"]["start"][:10], ESSAY["dueDate"])
        self.assertEqual(tasks["로그인 화면"]["projectId"], "app")
        self.assertGreaterEqual(tasks["로그인 화면"]["start"][:10], APP["startDate"])
        self.assertIsNone(tasks["방 정리"]["projectId"])
        self.assertTrue(all("notBefore" not in e for e in draft["entries"]))
        self.assertIsNone(draft["project"])
        self.assertEqual([p["id"] for p in draft["projects"]], ["essay", "app"])

        plan = self.call("/api/execution/plan/confirm", planId=draft["id"])["plan"]
        self.assertEqual(plan["status"], "confirmed")

    def test_single_project_keeps_the_previous_shape(self):
        self.call("/api/execution/profile", answers=ANSWERS)
        self.call("/api/execution/profile/confirm")
        response = self.client.put("/api/execution/settings", json={
            "revision": self.revision, "settings": {"slots": [{"day": 0, "hour": 19}], "view": "timeline"}})
        self.revision = response.json()["revision"]

        draft = self.call("/api/execution/plan", goal="에세이", startDate="2030-01-07", consent=True,
                          project=ESSAY)["planDraft"]

        self.assertEqual(draft["projectId"], "essay")
        self.assertEqual(draft["project"]["id"], "essay")
        self.assertTrue(all(e["projectId"] == "essay" for e in draft["entries"] if e["kind"] == "task"))


if __name__ == "__main__":
    unittest.main()
