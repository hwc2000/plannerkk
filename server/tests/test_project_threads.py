import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from server.app.execution_profile import generate_profile
from server.app.execution_store import ExecutionStore
from server.app.main import create_app
from server.tests.test_execution import ANSWERS

ESSAY = {"id": "essay", "title": "에세이", "goal": "초안 제출", "startDate": "2030-01-01", "dueDate": "2030-01-31"}
APP = {"id": "app", "title": "앱 개발", "goal": "로그인 화면", "startDate": "2030-01-01", "dueDate": "2030-01-31"}


class FakeLLM:
    def __init__(self):
        self.chat_calls = []
        self.route, self.replies = {"skill": "answer", "lookups": [], "reply": "좋아요"}, {}

    async def generate(self, **kwargs):
        if kwargs["name"] == "execution_profile":
            return generate_profile(ANSWERS)["insights"]
        if kwargs["name"].startswith("planner_"):
            self.chat_calls.append(kwargs)
            return self.route if kwargs["name"] == "planner_route" else self.replies[kwargs["name"]]
        title = (kwargs["context"]["project"] or {"title": "자유"})["title"]
        return {"tasks": [{"title": f"{title} 작업 {i}", "minutes": 20, "doneWhen": "완료", "dueDate": None, "projectId": None}
                          for i in range(2)]}


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"})
class ProjectThreadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.llm = FakeLLM()
        self.client = TestClient(create_app(
            execution_store=ExecutionStore(Path(self.temp.name) / "db.sqlite3"), execution_llm=self.llm))
        self.revision = self.client.get("/api/execution").json()["revision"]
        self.call("/api/execution/profile", answers=ANSWERS)
        self.call("/api/execution/profile/confirm")
        slots = [{"day": d, "hour": h} for d in range(7) for h in (19, 20)]
        self.revision = self.client.put("/api/execution/settings", json={
            "revision": self.revision, "settings": {"slots": slots, "view": "timeline"}}).json()["revision"]

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def call(self, path, **body):
        response = self.client.post(path, json={"revision": self.revision, **body})
        self.assertEqual(response.status_code, 200, response.text)
        self.revision = response.json()["revision"]
        return response.json()

    def plan(self, project, goal, start="2030-01-07"):
        draft = self.call("/api/execution/plan", goal=goal, startDate=start, consent=True, project=project, merge=True)["planDraft"]
        return self.call("/api/execution/plan/confirm", planId=draft["id"],
                         project=draft["project"])["plan"]

    def test_each_project_keeps_its_own_conversation(self):
        self.call("/api/execution/chat/message", text="에세이 얘기", consent=True, project=ESSAY)
        self.call("/api/execution/chat/message", text="앱 얘기", consent=True, project=APP)
        state = self.call("/api/execution/chat/message", text="자유 얘기", consent=True)

        threads = state["plannerThreads"]
        self.assertEqual(threads["essay"]["messages"][0]["content"], "에세이 얘기")
        self.assertEqual(threads["app"]["messages"][0]["content"], "앱 얘기")
        self.assertEqual(threads["_free"]["messages"][0]["content"], "자유 얘기")
        self.call("/api/execution/chat/message", text="이어서", consent=True, project=APP)
        self.assertEqual([m["content"] for m in self.llm.chat_calls[-1]["context"]["messages"]], ["앱 얘기", "좋아요"])

        state = self.call("/api/execution/chat/reset", projectId="essay")
        self.assertNotIn("essay", state["plannerThreads"])
        self.assertIn("app", state["plannerThreads"])

    def test_project_plans_share_the_week_without_touching_each_other(self):
        essay_plan = self.plan(ESSAY, "에세이 초안")
        essay_tasks = [e for e in essay_plan["entries"] if e["kind"] == "task"]
        self.call("/api/execution/task", planId=essay_plan["id"], taskId=essay_tasks[0]["id"], completed=True)

        merged = self.plan(APP, "로그인 화면", start="2030-01-09")
        self.assertEqual(merged["startDate"], "2030-01-07")
        tasks = [e for e in merged["entries"] if e["kind"] == "task"]
        for kept in essay_tasks:
            match = next(e for e in tasks if e["id"] == kept["id"])
            self.assertEqual((match["start"], match["projectId"]), (kept["start"], "essay"))
        self.assertTrue(next(e for e in tasks if e["id"] == essay_tasks[0]["id"])["completed"])
        self.assertEqual({e["projectId"] for e in tasks}, {"essay", "app"})
        self.assertTrue(all(a["end"] <= b["start"] for a, b in zip(merged["entries"], merged["entries"][1:])))
        self.assertEqual([p["id"] for p in merged["projects"]], ["essay", "app"])
        self.assertIsNone(merged["project"])
        self.assertIn("[에세이] 에세이 초안", merged["goal"])

        replanned = self.plan(ESSAY, "에세이 퇴고")
        ids = {e["id"] for e in replanned["entries"] if e["kind"] == "task"}
        self.assertIn(essay_tasks[0]["id"], ids)
        self.assertNotIn(essay_tasks[1]["id"], ids)
        self.assertTrue({e["id"] for e in tasks if e["projectId"] == "app"} <= ids)
        self.assertIn("[에세이] 에세이 퇴고", replanned["goal"])

    def test_plan_card_uses_the_active_week(self):
        self.plan(ESSAY, "에세이 초안")
        self.llm.route = {"skill": "plan_create", "lookups": [], "reply": None}
        self.llm.replies = {"planner_plan_create": {"reply": "정리했어요", "ready": True, "goal": "로그인", "startDate": None}}
        state = self.call("/api/execution/chat/message", text="로그인 화면 만들래", consent=True, project=APP)
        self.assertEqual(state["plannerThreads"]["app"]["action"]["payload"], {"goal": "로그인", "startDate": "2030-01-07"})
        self.assertGreater(state["plannerThreads"]["app"]["action"]["freeMinutes"], 0)
        self.assertEqual(state["plannerThreads"]["app"]["action"]["revision"], state["revision"])


if __name__ == "__main__":
    unittest.main()
