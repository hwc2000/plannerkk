"""A chat turn is routed to one skill, which reads only the saved information it needs.

The router sees the basic facts; lookups are computed by code; every card is
checked by code before the user sees it.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from server.app.execution_store import ExecutionStore
from server.app.main import create_app
from server.tests.test_adaptive_api import PLAIN_ANSWERS
from server.app.planner_skills import CARD_NOTE, CONFIRM_REPLY, NO_CARD_TO_CONFIRM
from server.tests.test_project_independence import APP, ESSAY, FakeLLM

MONDAY = "2030-01-07"


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"})
class PlannerSkillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.llm = FakeLLM()
        self.client = TestClient(create_app(execution_store=ExecutionStore(Path(self.temp.name) / "db.sqlite3"),
                                            execution_llm=self.llm))
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

    def plan(self, project, goal):
        draft = self.call("/api/execution/plan", goal=goal, startDate=MONDAY, consent=True, project=project, merge=True)["planDraft"]
        return self.call("/api/execution/plan/confirm", planId=draft["id"], project=draft["project"])["plan"]

    def say(self, text, project=ESSAY, **body):
        self.llm.chat_calls.clear()
        state = self.call("/api/execution/chat/message", text=text, consent=True, project=project, **body)
        return state, state["plannerThreads"][project["id"] if project else "_free"]

    def test_a_reply_from_the_conversation_alone_takes_one_call(self):
        _, thread = self.say("안녕하세요")

        self.assertEqual([c["name"] for c in self.llm.chat_calls], ["planner_route"])
        context = self.llm.chat_calls[0]["context"]
        # The router gets the basic facts only, never the profile or the week.
        self.assertEqual(set(context), {"today", "weekday", "project", "activeWeek", "hasAvailability", "waitingCard",
                                        "messages", "message"})
        self.assertEqual((thread["messages"][-1]["content"], thread["messages"][-1]["skill"]), ("좋아요", "small_talk"))
        self.assertEqual(thread["messages"][-1]["lookups"], [])

    def test_a_question_always_reads_the_week_and_more_only_when_asked(self):
        self.plan(ESSAY, "에세이 초안")
        self.plan(APP, "로그인 화면")
        self.call("/api/execution/fixed-schedule", method="put", items=[{"days": [2], "start": "18:00", "end": "19:00"}])
        # The router forgot to ask for anything: a question still reads this week's time and tasks.
        self.llm.route = {"skill": "answer", "lookups": [], "reply": "시간이 많이 남았어요"}

        _, thread = self.say("이번 주 수요일에 시간 남아?")

        route, answer = self.llm.chat_calls
        self.assertEqual(answer["name"], "planner_answer")
        self.assertEqual(set(answer["context"]["lookups"]), {"week", "tasks"})
        week = answer["context"]["lookups"]["week"]
        wednesday = next(d for d in week["days"] if d["date"] == "2030-01-09")
        self.assertEqual((wednesday["weekday"], wednesday["takenOutMinutes"], wednesday["availableMinutes"]), ("수", 60, 120))
        monday = week["days"][0]
        self.assertGreater(monday["thisConversationMinutes"], 0)
        self.assertEqual([p["title"] for p in monday["otherProjects"]], ["앱 개발"])
        self.assertEqual(week["weeklyHours"]["월"], ["18~21시"])
        # Other projects' totals are added by code, so the model never sums them.
        self.assertEqual(week["totals"]["otherProjects"],
                         [{"title": "앱 개발", "minutes": sum(d["otherProjects"][0]["minutes"] for d in week["days"] if d["otherProjects"])}])
        self.assertEqual(thread["messages"][-1]["lookups"], ["week", "tasks"])
        # The plan's reasons come along, so "why" is answered with what code applied.
        self.assertTrue(answer["context"]["lookups"]["tasks"]["planReasons"])

        self.llm.route = {"skill": "answer", "lookups": ["records"], "reply": None}
        self.say("어제 한 거 기록 있어?")
        records = self.llm.chat_calls[1]["context"]["lookups"]["records"]
        self.assertEqual((records["records"], records["waitingChanges"]), ([], []))

    def test_a_skill_always_reads_what_it_needs(self):
        self.plan(ESSAY, "에세이 초안")
        self.llm.route = {"skill": "plan_create", "lookups": [], "reply": None}
        self.llm.replies = {"planner_plan_create": {"reply": "정리했어요", "ready": True, "goal": "에세이 퇴고", "startDate": None}}

        _, thread = self.say("에세이 퇴고까지 계획해 줘")

        skill = self.llm.chat_calls[1]
        self.assertEqual(set(skill["context"]["lookups"]), {"week", "tasks"})
        self.assertEqual(skill["context"]["lookups"]["tasks"]["goal"], "에세이 초안")
        self.assertIn("ready=true", skill["instructions"])
        self.assertEqual(thread["action"]["payload"], {"goal": "에세이 퇴고", "startDate": MONDAY})

    def test_adjusting_without_a_week_plans_instead(self):
        self.llm.route = {"skill": "plan_adjust", "lookups": [], "reply": None}
        self.llm.replies = {"planner_plan_create": {"reply": "정리했어요", "ready": True, "goal": "에세이", "startDate": MONDAY}}

        _, thread = self.say("수요일은 빼 줘")

        self.assertEqual(self.llm.chat_calls[1]["name"], "planner_plan_create")
        self.assertEqual(thread["action"]["kind"], "plan")

    def test_an_adjustment_card_keeps_only_real_changes_to_this_week(self):
        self.plan(ESSAY, "에세이 초안")
        self.call("/api/execution/blocked-times", method="put", items=[{"date": "2030-01-08", "startHour": 18, "endHour": 21}])
        self.llm.route = {"skill": "plan_adjust", "lookups": [], "reply": None}
        self.llm.replies = {"planner_plan_adjust": {"reply": "수요일 저녁을 비울게요.", "replan": True, "goal": "에세이 초안, 분량 절반", "blockedTimes": [
            {"date": "2030-01-09", "startHour": 18, "endHour": 21},
            {"date": "2030-01-09", "startHour": 18, "endHour": 21},  # said twice
            {"date": "2030-01-08", "startHour": 18, "endHour": 21},  # already blocked
            {"date": "2030-01-20", "startHour": 18, "endHour": 21},  # not this week
        ]}}

        _, thread = self.say("수요일 저녁은 안 되고 분량도 반으로 줄여 줘")

        self.assertEqual(thread["action"]["kind"], "adjust")
        self.assertEqual(thread["action"]["payload"], {
            "blockedTimes": [{"date": "2030-01-09", "startHour": 18, "endHour": 21}],
            "goal": "에세이 초안, 분량 절반", "startDate": MONDAY})
        self.assertEqual(thread["messages"][-1]["skill"], "plan_adjust")
        # The next turn knows this card is still waiting for a click.
        _, thread = self.say("그걸로 할게요")
        self.assertEqual(self.llm.chat_calls[0]["context"]["waitingCard"]["kind"], "adjust")

        # Nothing new to change: no new card, and the one still waiting stays.
        waiting = thread["action"]
        self.llm.replies = {"planner_plan_adjust": {"reply": "이미 비워져 있어요.", "replan": False, "goal": None,
                                                    "blockedTimes": [{"date": "2030-01-08", "startHour": 18, "endHour": 21}]}}
        _, thread = self.say("화요일 저녁 빼 줘")
        self.assertEqual(thread["action"]["payload"], waiting["payload"])
        self.assertEqual(thread["messages"][-1]["content"], "이미 비워져 있어요.")

    def test_weekly_time_changes_are_worked_out_by_code(self):
        self.llm.route = {"skill": "availability", "lookups": [], "reply": None}
        monday_morning = [{"day": 0, "hour": 9}, {"day": 0, "hour": 10}]
        said = [{"day": "월", "hour": 9}, {"day": "월", "hour": 10}]
        self.llm.replies = {"planner_availability": {"reply": "월요일 오전이죠.", "change": "add", "slots": said}}
        _, thread = self.say("월요일 오전 9~11시도 추가해 줘", project=None)
        slots = thread["action"]["payload"]["slots"]
        self.assertEqual(len(slots), 21 + 2)  # the saved evenings stay
        self.assertEqual(thread["action"]["change"], {"added": monday_morning, "removed": []})
        self.assertEqual(set(self.llm.chat_calls[1]["context"]["lookups"]), {"week"})

        self.llm.replies = {"planner_availability": {"reply": "일요일 8시죠.", "change": "remove", "slots": [{"day": "일", "hour": 20}]}}
        _, thread = self.say("일요일 8시는 빼 줘", project=None)
        self.assertEqual(thread["action"]["change"], {"added": [], "removed": [{"day": 6, "hour": 20}]})
        self.assertEqual(len(thread["action"]["payload"]["slots"]), 20)

        self.llm.replies = {"planner_availability": {"reply": "월요일 오전만이죠.", "change": "replace", "slots": said}}
        _, thread = self.say("월요일 오전 9~11시로만 바꿔 줘", project=None)
        self.assertEqual(thread["action"]["payload"]["slots"], monday_morning)

        self.llm.replies = {"planner_availability": {"reply": "밤 11시죠.", "change": "add", "slots": [{"day": "월", "hour": 23}]}}
        response = self.client.post("/api/execution/chat/message", json={
            "revision": self.revision, "text": "밤 11시", "consent": True, "project": None})
        self.assertEqual(response.status_code, 400)
        self.assertIn("구체적으로", response.json()["detail"])

    def test_code_says_how_a_card_applies_and_a_question_keeps_the_card(self):
        self.plan(ESSAY, "에세이 초안")
        self.llm.route = {"skill": "plan_adjust", "lookups": [], "reply": None}
        self.llm.replies = {"planner_plan_adjust": {"reply": "수요일 저녁 6시부터 9시까지 비우는 거죠.", "replan": False,
                                                    "goal": None, "blockedTimes": [{"date": "2030-01-09", "startHour": 18, "endHour": 21}]}}
        _, thread = self.say("수요일 저녁은 안 돼")
        last = thread["messages"][-1]
        self.assertEqual(last["reply"], "수요일 저녁 6시부터 9시까지 비우는 거죠.")
        self.assertEqual(last["content"], f"{last['reply']}\n\n{CARD_NOTE}")
        card = thread["action"]

        # A question in between keeps the card waiting; it is valid for the new revision.
        self.llm.route = {"skill": "answer", "lookups": [], "reply": None}
        self.llm.replies = {"planner_answer": {"reply": "아직 확인 전이에요."}}
        state, thread = self.say("지금 적용된 거 맞지?")
        self.assertEqual({**thread["action"], "revision": card["revision"]}, card)
        self.assertEqual(thread["action"]["revision"], state["revision"])
        self.assertEqual(thread["messages"][-1]["content"], "아직 확인 전이에요.")
        # The model sees its own words, not the note code added.
        history = self.llm.chat_calls[0]["context"]["messages"]
        self.assertEqual(history[-1]["content"], "수요일 저녁 6시부터 9시까지 비우는 거죠.")

        # A different card replaces it, and code says so.
        self.llm.route = {"skill": "availability", "lookups": [], "reply": None}
        self.llm.replies = {"planner_availability": {"reply": "토요일 오전이죠.", "change": "add",
                                                     "slots": [{"day": "토", "hour": 9}]}}
        _, thread = self.say("매주 토요일 9시도 넣어 줘")
        self.assertEqual(thread["action"]["change"]["added"], [{"day": 5, "hour": 9}])
        self.assertIn("‘이번 주 계획 조정’ 제안은 이 제안으로 바뀌었어요", thread["messages"][-1]["content"])

    def test_agreeing_in_words_confirms_the_waiting_card(self):
        self.llm.route = {"skill": "confirm", "lookups": [], "reply": None}
        _, thread = self.say("응 그렇게 해 줘")
        self.assertEqual((thread["messages"][-1]["skill"], thread["action"]), ("confirm", None))
        self.assertEqual(thread["messages"][-1]["content"], NO_CARD_TO_CONFIRM)

        self.llm.route = {"skill": "project_settings", "lookups": ["profile"], "reply": None}
        self.llm.replies = {"planner_project_settings": {"reply": "한 번에 25분씩이죠.", "projectSettings": {
            "blockMinutes": 25, "dailyPlannedMinutes": None, "bufferPercent": None, "starterMinutes": None,
            "recoveryPreference": None}}}
        _, thread = self.say("이 프로젝트는 25분씩 할래")
        # The skill never reads the profile or earlier turns, so it cannot copy values the user did not say now.
        self.assertNotIn("profile", self.llm.chat_calls[1]["context"]["lookups"])
        self.assertTrue(self.llm.chat_calls[0]["context"]["messages"])
        self.assertEqual(self.llm.chat_calls[1]["context"]["messages"], [])
        card = thread["action"]

        self.llm.route = {"skill": "confirm", "lookups": [], "reply": None}
        state, thread = self.say("응 그렇게 해 줘")
        # One call: code answers and keeps the card for the screen to apply with the button's own action.
        self.assertEqual([c["name"] for c in self.llm.chat_calls], ["planner_route"])
        self.assertEqual((thread["messages"][-1]["skill"], thread["messages"][-1]["content"]), ("confirm", CONFIRM_REPLY))
        self.assertEqual(thread["action"]["payload"], card["payload"])
        self.assertEqual(thread["action"]["revision"], state["revision"])

    def test_the_profile_lookup_names_where_each_value_came_from(self):
        self.call("/api/execution/projects/essay/profile", method="put", overrides={"dailyPlannedMinutes": 90})
        self.llm.route = {"skill": "answer", "lookups": ["profile"], "reply": None}

        self.say("왜 이렇게 계획해?")

        profile = self.llm.chat_calls[1]["context"]["lookups"]["profile"]
        daily = next(s for s in profile["settings"] if s["name"] == "하루에 계획할 최대 시간")
        self.assertEqual((daily["value"], daily["source"]), ("90분", "이 프로젝트에서 사용자가 정함"))
        self.assertEqual(profile["traits"]["생활 형태"], ["학생", "직장인"])
        self.assertEqual(profile["traits"]["집중이 잘 되는 시간대"], "저녁 (예전 설문 답)")


if __name__ == "__main__":
    unittest.main()
