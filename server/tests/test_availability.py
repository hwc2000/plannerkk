"""The user's fixed schedule and blocked hours are taken out of every plan by code.

Saving them moves the open tasks that now collide; nothing asks the user to
untick those hours in the weekly grid.
"""
import os
import tempfile
import unittest
from datetime import date, datetime, time
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from server.app.adaptive.local import schedule_context
from server.app.availability import busy_times
from server.app.execution_store import ExecutionStore
from server.app.main import create_app
from server.tests.test_adaptive_api import PLAIN_ANSWERS
from server.tests.test_project_independence import APP, ESSAY, FakeLLM

MONDAY = "2030-01-07"


def overlaps(entry, day, start, end):
    return entry["start"] < f"{day}T{end}" and f"{day}T{start}" < entry["end"]


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"})
class AvailabilityTests(unittest.TestCase):
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

    def plan(self, project, goal):
        draft = self.call("/api/execution/plan", goal=goal, startDate=MONDAY, consent=True, project=project, merge=True)["planDraft"]
        return self.call("/api/execution/plan/confirm", planId=draft["id"], project=draft["project"])["plan"]

    def fixed(self, *items, status=200):
        return self.call("/api/execution/fixed-schedule", status=status, method="put", items=list(items))

    def test_the_hours_to_plan_in_are_chosen_again_every_week(self):
        saved = self.client.get("/api/execution").json()
        self.assertEqual(len(saved["settings"]["slots"]), 21)
        with mock.patch("server.app.execution_store.this_week", return_value="2099-01-05"), \
                mock.patch("server.app.execution_api.this_week", return_value="2099-01-05"):
            next_week = self.client.get("/api/execution").json()
            self.assertEqual(next_week["settings"]["slots"], [])
            self.assertEqual(next_week["settings"]["view"], "timeline")
            self.call("/api/execution/settings", method="put", settings={"slots": [{"day": 0, "hour": 9}], "view": "timeline"})
            self.assertEqual(self.client.get("/api/execution").json()["settings"]["slots"], [{"day": 0, "hour": 9}])

    def test_plans_never_use_the_fixed_schedule(self):
        # Monday and Tuesday 18:00-19:30 is class; the weekly grid still has those hours ticked.
        self.fixed({"days": [0, 1], "start": "18:00", "end": "19:30"})
        week = self.plan(ESSAY, "에세이 초안")

        tasks = [e for e in week["entries"] if e["kind"] == "task"]
        self.assertTrue(tasks)
        for day in ("2030-01-07", "2030-01-08"):
            self.assertFalse([e for e in week["entries"] if overlaps(e, day, "18:00", "19:30")])
        self.assertEqual(tasks[0]["start"], "2030-01-07T19:30")

    def test_saving_the_fixed_schedule_moves_the_tasks_it_now_covers(self):
        week = self.plan(ESSAY, "에세이 초안")
        week = self.plan(APP, "로그인 화면")
        first = next(e for e in week["entries"] if e["kind"] == "task")
        day, start, end = first["start"][:10], first["start"][11:], first["end"][11:]

        state = self.fixed({"days": [date.fromisoformat(day).weekday()], "start": start, "end": end})

        self.assertEqual(state["fixedSchedule"], [{"id": "fixed-1", "days": [date.fromisoformat(day).weekday()],
                                                   "start": start, "end": end}])
        self.assertEqual(state["relocated"], {"moved": [first["title"]], "unplaced": []})
        moved = next(e for e in state["plan"]["entries"] if e["id"] == first["id"])
        self.assertEqual((moved["minutes"], moved["projectId"]), (first["minutes"], first["projectId"]))
        self.assertFalse(overlaps(moved, day, start, end))
        entries = state["plan"]["entries"]
        self.assertTrue(all(a["end"] <= b["start"] for a, b in zip(entries, entries[1:])))
        # Every other project's task stayed where it was.
        before = {e["id"]: e["start"] for e in week["entries"] if e["kind"] == "task" and e["id"] != first["id"]}
        self.assertEqual({e["id"]: e["start"] for e in entries if e["id"] in before}, before)

    def test_a_task_with_no_free_time_left_is_listed_with_the_reason(self):
        week = self.plan(ESSAY, "에세이 초안")
        # Every evening is taken now.
        state = self.fixed({"days": list(range(7)), "start": "18:00", "end": "21:00"})

        titles = [e["title"] for e in week["entries"] if e["kind"] == "task" and not e.get("starter")]
        self.assertEqual(state["relocated"]["unplaced"], titles)
        self.assertFalse([e for e in state["plan"]["entries"] if e["kind"] == "task"])
        self.assertEqual([t["title"] for t in state["plan"]["pendingTasks"][-len(titles):]], titles)
        self.assertIn("고정 일정이나 비워 둔 시간과 겹쳐", state["plan"]["pendingTasks"][-1]["reason"])

    def test_the_fixed_schedule_is_checked(self):
        self.fixed({"days": [0], "start": "19:00", "end": "18:00"}, status=422)
        self.fixed({"days": [7], "start": "09:00", "end": "10:00"}, status=422)
        response = self.client.put("/api/execution/fixed-schedule", json={"revision": self.revision, "items": [
            {"days": [0, 2], "start": "09:00", "end": "12:00"}, {"days": [2], "start": "11:00", "end": "13:00"}]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("겹치는 고정 일정", response.json()["detail"])

    def test_blocked_hours_apply_to_one_date_only(self):
        week = self.plan(ESSAY, "에세이 초안")
        monday = [e for e in week["entries"] if e["kind"] == "task" and e["start"].startswith(MONDAY)]
        self.assertTrue(monday)

        state = self.call("/api/execution/blocked-times", method="put", items=[
            {"date": MONDAY, "startHour": 18, "endHour": 21}, {"date": "2020-01-01", "startHour": 18, "endHour": 21}])

        self.assertEqual(state["blockedTimes"], [{"id": f"blocked-{MONDAY}-18-21", "date": MONDAY, "startHour": 18, "endHour": 21}])
        self.assertFalse([e for e in state["plan"]["entries"] if e["start"].startswith(MONDAY)])
        self.assertEqual(state["relocated"]["moved"], [e["title"] for e in monday if not e.get("starter")])
        # The next Monday is a normal day again.
        self.assertEqual(busy_times(state, date(2030, 1, 14)), [])

    def test_recovery_moves_avoid_the_fixed_schedule_too(self):
        week = self.plan(ESSAY, "에세이 초안")
        self.fixed({"days": [2], "start": "18:00", "end": "21:00"})
        state = self.store.read()
        task = next(e for e in state["plan"]["entries"] if e["kind"] == "task")

        context = schedule_context(state, task["id"], [], datetime(2030, 1, 7, 8, 0))

        wednesday = [w for w in context["free_windows"] if w[0].startswith("2030-01-09")]
        self.assertEqual(wednesday, [])
        self.assertTrue(context["free_windows"])
        self.assertEqual(week["startDate"], MONDAY)

    def test_busy_times_cover_each_weekday_of_the_block(self):
        state = {"fixedSchedule": [{"id": "a", "days": [0, 2], "start": "09:00", "end": "12:00"}], "blockedTimes": []}
        self.assertEqual([(b.date.isoformat(), b.startTime, b.endTime) for b in busy_times(state, date(2030, 1, 7))],
                         [("2030-01-07", time(9), time(12)), ("2030-01-09", time(9), time(12))])


if __name__ == "__main__":
    unittest.main()
