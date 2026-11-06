"""The learning rules added after the check-in experiment (sim/): each proposes from the user's own records.

- a waiting proposal made for settings that changed since is closed, not left un-approvable;
- a longer block needs most of what was planned since the last change to be finished;
- a longer block that made things worse is proposed back;
- a daily plan, how long work really takes, and a short part of the day are learned;
- a miss after a day's worth of work does not count against the hour it was in.
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from uuid import uuid4

from fastapi.testclient import TestClient

from server.app.adaptive.personalization import period_odds, pick_windows_for_cap, shape_windows
from server.app.execution_store import ExecutionStore
from server.app.main import create_app

ANSWERS = {"roles": ["student"], "regularity": "regular", "barriers": ["none"], "focusMinutes": 60, "dailyMinutes": None,
           "energy": "unknown", "recovery": "replan", "constraints": "", "context": "", "scheduleStyle": "time_blocks"}


class FillLLM:
    """Fills every slot the planner offers, one task per slot."""

    async def generate(self, **kwargs):
        if kwargs["name"].startswith("planner_"):
            return {}
        return {"tasks": [{"title": f"공부 {i}", "minutes": minutes, "doneWhen": "정리 저장", "dueDate": None}
                          for i, minutes in enumerate(m for day in kwargs["context"]["daySlots"] for m in day["minutes"])]}


@mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"})
class LearningRuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ExecutionStore(Path(self.temp.name) / "db.sqlite3")
        self.client = TestClient(create_app(execution_store=self.store, execution_llm=FillLLM()))
        self.revision = self.client.get("/api/execution").json()["revision"]
        self.call("/api/execution/profile", answers=ANSWERS)
        self.call("/api/execution/profile/confirm")

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

    def put_plan(self, tasks, project=None):
        """A confirmed week of (start, minutes) tasks, made with the current profile (and project settings)."""
        state = self.store.read()
        profile = state["profile"]
        project_profile_id = ((state.get("projectProfiles") or {}).get(project) or {}).get("id")
        entries = [{"id": str(uuid4()), "kind": "task", "title": f"공부 {i + 1}", "minutes": minutes, "doneWhen": "정리",
                    "dueDate": None, "start": start, "completed": False, "projectId": project,
                    "projectProfileId": project_profile_id,
                    "end": (datetime.fromisoformat(start) + timedelta(minutes=minutes)).isoformat(timespec="minutes")}
                   for i, (start, minutes) in enumerate(tasks)]
        context = {"id": project, "title": "공부", "goal": "공부", "startDate": "2030-01-01", "dueDate": "2030-03-31"} if project else None
        plan = {"id": str(uuid4()), "profileId": profile["id"], "profileVersion": profile["version"], "projectId": project,
                "project": context, "goal": "공부", "startDate": "2030-01-07", "endDate": "2030-01-13", "timezone": "Asia/Seoul",
                "status": "confirmed", "slots": [], "entries": entries, "pendingTasks": []}
        self.revision = self.store.change(self.revision, lambda state: state.update(plan=plan))["revision"]
        return plan["id"], entries

    def record(self, plan_id, task, result, actual=None, reason=None):
        body = {"planId": plan_id, "taskId": task["id"], "result": result, "actualMinutes": actual, "reasonCode": reason}
        if result == "partial":
            body["remainingMinutes"] = max(0, task["minutes"] - (actual or 0))
        return self.call("/api/execution/records", **body)

    def proposals(self, state, key, status="pending"):
        return [p for p in state["profileUpdateProposals"] if key in p["proposedChanges"] and p["status"] == status]

    def day(self, d, hour, minute=0):
        return f"2030-01-{d:02}T{hour:02}:{minute:02}"

    def test_a_waiting_proposal_for_replaced_settings_is_closed(self):
        days = (7, 8, 9)
        plan_id, entries = self.put_plan([(self.day(d, h, m), n) for d in days for h, m, n in ((9, 0, 30), (10, 5, 55), (19, 0, 60))])
        for i in range(0, 9, 3):
            self.record(plan_id, entries[i], "completed", 30)
        for i in range(0, 9, 3):
            self.record(plan_id, entries[i + 1], "partial", 10, "time_shortage")
            state = self.record(plan_id, entries[i + 2], "partial", 10, "time_shortage")
        [block] = self.proposals(state, "blockMinutes")
        [cap] = self.proposals(state, "dailyPlannedMinutes")
        state = self.call(f"/api/execution/proposals/{cap['id']}/approve")
        closed = next(p for p in state["profileUpdateProposals"] if p["id"] == block["id"])
        self.assertEqual((closed["status"], closed["closedBy"]), ("rejected", "settings_changed"))

    def test_growing_needs_most_work_since_the_last_change_finished(self):
        plan_id, entries = self.put_plan([(self.day(d, 9), 60) for d in range(7, 14)])
        for task in entries[:3]:
            self.record(plan_id, task, "partial", 30, "fatigue")
        for task in entries[3:]:
            state = self.record(plan_id, task, "completed", 60)
        self.assertEqual(self.proposals(state, "blockMinutes"), [])

    def test_finishing_tasks_alone_never_makes_them_longer(self):
        plan_id, entries = self.put_plan([(self.day(d, 9), 60) for d in range(7, 14)])
        for task in entries:
            state = self.record(plan_id, task, "completed", 60)
        self.assertEqual(self.proposals(state, "blockMinutes"), [])

    def feedback(self, time_fit):
        return self.call("/api/execution/projects/p1/feedback", load="right", timeFit=time_fit)

    def test_two_weekly_feedbacks_ask_for_longer_or_shorter_tasks(self):
        plan_id, entries = self.put_plan([(self.day(d, 9), 60) for d in range(7, 10)], project="p1")
        for task in entries:
            self.record(plan_id, task, "completed", 60)
        self.feedback("too_short")
        self.assertEqual(self.proposals(self.store.read(), "blockMinutes"), [])  # once is not yet a request
        [grow] = self.proposals(self.feedback("too_short"), "blockMinutes")
        self.assertEqual((grow["ruleVersion"], grow["proposedChanges"]["blockMinutes"]), ("feedback-size-v1", {"from": 60, "to": 70}))
        self.call(f"/api/execution/proposals/{grow['id']}/reject")
        self.feedback("too_long")
        [shrink] = self.proposals(self.feedback("too_long"), "blockMinutes")
        self.assertEqual(shrink["proposedChanges"]["blockMinutes"], {"from": 60, "to": 50})

    def test_time_too_short_with_work_running_long_is_about_pace_not_length(self):
        plan_id, entries = self.put_plan([(self.day(d, 9), 60) for d in range(7, 10)], project="p1")
        for task in entries:
            self.record(plan_id, task, "completed", 80)
        self.feedback("too_short")
        self.assertEqual(self.proposals(self.feedback("too_short"), "blockMinutes"), [])

    def test_a_longer_block_that_made_things_worse_goes_back(self):
        plan_id, entries = self.put_plan([(self.day(d, 9), 60) for d in range(7, 10)], project="p1")
        for task in entries:
            self.record(plan_id, task, "completed", 60)
        self.feedback("too_short")
        [grow] = self.proposals(self.feedback("too_short"), "blockMinutes")
        self.call(f"/api/execution/proposals/{grow['id']}/approve")
        plan_id, entries = self.put_plan([(self.day(d, 9), 70) for d in range(7, 11)], project="p1")
        self.record(plan_id, entries[0], "completed", 70)
        for task in entries[1:]:
            state = self.record(plan_id, task, "partial", 60, "fatigue")
        [back] = self.proposals(state, "blockMinutes")
        self.assertEqual((back["ruleVersion"], back["proposedChanges"]["blockMinutes"]), ("grow-revert-v1", {"from": 70, "to": 60}))
        self.assertEqual(back["projectId"], "p1")

    def test_a_daily_plan_the_user_gets_through(self):
        plan_id, entries = self.put_plan([(self.day(d, h, m), n) for d in (7, 8, 9)
                                          for h, m, n in ((9, 0, 60), (10, 5, 55), (19, 0, 60), (20, 5, 55))])
        for i in range(0, 12, 4):
            self.record(plan_id, entries[i], "completed", 60)
            self.record(plan_id, entries[i + 1], "completed", 55)
            self.record(plan_id, entries[i + 2], "partial", 5, "fatigue")
            state = self.record(plan_id, entries[i + 3], "not_started", 0, "fatigue")
        [cap] = self.proposals(state, "dailyPlannedMinutes")
        self.assertEqual((cap["ruleVersion"], cap["proposedChanges"]["dailyPlannedMinutes"]), ("daily-cap-v1", {"from": None, "to": 120}))
        # The evenings were missed after a day's worth of work: that is not the evening's fault.
        self.assertEqual(self.proposals(state, "focusTime"), [])
        self.assertEqual(self.proposals(state, "periodMinutes"), [])

    def test_work_that_takes_longer_leaves_time_free_in_the_plan(self):
        plan_id, entries = self.put_plan([(self.day(d, 9), 60) for d in range(7, 11)])
        for task in entries:
            state = self.record(plan_id, task, "completed", 84)
        [pace] = self.proposals(state, "pacePercent")
        self.assertEqual(pace["proposedChanges"]["pacePercent"], {"from": None, "to": 140})
        self.call(f"/api/execution/proposals/{pace['id']}/approve")
        slots = [{"day": d, "hour": h} for d in range(7) for h in (9, 10)]
        self.call("/api/execution/settings", method="put", settings={"slots": slots, "view": "timeline"})
        draft = self.call("/api/execution/plan", goal="공부", startDate="2030-01-07", consent=True)["planDraft"]
        for day in {e["start"][:10] for e in draft["entries"]}:
            work = sum(e["minutes"] for e in draft["entries"] if e["kind"] == "task" and e["start"][:10] == day)
            self.assertLessEqual(work, 85)
        self.assertIn("pace", [r["key"] for r in draft["personalization"]])

    def test_a_part_of_the_day_that_keeps_falling_short_gets_a_shorter_stretch(self):
        plan_id, entries = self.put_plan([(self.day(d, h), 60) for d in (7, 8, 9, 10) for h in (9, 19)])
        mornings, evenings = entries[0::2], entries[1::2]
        for task in mornings:
            self.record(plan_id, task, "completed", 60)
        for task in evenings[1:]:
            state = self.record(plan_id, task, "partial", 30, "fatigue")
        [period] = self.proposals(state, "periodMinutes")
        self.assertEqual(period["proposedChanges"]["periodMinutes"], {"from": None, "to": {"evening": 30}})

    def test_misses_on_worse_days_do_not_cut_below_what_usually_gets_done(self):
        plan_id, entries = self.put_plan([(self.day(d, 9), 30) for d in range(7, 15)])
        self.call(f"/api/execution/proposals/{self.shorten_to(30)}/approve")
        plan_id, entries = self.put_plan([(self.day(d, 9), 30) for d in range(7, 15)])
        for task in entries[:5]:
            self.record(plan_id, task, "completed", 30)
        for task, minutes in zip(entries[5:], (25, 25, 15)):  # on three different days
            state = self.record(plan_id, task, "partial", minutes, "task_too_large")
        [shorter] = [p for p in state["profileUpdateProposals"] if p["status"] == "pending"
                     and (p["proposedChanges"].get("blockMinutes") or {}).get("to", 99) < 30]
        self.assertEqual(shorter["proposedChanges"]["blockMinutes"]["to"], 25)

    def shorten_to(self, minutes):
        """Approve-ready proposal that brings the 60-minute block down to ``minutes``."""
        plan_id, entries = self.put_plan([(self.day(d, 9), 60) for d in (7, 8, 9)])
        for task in entries:
            state = self.record(plan_id, task, "partial", minutes, "task_too_large")
        [block] = self.proposals(state, "blockMinutes")
        return block["id"]

    def test_without_the_minutes_nothing_is_shortened(self):
        plan_id, entries = self.put_plan([(self.day(d, 9), 60) for d in (7, 8, 9)])
        for task in entries:
            state = self.record(plan_id, task, "partial", None, "task_too_large")
        self.assertEqual(self.proposals(state, "blockMinutes"), [])

    def test_one_bad_day_is_not_a_pattern_and_the_floor_is_fifteen(self):
        plan_id, entries = self.put_plan([(self.day(7, h), 60) for h in (9, 10, 19)])
        for task in entries:
            state = self.record(plan_id, task, "partial", 5, "task_too_large")
        self.assertEqual(self.proposals(state, "blockMinutes"), [])
        plan_id, entries = self.put_plan([(self.day(d, 9), 60) for d in (8, 9, 10)])
        for task in entries:
            state = self.record(plan_id, task, "partial", 5, "task_too_large")
        [block] = self.proposals(state, "blockMinutes")
        self.assertEqual(block["proposedChanges"]["blockMinutes"]["to"], 15)

    def test_a_shortage_after_an_overrun_is_about_pace_not_size_or_energy(self):
        plan_id, entries = self.put_plan([(self.day(d, h, m), n) for d in (7, 8, 9, 10) for h, m, n in ((10, 0, 60), (11, 5, 55))])
        for i in range(0, 8, 2):
            self.record(plan_id, entries[i], "completed", 84)
            state = self.record(plan_id, entries[i + 1], "partial", 30, "time_shortage")
        self.assertEqual(self.proposals(state, "blockMinutes"), [])
        self.assertEqual(self.proposals(state, "dailyPlannedMinutes"), [])
        [pace] = self.proposals(state, "pacePercent")
        self.assertEqual(pace["proposedChanges"]["pacePercent"]["to"], 140)

    def test_a_daily_cap_keeps_the_parts_of_the_day_that_go_better_more_often(self):
        days = [datetime(2030, 1, 7) + timedelta(days=d) for d in range(14)]
        windows = [w for day in days for w in ((day.replace(hour=10), day.replace(hour=12)), (day.replace(hour=19), day.replace(hour=21)))]
        records = ([{"plannedStart": "2030-01-06T10:00", "result": "partial"}] * 8
                   + [{"plannedStart": "2030-01-06T19:00", "result": "completed"}] * 8)
        odds = period_odds(records, "2030-01-07")
        self.assertEqual(odds, {"morning": 0.1, "evening": 0.9})
        kept = pick_windows_for_cap(windows, 120, odds, "user-1")
        self.assertEqual(kept, pick_windows_for_cap(windows, 120, odds, "user-1"))  # the same request, the same week
        evenings = sum(begin.hour == 19 for begin, _ in kept)
        self.assertEqual(len(kept), 14)  # one stretch a day fits the cap
        self.assertGreater(evenings, 10)
        # With nothing known yet the parts of the day are even; a known best part is kept first.
        self.assertEqual(period_odds([], "2030-01-07"), {})
        self.assertTrue(all(begin.hour == 10 for begin, _ in pick_windows_for_cap(windows, 120, odds, "user-1", "morning")))

    def test_shaping_the_chosen_time(self):
        windows = [(datetime(2030, 1, 7, 9), datetime(2030, 1, 7, 11)), (datetime(2030, 1, 7, 19), datetime(2030, 1, 7, 21))]
        self.assertEqual(shape_windows(windows, {}), windows)
        self.assertEqual(shape_windows(windows, {"pacePercent": 140, "periodMinutes": {"evening": 30}}),
                         [(datetime(2030, 1, 7, 9), datetime(2030, 1, 7, 10, 25)), (datetime(2030, 1, 7, 19), datetime(2030, 1, 7, 19, 21))])


if __name__ == "__main__":
    unittest.main()
