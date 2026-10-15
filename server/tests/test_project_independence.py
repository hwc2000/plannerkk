"""Projects stand alone inside a shared week; only the user profile is shared.

Each project plans, records, learns and is replanned with its own settings on
top of the user profile.  Another project's settings never reach it.
"""
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from server.app.execution_learning import propose_update
from server.app.execution_profile import generate_profile
from server.app.execution_store import ExecutionStore
from server.app.main import create_app
from server.tests.test_adaptive_api import PLAIN_ANSWERS

ESSAY = {"id": "essay", "title": "에세이", "goal": "초안 제출", "startDate": "2030-01-01", "dueDate": "2030-01-31"}
APP = {"id": "app", "title": "앱 개발", "goal": "로그인 화면", "startDate": "2030-01-01", "dueDate": "2030-01-31"}
BASE_BLOCK = 30  # PLAIN_ANSWERS' focus block
# A chat turn the router answers itself, without reading saved data.
ANSWER_ROUTE = {"skill": "answer", "lookups": [], "reply": "좋아요"}


class FakeLLM:
    """Plans two tasks per project in the request; minutes per project, a second value after a retry.

    A chat turn is routed by ``route``; each skill call answers from ``replies`` by call name.
    """

    def __init__(self):
        self.plan_calls, self.chat_calls = [], []
        self.minutes, self.retry_minutes = {}, {}
        self.route, self.replies = ANSWER_ROUTE, {}

    async def generate(self, **kwargs):
        if kwargs["name"] == "execution_profile":
            return generate_profile(PLAIN_ANSWERS)["insights"]
        if kwargs["name"].startswith("planner_"):
            self.chat_calls.append(kwargs)
            if kwargs["name"] == "planner_route":
                return self.route
            return self.replies.get(kwargs["name"], {"reply": "좋아요"})
        self.plan_calls.append(kwargs)
        context = kwargs["context"]
        minutes = self.retry_minutes if context.get("previousErrors") else self.minutes
        return {"tasks": [
            {"title": f"{p['title']} 작업 {i}", "minutes": minutes.get(p["id"], 20), "doneWhen": "완료",
             "dueDate": None, "projectId": p["id"]}
            for p in context["projects"] for i in range(2)
        ]}


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"})
class ProjectIndependenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.llm = FakeLLM()
        self.store = ExecutionStore(Path(self.temp.name) / "db.sqlite3")
        self.client = TestClient(create_app(execution_store=self.store, execution_llm=self.llm))
        self.revision = self.client.get("/api/execution").json()["revision"]
        self.call("/api/execution/profile", answers=PLAIN_ANSWERS)
        self.call("/api/execution/profile/confirm")
        slots = [{"day": d, "hour": h} for d in range(7) for h in (18, 19, 20)]
        self.call("/api/execution/settings", method="put", settings={"slots": slots, "view": "timeline"})

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

    def draft(self, project, goal):
        return self.call("/api/execution/plan", goal=goal, startDate="2030-01-07", consent=True,
                         project=project, merge=True)["planDraft"]

    def plan(self, project, goal):
        draft = self.draft(project, goal)
        return self.call("/api/execution/plan/confirm", planId=draft["id"], project=draft["project"])["plan"]

    def set_project(self, project_id, **overrides):
        state = self.call(f"/api/execution/projects/{project_id}/profile", method="put", overrides=overrides)
        return state["projectProfiles"][project_id]["id"]

    @staticmethod
    def tasks(plan, project_id):
        return [e for e in plan["entries"] if e["kind"] == "task" and e.get("projectId") == project_id]

    def test_each_project_plans_and_records_with_its_own_settings(self):
        essay_settings = self.set_project("essay", blockMinutes=15)
        self.llm.minutes = {"essay": 15}
        self.plan(ESSAY, "에세이 초안")
        week = self.plan(APP, "로그인 화면")

        essay_call, app_call = self.llm.plan_calls
        self.assertEqual((essay_call["context"]["maxBlockMinutes"], app_call["context"]["maxBlockMinutes"]), (15, BASE_BLOCK))
        self.assertEqual({e["projectProfileId"] for e in self.tasks(week, "essay")}, {essay_settings})
        self.assertEqual({e["projectProfileId"] for e in self.tasks(week, "app")}, {None})

        # A record in a shared week counts for its own project and settings version.
        for project_id, expected in (("essay", essay_settings), ("app", None)):
            task = self.tasks(week, project_id)[0]
            record = self.call("/api/execution/task", planId=week["id"], taskId=task["id"], completed=True)["executionRecords"][-1]
            self.assertEqual((record["projectId"], record["projectProfileId"]), (project_id, expected))

    def test_a_project_change_replans_only_that_project_in_a_shared_week(self):
        self.plan(ESSAY, "에세이 초안")
        week = self.plan(APP, "로그인 화면")
        app_before = self.tasks(week, "app")

        def fail_essay(doc):
            for i in range(3):
                doc["executionRecords"].append({
                    "id": f"essay-{i}", "planId": doc["plan"]["id"], "taskId": f"t{i}", "profileId": doc["profile"]["id"],
                    "profileVersion": doc["profile"]["version"], "projectId": "essay", "projectProfileId": None,
                    "taskTitle": "긴 작업", "plannedMinutes": 50, "actualMinutes": 20, "remainingMinutes": 30,
                    "result": "partial", "reasonCode": "time_shortage", "note": "", "difficulty": None,
                    "recoveryAction": None, "createdAt": datetime.now(timezone.utc).isoformat(),
                })
            propose_update(doc, "essay")
        self.revision = self.store.change(self.revision, fail_essay)["revision"]
        [proposal] = self.state()["profileUpdateProposals"]
        essay_settings = self.call(f"/api/execution/proposals/{proposal['id']}/approve")["projectProfiles"]["essay"]["id"]

        # The app's tasks were planned with settings that did not change: recovery still works there.
        moved = self.call("/api/adaptive/check-in", taskId=app_before[0]["id"], consent=True,
                          checkIn={"completed": False, "actualMinutes": 5, "reasonCode": "time_shortage"})
        self.assertEqual(moved["recoveryDraft"]["strategy"], "reschedule")
        stale = self.call("/api/adaptive/check-in", 400, taskId=self.tasks(week, "essay")[0]["id"], consent=True,
                          checkIn={"completed": False, "actualMinutes": 5, "reasonCode": "time_shortage"})
        self.assertIn("‘에세이’ 설정이 바뀌었습니다", stale["detail"])

        draft = self.call("/api/execution/plan", goal="무시됨", startDate="2030-01-07", consent=True,
                          profileChangeProposalId=proposal["id"])["planDraft"]

        context = self.llm.plan_calls[-1]["context"]
        self.assertEqual([p["id"] for p in context["projects"]], ["essay"])
        self.assertEqual((context["maxBlockMinutes"], context["profileChange"]["projectId"]), (20, "essay"))
        self.assertEqual([(e["id"], e["start"]) for e in self.tasks(draft, "app")], [(e["id"], e["start"]) for e in app_before])
        self.assertEqual({e["projectProfileId"] for e in self.tasks(draft, "essay")}, {essay_settings})
        self.assertFalse({e["id"] for e in self.tasks(draft, "essay")} & {e["id"] for e in self.tasks(week, "essay")})
        self.call("/api/execution/plan/confirm", planId=draft["id"], project=None)

    def test_confirming_checks_only_the_projects_it_planned(self):
        self.plan(ESSAY, "에세이 초안")
        app_draft = self.draft(APP, "로그인 화면")
        self.set_project("essay", blockMinutes=20)  # the essay's tasks are now stale, the app's are not

        self.call("/api/execution/plan/confirm", planId=app_draft["id"], project=None)

        essay_draft = self.draft(ESSAY, "에세이 퇴고")
        self.set_project("essay", blockMinutes=25)
        error = self.call("/api/execution/plan/confirm", 400, planId=essay_draft["id"], project=None)
        self.assertIn("초안 생성 후 ‘에세이’ 설정이 바뀌었습니다", error["detail"])

    def test_one_request_for_several_projects_keeps_each_projects_block(self):
        essay_settings = self.set_project("essay", blockMinutes=15)
        self.llm.minutes, self.llm.retry_minutes = {"essay": 20, "app": 25}, {"essay": 15, "app": 25}

        draft = self.call("/api/execution/plan", goal="에세이와 앱", startDate="2030-01-07", consent=True,
                          projects=[ESSAY, APP])["planDraft"]

        first, retry = self.llm.plan_calls
        caps = {p["id"]: p["maxBlockMinutes"] for p in first["context"]["projects"]}
        self.assertEqual(caps, {"essay": 15, "app": BASE_BLOCK})
        self.assertEqual(retry["context"]["previousErrors"],
                         [f"'에세이 작업 {i}' 20분은 작업당 최대 15분을 넘습니다. 15분 이하 작업 여러 개로 나누세요." for i in range(2)])
        self.assertEqual({e["minutes"] for e in self.tasks(draft, "app")}, {25})  # the app keeps its own, longer block
        self.assertEqual({e["projectProfileId"] for e in self.tasks(draft, "essay")}, {essay_settings})
        reason = next(r for r in draft["personalization"] if r["key"] == "taskLength:essay")
        self.assertTrue(reason["applied"].startswith("‘에세이’ 작업은 한 번에 15분 이하로"))
        self.assertEqual(reason["source"], "project")

    def test_chat_sees_only_its_own_project_and_the_shared_profile(self):
        self.set_project("essay", blockMinutes=15)
        self.llm.route = {"skill": "answer", "lookups": ["profile"], "reply": None}

        self.call("/api/execution/chat/message", text="에세이는 몇 분씩 해?", consent=True, project=ESSAY)
        self.call("/api/execution/chat/message", text="앱은 몇 분씩 해?", consent=True, project=APP)

        essay, app = (call["context"]["lookups"]["profile"]["settings"][0] for call in self.llm.chat_calls
                      if call["name"] == "planner_answer")
        self.assertEqual(essay, {"name": "한 번에 집중할 시간", "value": "15분", "source": "이 프로젝트에서 사용자가 정함",
                                 "basicProfileValue": f"{BASE_BLOCK}분"})
        self.assertEqual(app, {"name": "한 번에 집중할 시간", "value": f"{BASE_BLOCK}분", "source": "설문 답에서 정함"})

    def test_chat_turns_what_the_user_says_about_a_project_into_a_card(self):
        said = {"blockMinutes": 25, "dailyPlannedMinutes": None, "bufferPercent": None, "starterMinutes": None,
                "recoveryPreference": None}
        self.llm.route = {"skill": "project_settings", "lookups": [], "reply": None}
        self.llm.replies = {"planner_project_settings": {"reply": "좋아요", "projectSettings": said}}

        state = self.call("/api/execution/chat/message", text="에세이는 25분씩만 할래요", consent=True, project=ESSAY)

        action = state["plannerThreads"]["essay"]["action"]
        self.assertEqual(action["kind"], "project_settings")
        self.assertEqual(action["payload"], {"projectId": "essay", "overrides": {"blockMinutes": 25},
                                             "changes": {"blockMinutes": {"from": BASE_BLOCK, "to": 25}}})
        self.assertEqual(state["projectProfiles"], {})  # nothing applies until the user confirms
        self.set_project("essay", **action["payload"]["overrides"])
        self.assertEqual(self.state()["projectProfiles"]["essay"]["overrides"]["blockMinutes"]["value"], 25)

        # A value equal to what already applies is not stored: the project keeps following the user profile there.
        self.llm.replies = {"planner_project_settings": {"reply": "좋아요", "projectSettings": {
            **said, "blockMinutes": 20, "bufferPercent": self.state()["profile"]["planningPreferences"]["bufferPercent"]}}}
        state = self.call("/api/execution/chat/message", text="20분으로 바꿀래요", consent=True, project=ESSAY)
        self.assertEqual(state["plannerThreads"]["essay"]["action"]["payload"]["overrides"], {"blockMinutes": 20})
        self.assertEqual(list(state["plannerThreads"]["essay"]["action"]["payload"]["changes"]), ["blockMinutes"])

        # Saying again what already applies makes no card; the reply says it is already set.
        self.set_project("essay", blockMinutes=20)
        state = self.call("/api/execution/chat/message", text="20분으로 바꿀래요", consent=True, project=ESSAY)
        self.assertIsNone(state["plannerThreads"]["essay"]["action"])
        self.assertIn("이미 이 프로젝트에 적용돼 있어요", state["plannerThreads"]["essay"]["messages"][-1]["content"])

        # A value that cannot work with the profile gets no card, and the reply says why.
        self.llm.replies = {"planner_project_settings": {"reply": "좋아요", "projectSettings": {
            **said, "blockMinutes": None, "starterMinutes": 40}}}
        state = self.call("/api/execution/chat/message", text="시작 행동은 40분", consent=True, project=ESSAY)
        self.assertIsNone(state["plannerThreads"]["essay"]["action"])
        self.assertIn("적용 카드를 만들지 않았어요", state["plannerThreads"]["essay"]["messages"][-1]["content"])

        # Free planning has no project to set: the turn is answered instead.
        self.llm.replies = {"planner_project_settings": {"reply": "좋아요", "projectSettings": said}}
        state = self.call("/api/execution/chat/message", text="25분씩", consent=True)
        self.assertIsNone(state["plannerThreads"]["_free"]["action"])
        self.assertEqual(state["plannerThreads"]["_free"]["messages"][-1]["skill"], "answer")


if __name__ == "__main__":
    unittest.main()
