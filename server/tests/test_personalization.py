import itertools
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from server.app.adaptive import build_adaptive_planner_graph
from server.app.adaptive.personalization import (
    PlanPolicy,
    day_slots,
    personalization_reasons,
    place_tasks,
    plan_policy,
    preferred_windows,
)
from server.app.adaptive.ports import PlanValidationError
from server.app.adaptive.state import default_strategy
from server.app.execution_profile import OPTIONS, generate_profile
from server.app.execution_scheduler import schedule
from server.app.execution_store import ExecutionStore
from server.app.main import create_app

GOAL = "이번 주까지 발표 자료 초안을 완성하고 발표 연습을 한다."
SECRET = "비공개-메모-7731"
USER_A = {"roles": ["student"], "regularity": "regular", "barriers": ["none"], "focusMinutes": 50,
          "dailyMinutes": 120, "energy": "morning", "recovery": "replan", "constraints": SECRET, "context": SECRET}
USER_B = {"roles": ["student"], "regularity": "irregular", "barriers": ["starting"], "focusMinutes": 20,
          "dailyMinutes": 120, "energy": "variable", "recovery": "reduce", "constraints": SECRET, "context": SECRET}


def user_profile(answers, **prefs):
    """The userProfile part of A's planning context (free-text notes are dropped there)."""
    profile = generate_profile(answers)
    facts = {k: v for k, v in profile["facts"].items() if k not in ("constraints", "context")}
    return {"declaredFacts": facts, "planningPreferences": {**profile["planningPreferences"], **prefs},
            "learnedPatterns": []}


def task(title, minutes, starter=""):
    return {"title": title, "minutes": minutes, "doneWhen": "끝냄", "dueDate": None, "starter": starter}


def windows(*spans):
    return [(datetime.fromisoformat(a), datetime.fromisoformat(b)) for a, b in spans]


def by_key(reasons):
    return {reason["key"]: reason for reason in reasons}


class SchedulerTests(unittest.TestCase):
    def test_daily_cap_and_one_starter_per_day(self):
        week = windows(("2030-01-07T09:00", "2030-01-07T12:00"), ("2030-01-08T09:00", "2030-01-08T12:00"))
        tasks = [task(f"작업 {i}", 20, starter=f"작업 {i} 파일 열기" if i else "") for i in range(5)]
        entries, pending = schedule(tasks, week, daily_cap=50, starter_minutes=5)
        work = [e for e in entries if e["kind"] == "task"]
        for day in ("2030-01-07", "2030-01-08"):
            today = [e for e in work if e["start"].startswith(day)]
            self.assertTrue(today[0]["starter"])
            self.assertEqual(sum(e.get("starter", False) for e in today), 1)
            self.assertLessEqual(sum(e["minutes"] for e in today), 50)
        self.assertEqual(work[0]["title"], "시작 행동: 작업 0 자료를 열고 첫 단계만 해 보기")  # empty -> generic
        self.assertEqual(work[0]["end"], work[1]["start"])  # the starter leads straight into the task
        self.assertNotIn("starter", work[1])  # LLM starter text never leaks into a task entry
        self.assertEqual(len(pending), 1)
        self.assertIn("하루 계획량 50분", pending[0]["reason"])

    def test_pending_reason_names_the_cap_only_when_it_binds(self):
        tight = windows(("2030-01-07T09:00", "2030-01-07T10:00"))
        _, pending = schedule([task("A", 40), task("B", 40)], tight, daily_cap=90)
        self.assertNotIn("하루 계획량", pending[0]["reason"])  # the hour itself binds, not the 90-minute cap

    def test_all_the_chosen_time_is_planned(self):
        # Three free hours, one-hour blocks: two blocks and the 50 minutes left, with breaks between.
        evening = windows(("2030-01-07T19:00", "2030-01-07T22:00"))
        self.assertEqual(day_slots(evening, PlanPolicy(60, None, None, None), 60), [{"date": "2030-01-07", "minutes": [60, 60, 50]}])
        entries, pending = schedule([task("A", 60), task("B", 60), task("복습", 50)], evening)
        self.assertEqual(pending, [])
        self.assertEqual([(e["start"][11:], e["end"][11:]) for e in entries if e["kind"] == "task"],
                         [("19:00", "20:00"), ("20:05", "21:05"), ("21:10", "22:00")])

    def test_day_slots_share_a_short_end_and_follow_the_starter_and_cap(self):
        def slots(span, policy, block):
            return day_slots(windows(span), policy, block)[0]["minutes"]
        self.assertEqual(slots(("2030-01-07T19:00", "2030-01-07T21:00"), PlanPolicy(50, None, None, None), 50), [50, 30, 30])
        self.assertEqual(slots(("2030-01-07T19:00", "2030-01-07T22:00"), PlanPolicy(60, None, 5, None), 60), [60, 60, 45])
        self.assertEqual(slots(("2030-01-07T19:00", "2030-01-07T22:00"), PlanPolicy(60, 90, None, None), 60), [60, 30])
        self.assertEqual(day_slots(windows(("2030-01-07T19:00", "2030-01-07T19:05")), PlanPolicy(60, None, None, None), 60), [])

    def test_without_policy_values_the_schedule_is_unchanged(self):
        week = windows(("2030-01-07T09:00", "2030-01-07T12:00"))
        entries, pending = schedule([task("작업", 30)], week)
        self.assertEqual([e["kind"] for e in entries], ["task", "break"])
        self.assertFalse(any(e.get("starter") for e in entries))
        self.assertEqual(pending, [])

    def test_preferred_period_is_used_when_it_fits(self):
        week = windows(("2030-01-07T09:00", "2030-01-07T11:00"), ("2030-01-07T19:00", "2030-01-07T21:00"),
                       ("2030-01-08T09:00", "2030-01-08T11:00"), ("2030-01-08T19:00", "2030-01-08T21:00"))
        policy = PlanPolicy(block_minutes=50, daily_cap_minutes=90, starter_minutes=None, preferred_period="morning")
        entries, pending, placement = place_tasks([task("A", 50), task("B", 40)], week, policy)
        self.assertEqual(placement, "preferred")
        self.assertTrue(all(e["start"][11:13] < "12" for e in entries))
        evening = PlanPolicy(**{**policy.__dict__, "preferred_period": "evening"})
        entries, _, placement = place_tasks([task("A", 50), task("B", 40)], week, evening)
        self.assertEqual(placement, "preferred")
        self.assertTrue(all(e["start"][11:13] >= "18" for e in entries))

    def test_preferred_period_falls_back_without_losing_tasks(self):
        week = windows(("2030-01-07T11:00", "2030-01-07T12:00"), ("2030-01-07T19:00", "2030-01-07T22:00"))
        policy = PlanPolicy(50, None, None, "morning")
        entries, pending, placement = place_tasks([task("A", 50), task("B", 50)], week, policy)
        self.assertEqual((placement, pending), ("mixed", []))
        _, _, placement = place_tasks([task("A", 50)], windows(("2030-01-07T19:00", "2030-01-07T21:00")), policy)
        self.assertEqual(placement, "unavailable")
        self.assertEqual(preferred_windows(windows(("2030-01-07T11:00", "2030-01-07T13:00")), "morning"),
                         windows(("2030-01-07T11:00", "2030-01-07T12:00")))


class ReasonTests(unittest.TestCase):
    def test_same_goal_two_users_get_their_own_reasons(self):
        a = by_key(personalization_reasons(user_profile(USER_A), placement="preferred", starter_used=False))
        b = by_key(personalization_reasons(user_profile(USER_B), placement=None, starter_used=True))
        self.assertIn("50분", a["taskLength"]["applied"])
        self.assertEqual((a["taskLength"]["source"], a["taskLength"]["fields"]), ("declared", ["focusMinutes"]))
        self.assertIn("집중 가능 시간 50분", a["taskLength"]["because"])
        self.assertNotIn("buffer", a)  # all the chosen time is planned; nothing is held back
        self.assertIn("오전", a["period"]["applied"])
        self.assertIn("다시 잡는", a["recovery"]["applied"])
        self.assertNotIn("starter", a)

        self.assertIn("20분", b["taskLength"]["applied"])
        self.assertIn("집중 가능 시간 20분", b["taskLength"]["because"])
        self.assertIn("5분", b["starter"]["applied"])
        self.assertIn("120분", b["dailyCap"]["applied"])
        self.assertIn("줄이는", b["recovery"]["applied"])
        self.assertIn("할 일 목록", b["scheduleStyle"]["applied"])
        self.assertNotIn("period", b)

    def test_every_survey_combination_is_explained_by_its_own_values(self):
        barrier_sets = [["none"], ["unknown"], ["starting"], ["overplanning"], ["distraction"],
                        ["starting", "overplanning", "distraction"]]
        combos = itertools.product(OPTIONS["regularity"], barrier_sets, (None, 20, 50, 90), (None, 30, 120),
                                   OPTIONS["energy"], OPTIONS["recovery"], ("unknown", "time_blocks", "flexible_queue"))
        for regularity, barriers, focus, daily, energy, recovery, style in combos:
            answers = {"roles": ["student"], "regularity": regularity, "barriers": barriers, "focusMinutes": focus,
                       "dailyMinutes": daily, "energy": energy, "recovery": recovery, "scheduleStyle": style,
                       "constraints": SECRET, "context": SECRET}
            profile = user_profile(answers)
            prefs = profile["planningPreferences"]
            placement = "preferred" if energy in ("morning", "afternoon", "evening") else None
            reasons = personalization_reasons(profile, placement=placement, starter_used=True)
            keyed = by_key(reasons)
            text = " ".join(f"{r['applied']} {r['because']}" for r in reasons)
            with self.subTest(answers=answers):
                self.assertNotIn(SECRET, text)
                self.assertTrue(all(r["source"] in ("declared", "default") for r in reasons))
                self.assertIn(f"{prefs['blockMinutes']}분", keyed["taskLength"]["applied"])
                self.assertEqual(keyed["taskLength"]["source"], "default" if focus is None else "declared")
                if focus is not None:
                    self.assertIn(f"{focus}분", keyed["taskLength"]["because"])
                self.assertEqual("starter" in keyed, prefs["starterMinutes"] is not None)
                self.assertEqual("dailyCap" in keyed, daily is not None)
                if daily is not None:
                    self.assertIn(f"{prefs['dailyPlannedMinutes']}분", keyed["dailyCap"]["applied"])
                self.assertEqual("period" in keyed, placement is not None)
                self.assertEqual("recovery" in keyed, recovery in ("reduce", "replan"))

    def test_values_set_outside_the_survey_are_not_explained_by_answers(self):
        edited = user_profile(USER_B, blockMinutes=15, dailyPlannedMinutes=100)
        reasons = by_key(personalization_reasons(edited, placement=None, starter_used=False))
        self.assertEqual((reasons["taskLength"]["source"], reasons["dailyCap"]["source"]), ("profile", "profile"))

    def test_learned_change_names_its_evidence(self):
        profile = user_profile(USER_A, blockMinutes=20)
        profile["learnedPatterns"] = [{"proposedChanges": {"blockMinutes": {"from": 50, "to": 20}},
                                       "evidenceRecordIds": ["r1", "r2", "r3"]}]
        reason = by_key(personalization_reasons(profile, placement=None, starter_used=False))["taskLength"]
        self.assertEqual(reason["source"], "learned")
        self.assertIn("실행 기록 3건", reason["because"])
        self.assertIn("50분 → 20분", reason["because"])

    def test_policy_reads_only_the_users_profile(self):
        self.assertEqual(plan_policy(user_profile(USER_A)), PlanPolicy(50, 120, None, "morning"))
        self.assertEqual(plan_policy(user_profile(USER_B)), PlanPolicy(20, 120, 5, None))


class StrategyTests(unittest.TestCase):
    def test_recovery_preference_picks_strategy_for_circumstances_only(self):
        for reason in ("time_shortage", "fatigue", "interruption", "underestimated", "other"):
            self.assertEqual(default_strategy(reason, "reduce"), "shrink")
            self.assertEqual(default_strategy(reason, "replan"), "reschedule")
        for preference in ("reduce", "replan", "continue", None):
            self.assertEqual(default_strategy("task_too_large", preference), "shrink")
            self.assertEqual(default_strategy("unclear_task", preference), "shrink")
            self.assertEqual(default_strategy("priority_changed", preference), "replan")
        self.assertEqual(default_strategy("time_shortage", "continue"), "reschedule")
        self.assertIsNone(default_strategy("other", "unknown"))

    def test_graph_uses_the_users_preference(self):
        state = {
            "request": "recovery",
            "execution_context": {"schedule_style": "time_blocks", "focus_minutes": 20, "recovery_preference": "reduce"},
            "current_task": {"id": "t", "title": "발표 자료 초안", "minutes": 60, "done_when": "초안 완성"},
            "check_in": {"completed": False, "actual_minutes": 20, "reason_code": "time_shortage", "note": ""},
            "schedule_context": {"now": "2030-01-07T09:00", "free_windows": [["2030-01-07T18:00", "2030-01-07T21:00"]],
                                 "deadline": None, "deadline_within_plan": False},
        }
        graph = build_adaptive_planner_graph(lambda _state: {"kind": "shrink", "tasks": []})
        self.assertEqual(graph.invoke(state)["strategy"], "shrink")
        state["execution_context"]["recovery_preference"] = "replan"
        self.assertEqual(graph.invoke(state)["strategy"], "reschedule")


class FullPlanRetryTests(unittest.TestCase):
    def run_graph(self, failures, max_retries=2):
        seen = []

        def generator(state):
            seen.append(list(state.get("validation_errors") or []))
            if len(seen) <= failures:
                raise PlanValidationError([f"규칙 위반 {len(seen)}"])
            return {"id": "draft", "profileId": "profile", "entries": []}

        result = build_adaptive_planner_graph(lambda _state: {}, full_plan_generator=generator,
                                              max_retries=max_retries).invoke(
            {"request": "new_plan", "planning_context": {"goal": "발표 준비"}})
        return result, seen

    def test_validation_failure_is_retried_with_its_errors(self):
        result, seen = self.run_graph(failures=2)
        self.assertEqual(result["approval_status"], "waiting")
        self.assertEqual(result["retry_count"], 2)
        self.assertEqual(seen, [[], ["규칙 위반 1"], ["규칙 위반 2"]])

    def test_retries_are_bounded_and_keep_the_current_plan(self):
        result, seen = self.run_graph(failures=10)
        self.assertEqual(len(seen), 3)
        self.assertIsNone(result["plan_draft"])
        self.assertEqual(result["fallback"]["action"], "keep_current_plan")
        self.assertEqual(result["fallback"]["validation_errors"], ["규칙 위반 3"])
        result, seen = self.run_graph(failures=10, max_retries=0)
        self.assertEqual(len(seen), 1)


class PlanLLM:
    """Answers the weekly-plan call like a well-behaved LLM: tasks at the cap, with starters."""

    def __init__(self):
        self.calls = []

    async def generate(self, **kwargs):
        if kwargs["name"] == "execution_profile":
            return generate_profile(USER_A)["insights"]
        self.calls.append(kwargs)
        context = kwargs["context"]
        task = {"title": "발표 자료 작업", "minutes": context["maxBlockMinutes"], "doneWhen": "한 부분 완성", "dueDate": None}
        if context["starterMinutes"]:
            task["starter"] = "발표 자료 파일을 열고 제목 슬라이드만 만들기"
        return {"tasks": [dict(task, title=f"발표 자료 작업 {i}") for i in range(8)]}


class OverflowLLM(PlanLLM):
    """Returns more work than fits for the first ``overflows`` calls."""

    def __init__(self, overflows):
        super().__init__()
        self.overflows = overflows

    async def generate(self, **kwargs):
        reply = await super().generate(**kwargs)
        if kwargs["name"] == "execution_tasks":
            reply["tasks"] = (reply["tasks"] * 5)[:40] if len(self.calls) <= self.overflows else reply["tasks"][:2]
        return reply


class DeadlineLLM(PlanLLM):
    """Puts a task due on the first day last, until a retry names its deadline; then keeps it first."""

    told = False

    async def generate(self, **kwargs):
        reply = await super().generate(**kwargs)
        if kwargs["name"] == "execution_tasks":
            due = {"title": "발표 연습", "minutes": 40, "doneWhen": "처음부터 끝까지 한 번", "dueDate": "2030-01-07"}
            others = [{"title": f"자료 {i}장", "minutes": 40, "doneWhen": "초안 완성", "dueDate": None} for i in range(3)]
            self.told = self.told or any("'발표 연습'(마감 2030-01-07)" in e for e in kwargs["context"].get("previousErrors", []))
            reply["tasks"] = [due, *others] if self.told else [*others, due]
        return reply


class TooLongLLM(PlanLLM):
    """Copies a 2-hour existing task as one 120-minute task until the retry names it."""

    async def generate(self, **kwargs):
        reply = await super().generate(**kwargs)
        if kwargs["name"] == "execution_tasks":
            errors = kwargs["context"].get("previousErrors", [])
            told = any("'화면 흐름 검토' 120분은 작업당 최대 50분을 넘습니다" in e for e in errors)
            reply["tasks"] = ([{"title": f"화면 흐름 검토 {i}", "minutes": 40, "doneWhen": "절반 검토", "dueDate": None} for i in (1, 2)]
                              if told else [{"title": "화면 흐름 검토", "minutes": 120, "doneWhen": "검토 완료", "dueDate": None}])
        return reply


class TimedDoneWhenLLM(PlanLLM):
    """Writes the start time as the completion condition for the first ``times`` calls."""

    def __init__(self, times):
        super().__init__()
        self.times = times

    async def generate(self, **kwargs):
        reply = await super().generate(**kwargs)
        if kwargs["name"] == "execution_tasks" and len(self.calls) <= self.times:
            for i, task in enumerate(reply["tasks"]):
                task["doneWhen"] = f"2030-01-07T{9 + i:02d}:00"
        return reply


class ShortTasksLLM(PlanLLM):
    """Cuts the work into 10-minute slivers for the first ``times`` calls."""

    def __init__(self, times):
        super().__init__()
        self.times = times

    async def generate(self, **kwargs):
        reply = await super().generate(**kwargs)
        if kwargs["name"] == "execution_tasks" and len(self.calls) <= self.times:
            reply["tasks"] = [{"title": f"자료 {i} 찾기", "minutes": 10, "doneWhen": f"자료 {i} 링크 저장", "dueDate": None}
                              for i in range(1, 7)]
        return reply


class TwoUsersApiTests(unittest.TestCase):
    """Same goal, same free time, different users -> different plans and reasons."""

    def plan_for(self, answers, llm=None):
        llm = llm or PlanLLM()
        with tempfile.TemporaryDirectory() as temp, TestClient(create_app(
                execution_store=ExecutionStore(Path(temp) / "db.sqlite3"), execution_llm=llm)) as client:
            state = client.get("/api/execution").json()

            def post(path, **body):
                nonlocal state
                response = client.post(f"/api/execution{path}", json={"revision": state["revision"], **body})
                self.assertEqual(response.status_code, 200, response.text)
                state = response.json()

            post("/profile", answers=answers)
            post("/profile/confirm")
            slots = [{"day": d, "hour": h} for d in range(5) for h in (9, 10, 19, 20)]
            state = client.put("/api/execution/settings", json={"revision": state["revision"],
                               "settings": {"slots": slots, "view": "timeline"}}).json()
            post("/plan", goal=GOAL, startDate="2030-01-07", consent=True)
            draft = state["planDraft"]
            post("/plan/confirm", planId=draft["id"])
            self.assertEqual(state["plan"]["personalization"], draft["personalization"])
            return draft, llm.calls[-1]

    def test_overflow_is_asked_again_with_numbers(self):
        llm = OverflowLLM(overflows=1)
        draft, last = self.plan_for(USER_B, llm)
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(draft["pendingTasks"], [])
        self.assertIn("하루 최대 120분", last["context"]["previousErrors"][0])
        self.assertNotIn("previousErrors", llm.calls[0]["context"])

    def test_a_completion_condition_is_a_result_not_a_time(self):
        llm = TimedDoneWhenLLM(times=1)
        draft, _ = self.plan_for(USER_A, llm)
        self.assertNotIn("previousErrors", llm.calls[0]["context"])
        self.assertIn("doneWhen에 날짜·시각('2030-01-07T09:00')을 썼습니다", llm.calls[1]["context"]["previousErrors"][0])
        self.assertEqual({e["doneWhen"] for e in draft["entries"] if e["kind"] == "task"}, {"한 부분 완성"})

        # Out of retries, the plan still comes, with a plain condition instead of a time.
        llm = TimedDoneWhenLLM(times=10)
        draft, _ = self.plan_for(USER_A, llm)
        tasks = [e for e in draft["entries"] if e["kind"] == "task"]
        self.assertTrue(tasks)
        self.assertTrue(all(e["doneWhen"] == f"‘{e['title']}’ 마치기" for e in tasks))

    def test_work_is_not_cut_into_slivers(self):
        llm = ShortTasksLLM(times=1)
        draft, _ = self.plan_for(USER_A, llm)
        self.assertIn("짧습니다", llm.calls[1]["context"]["previousErrors"][0])
        self.assertEqual(llm.calls[0]["context"]["minTaskMinutes"], 25)
        self.assertTrue(all(e["minutes"] >= 25 for e in draft["entries"] if e["kind"] == "task" and not e.get("starter")))

        # Out of retries, neighbouring slivers are joined up to the focus block; one short wrap-up may stay.
        llm = ShortTasksLLM(times=10)
        draft, _ = self.plan_for(USER_A, llm)
        tasks = [e for e in draft["entries"] if e["kind"] == "task" and not e.get("starter")]
        self.assertEqual([e["minutes"] for e in tasks], [50, 10])
        self.assertEqual(tasks[0]["title"], "자료 1 찾기 · 자료 2 찾기 · 자료 3 찾기 · 자료 4 찾기 · 자료 5 찾기")

    def test_a_task_over_the_focus_block_is_named_in_the_retry(self):
        llm = TooLongLLM()
        draft, last = self.plan_for(USER_A, llm)
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(last["context"]["previousErrors"],
                         ["'화면 흐름 검토' 120분은 작업당 최대 50분을 넘습니다. 50분 이하 작업 여러 개로 나누세요."])
        self.assertEqual([e["minutes"] for e in draft["entries"] if e["kind"] == "task"], [40, 40])

    def test_a_deadline_task_left_out_is_named_in_the_retry(self):
        llm = DeadlineLLM()
        draft, _ = self.plan_for(USER_A, llm)
        self.assertIn("'발표 연습'(마감 2030-01-07)은 마감 전에 들어갈 자리가 없었습니다", llm.calls[1]["context"]["previousErrors"][1])
        self.assertEqual(draft["pendingTasks"], [])
        placed = next(e for e in draft["entries"] if e["title"] == "발표 연습")
        self.assertEqual(placed["start"][:10], "2030-01-07")

    def test_overflow_on_the_last_attempt_keeps_the_plan_with_pending_tasks(self):
        llm = OverflowLLM(overflows=10)
        draft, _ = self.plan_for(USER_B, llm)
        self.assertEqual(len(llm.calls), 3)  # first try + max_retries (2)
        self.assertTrue(draft["pendingTasks"])
        self.assertTrue(any(e["kind"] == "task" for e in draft["entries"]))

    def test_demo_users_get_different_plans(self):
        a, a_call = self.plan_for(USER_A)
        b, b_call = self.plan_for(USER_B)
        a_tasks = [e for e in a["entries"] if e["kind"] == "task"]
        b_tasks = [e for e in b["entries"] if e["kind"] == "task" and not e.get("starter")]
        b_starters = [e for e in b["entries"] if e.get("starter")]

        self.assertEqual({e["minutes"] for e in a_tasks}, {50})
        self.assertTrue(all(e["start"][11:13] < "12" for e in a_tasks))
        self.assertFalse(any(e.get("starter") for e in a["entries"]))
        self.assertTrue(b_tasks and all(e["minutes"] <= 20 for e in b_tasks))
        self.assertTrue(b_starters and all(e["minutes"] == 5 for e in b_starters))
        for day in {e["start"][:10] for e in b_tasks}:
            self.assertLessEqual(sum(e["minutes"] for e in b["entries"] if e["kind"] == "task" and e["start"].startswith(day)), 120)
        self.assertLess(sum(e["minutes"] for e in b_tasks), sum(e["minutes"] for e in a_tasks))

        self.assertEqual((a_call["context"]["maxBlockMinutes"], a_call["context"]["starterMinutes"]), (50, None))
        self.assertEqual((b_call["context"]["maxBlockMinutes"], b_call["context"]["starterMinutes"]), (20, 5))
        self.assertIn("starter", b_call["schema"]["properties"]["tasks"]["items"]["properties"])
        self.assertNotIn("starter", a_call["schema"]["properties"]["tasks"]["items"]["properties"])

        a_reasons, b_reasons = by_key(a["personalization"]), by_key(b["personalization"])
        self.assertEqual(set(a_reasons) - set(b_reasons), {"period"})
        self.assertEqual(set(b_reasons) - set(a_reasons), {"starter"})
        self.assertNotIn(SECRET, str(a["personalization"]) + str(b["personalization"]))
        self.assertNotIn(SECRET, str(a_call["context"]) + str(b_call["context"]))



class FillTheDayLLM(PlanLLM):
    """Sizes every task to the focus block first; after the retry, fits each day's slots."""

    async def generate(self, **kwargs):
        if kwargs["name"] != "execution_tasks":
            return await super().generate(**kwargs)
        self.calls.append(kwargs)
        context = kwargs["context"]
        if context.get("previousErrors"):
            sizes = [m for day in context["daySlots"] for m in day["minutes"]][:4]
        else:
            sizes = [context["maxBlockMinutes"]] * 4
        return {"tasks": [{"title": f"보고서 {i}", "minutes": m, "doneWhen": "한 부분 완성", "dueDate": None}
                          for i, m in enumerate(sizes, 1)]}


class FillTheDayTests(unittest.TestCase):
    """The time the user chose is used: a day is full before work moves to the next one."""

    def test_a_day_is_filled_before_the_next(self):
        answers = {**USER_A, "focusMinutes": 60, "dailyMinutes": None, "energy": "unknown"}
        llm = FillTheDayLLM()
        with tempfile.TemporaryDirectory() as temp, TestClient(create_app(
                execution_store=ExecutionStore(Path(temp) / "db.sqlite3"), execution_llm=llm)) as client:
            state = client.get("/api/execution").json()

            def post(path, method="post", **body):
                nonlocal state
                response = getattr(client, method)(f"/api/execution{path}", json={"revision": state["revision"], **body})
                self.assertEqual(response.status_code, 200, response.text)
                state = response.json()

            post("/profile", answers=answers)
            post("/profile/confirm")
            post("/settings", method="put", settings={"slots": [{"day": d, "hour": h} for d in (0, 1) for h in (19, 20, 21)],
                                                      "view": "timeline"})
            post("/plan", goal=GOAL, startDate="2030-01-07", consent=True)

        first, retry = llm.calls
        self.assertEqual(first["context"]["daySlots"][0], {"date": "2030-01-07", "minutes": [60, 60, 50]})
        self.assertEqual(first["context"]["budgetMinutes"], 340)
        self.assertIn("1/7(월)에 50분이 비었는데 다음 작업 '보고서 3'(60분)", retry["context"]["previousErrors"][0])
        monday = [(e["start"][11:], e["minutes"]) for e in state["planDraft"]["entries"]
                  if e["kind"] == "task" and e["start"].startswith("2030-01-07")]
        self.assertEqual(monday, [("19:00", 60), ("20:05", 60), ("21:10", 50)])


if __name__ == "__main__":
    unittest.main()
