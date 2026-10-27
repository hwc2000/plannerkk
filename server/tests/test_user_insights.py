"""Pure, dated evidence tests; no database, API, or model calls."""
import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from server.app import user_insights as ui

NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


def session(day, place="카페", focus="good", project="essay", **extra):
    return {"id": f"{project}-{day}-{place}", "date": (NOW - timedelta(days=day)).date().isoformat(),
            "projectId": project, "place": place, "focus": focus, **extra}


class UserInsightTests(unittest.TestCase):
    def setUp(self):
        clock = patch.object(ui, "_now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)

    def candidates(self, state, project=None):
        return ui.insights_for_ai(state, project_id=project)["candidatePatterns"]

    def place(self, state, name="카페", project=None):
        return next(p for p in self.candidates(state, project) if p["field"] == "place" and p["value"] == name)

    def test_one_observation_is_not_a_habit_or_declaration(self):
        state = {"checkInSessions": [session(0)]}
        candidate = self.place(state)
        self.assertEqual(candidate["status"], "insufficient")
        self.assertEqual(candidate["samples"], 1)
        self.assertEqual(ui.known_insights(state), {})
        self.assertEqual(ui.insights_for_ai(state)["recommendations"], [])

    def test_minimum_counts_distinct_days_and_ratio(self):
        state = {"checkInSessions": [session(i) for i in range(3)]}
        self.assertEqual(self.place(state)["status"], "supported")
        state["checkInSessions"] = [dict(session(0), id=str(i)) for i in range(8)]
        self.assertEqual(self.place(state)["status"], "insufficient")
        state["checkInSessions"] = [session(i, focus="good" if i < 7 else "poor") for i in range(10)]
        self.assertEqual(self.place(state)["goodFocusRatio"], .7)
        self.assertEqual(self.place(state)["status"], "supported")
        state["checkInSessions"][6]["focus"] = "poor"
        self.assertEqual(self.place(state)["status"], "mixed")

    def test_unknown_focus_is_not_failure_or_confirmed_success(self):
        state = {"checkInSessions": [session(i, focus="good" if i < 3 else None) for i in range(7)]}
        p = self.place(state)
        self.assertEqual((p["samples"], p["knownFocus"], p["unknownFocus"], p["goodFocusRatio"]), (7, 3, 4, 1.0))
        self.assertEqual(p["status"], "supported")
        state["checkInSessions"][1]["focus"] = "unexpected"
        self.assertEqual(self.place(state)["status"], "insufficient")

    def test_primary_sessions_not_duplicated_by_task_records(self):
        state = {"checkInSessions": [session(0)], "executionRecords": [dict(session(0), checkInId="essay-0-카페") for _ in range(8)]}
        self.assertEqual(ui.session_summary(state)["기록 수"], 1)
        self.assertEqual(self.place(state)["samples"], 1)

    def test_legacy_grouping_and_undated_rows_never_prove_days(self):
        records = [dict(session(i), checkInId=f"event-{i}", checkInDate=session(i)["date"]) for i in range(3) for _ in range(6)]
        self.assertEqual(self.place({"executionRecords": records})["samples"], 3)
        for row in records:
            row.pop("checkInId")
        self.assertEqual(self.place({"executionRecords": records})["samples"], 3)
        undated = {"executionRecords": [{"place": "카페", "focus": "good", "id": str(i)} for i in range(8)]}
        self.assertEqual(self.place(undated)["status"], "insufficient")
        self.assertEqual(self.place(undated)["distinctDays"], 0)

    def test_unknown_task_date_is_not_a_checkin_date(self):
        state = {"executionRecords": [{"scheduledDate": session(i)["date"], "place": "카페", "focus": "good"} for i in range(5)]}
        self.assertEqual(self.place(state)["status"], "insufficient")

    def test_recency_expiry_and_reversed_evidence_downgrade(self):
        state = {"checkInSessions": [session(i) for i in range(5, 25)]}
        self.assertEqual(self.place(state)["status"], "supported")
        state["checkInSessions"] += [session(i, focus="poor") for i in range(5)]
        self.assertEqual(self.place(state)["status"], "mixed")  # lifetime 80% cannot hide reversal
        self.assertEqual(self.candidates({"checkInSessions": [session(i) for i in range(40, 45)]}), [])

    def test_project_scope_and_global_declarations_do_not_mutate_profile(self):
        state = {"checkInSessions": [session(i) for i in range(3)] + [session(i, place="집", project="app", focus="poor") for i in range(3)],
                 "userInsights": {"place": {"value": "도서관", "history": ["도서관"]}}, "userProfile": {"x": 1}}
        before = copy.deepcopy(state)
        context = ui.insights_for_ai(state, project_id="essay")
        self.assertEqual({p["value"] for p in context["candidatePatterns"]}, {"카페"})
        self.assertEqual(context["알게 된 것"]["주로 하는 곳"], "도서관")
        self.assertEqual(context["scope"], {"kind": "project", "projectId": "essay"})
        self.assertEqual(ui.insights_for_ai(state)["scope"]["kind"], "global_aggregate")
        self.assertEqual(state, before)

    def test_eighty_percent_success_is_not_eighty_percent_recommendations(self):
        state = {"checkInSessions": [session(i, focus="good" if i < 8 else "poor") for i in range(10)] + [session(1, place="집")]}
        context = ui.insights_for_ai(state)
        self.assertEqual(self.place(state)["goodFocusRatio"], .8)
        self.assertEqual(context["recommendations"][0]["maxShare"], .6)
        self.assertEqual({o["place"] for o in context["placeOptions"]}, {"카페", "집", None})
        self.assertIn("not every task", context["selectionPolicy"])
        self.assertIn("titles generic", context["selectionPolicy"])
        self.assertIn("no forced cost/time", context["selectionPolicy"])
        self.assertIn("not causal", context["interpretationPolicy"])

    def test_no_invented_alternative_or_outcome_even_with_only_one_place(self):
        state = {"checkInSessions": [session(i) for i in range(3)]}
        ctx = ui.insights_for_ai(state)
        self.assertEqual({p["place"] for p in ctx["placeOptions"]}, {"카페", None})
        self.assertLessEqual(ctx["recommendations"][0]["maxShare"], .6)
        self.assertNotIn("goodFocusRatio", next(p for p in ctx["placeOptions"] if p["place"] is None))

    def test_declared_evidence_accumulates_dedupes_and_retains_ui_history(self):
        state = {}
        for day in range(3):
            ui.apply_insights(state, {"focus_aids": "음악"}, event_id=f"e{day}", date=session(day)["date"], project_id="essay")
        ui.apply_insights(state, {"focus_aids": "음악"}, event_id="e0", date=session(0)["date"], project_id="essay")
        item = state["userInsights"]["focus_aids"]
        self.assertEqual(item["evidence"]["confirmations"], 3)
        self.assertEqual(item["evidence"]["distinctDays"], 3)
        self.assertEqual(len(item["evidence"]["samples"]), 3)
        self.assertEqual(item["kind"], "declared")
        ui.apply_insights(state, {"focus_aids": "휴대폰 멀리"})
        self.assertEqual(item["history"], ["음악"])
        self.assertEqual(state["userInsights"]["focus_aids"]["history"], ["음악", "휴대폰 멀리"])
        self.assertEqual(ui.known_insights(state)["집중에 도움 되는 습관"], "음악, 휴대폰 멀리")

    def test_legacy_value_without_history_and_no_fabricated_confirmations(self):
        state = {"userInsights": {"place": {"value": "집"}}}
        self.assertEqual(ui.known_insights(state), {"주로 하는 곳": "집"})
        ui.apply_insights(state, {"place": "집"}, event_id="new")
        self.assertEqual(state["userInsights"]["place"]["evidence"]["confirmations"], 1)

    def test_legacy_conflict_is_unknown_and_partial_migration_keeps_other_days(self):
        records = [dict(session(i), checkInId=f"e{i}", checkInDate=session(i)["date"]) for i in range(3)]
        state = {"checkInSessions": [session(0)], "executionRecords": records}
        self.assertEqual(self.place(state)["samples"], 3)
        state["executionRecords"].append(dict(records[1], focus="poor"))
        self.assertEqual(self.place(state)["knownFocus"], 2)
        self.assertEqual(self.place(state)["status"], "insufficient")

    def test_same_day_approval_replays_and_expired_samples_not_confirmations(self):
        state = {}
        for _ in range(6):
            ui.apply_insights(state, {"place": "카페"})
        self.assertEqual(state["userInsights"]["place"]["evidence"]["confirmations"], 1)
        ui.apply_insights(state, {"place": "카페"}, event_id="old", date=session(40)["date"])
        self.assertEqual(state["userInsights"]["place"]["evidence"]["confirmations"], 1)
        self.assertEqual(len(state["userInsights"]["place"]["evidence"]["samples"]), 2)

    def test_success_rates_count_days_not_sessions_or_projects(self):
        rows = [dict(session(0), id=f"event-{i}", projectId=f"project-{i}",
                     atmosphere="quiet") for i in range(8)]
        rows += [dict(session(i, focus="poor"), atmosphere="quiet") for i in (1, 2)]
        state = {"checkInSessions": rows}
        for candidate in self.candidates(state):
            self.assertEqual(candidate["samples"], 3)
            self.assertEqual(candidate["knownFocus"], 3)
            self.assertEqual(candidate["goodFocus"], 1)
            self.assertAlmostEqual(candidate["goodFocusRatio"], 1 / 3)
            self.assertAlmostEqual(candidate["recentGoodFocusRatio"], 1 / 3)
            self.assertEqual(candidate["status"], "mixed")
        self.assertEqual(ui.insights_for_ai(state)["recommendations"], [])

    def test_duplicate_volume_cannot_evict_other_days_before_aggregation(self):
        state = {"checkInSessions": [session(0)] + [session(i, focus="poor") for i in (1, 2)]}
        before = self.place(state)
        state["checkInSessions"] += [dict(session(0), id=f"duplicate-{i}") for i in range(150)]
        self.assertEqual(self.place(state), before)
        policy = ui.insights_for_ai(state)["evidencePolicy"]
        self.assertEqual(policy["observationUnit"], "calendar_day")
        self.assertEqual(policy["calendarTimezone"], "Asia/Seoul")
        self.assertEqual(policy["sameDayFocusPolicy"], "unanimous_valid_focus_else_unknown")

    def test_same_day_conflicts_and_missing_focus_are_unknown(self):
        for other_focus in ("poor", "ok", None, "invalid"):
            with self.subTest(other_focus=other_focus):
                state = {"checkInSessions": [session(i) for i in range(3)] +
                         [dict(session(0, focus=other_focus, project="other"), id="extra")]}
                p = self.place(state)
                self.assertEqual((p["samples"], p["knownFocus"], p["unknownFocus"]), (3, 2, 1))
                self.assertEqual(p["status"], "insufficient")
                self.assertEqual(self.place(state, project="essay")["status"], "supported")

    def test_recent_ratio_also_counts_one_observation_per_day(self):
        rows = [session(i) for i in range(5, 25)]
        rows += [session(i, focus="poor") for i in range(1, 5)]
        rows += [dict(session(0), id=f"repeat-{i}") for i in range(20)]
        p = self.place({"checkInSessions": rows})
        self.assertEqual(p["recentKnownFocus"], 5)
        self.assertEqual(p["recentGoodFocusRatio"], .2)
        self.assertEqual(p["status"], "mixed")

    def test_declaration_confirmations_are_distinct_days_across_projects(self):
        state = {}
        for i in range(8):
            ui.apply_insights(state, {"place": "카페"}, event_id=f"e{i}", project_id=f"p{i}")
        evidence = state["userInsights"]["place"]["evidence"]
        self.assertEqual(evidence["confirmations"], 1)
        self.assertEqual(evidence["distinctDays"], 1)
        self.assertEqual(len(evidence["samples"]), 8)  # raw provenance remains available

    def test_kst_calendar_boundaries_for_windows_and_declarations(self):
        for instant, day in (("2026-10-26T14:59:59+00:00", "2026-10-26"),
                             ("2026-10-26T15:00:00+00:00", "2026-10-27"),
                             ("2026-10-26T23:59:59+00:00", "2026-10-27"),
                             ("2026-10-27T00:00:00+00:00", "2026-10-27")):
            with self.subTest(instant=instant), patch.object(ui, "_now", return_value=datetime.fromisoformat(instant)):
                today = datetime.fromisoformat(day)
                oldest = (today - timedelta(days=29)).date().isoformat()
                expired = (today - timedelta(days=30)).date().isoformat()
                future = (today + timedelta(days=1)).date().isoformat()
                self.assertTrue(ui._in_window(day))
                self.assertTrue(ui._in_window(oldest))
                self.assertFalse(ui._in_window(expired))
                self.assertFalse(ui._in_window(future))
                state = {}
                ui.apply_insights(state, {"place": "카페"})
                evidence = state["userInsights"]["place"]["evidence"]
                self.assertEqual(evidence["samples"][0]["date"], day)
                self.assertEqual(evidence["confirmations"], 1)
                rows = [{"id": d, "date": d, "place": "카페", "focus": "good"}
                        for d in (day, oldest, expired, future)]
                self.assertEqual(self.place({"checkInSessions": rows})["samples"], 2)

    def test_timestamp_dates_convert_to_kst_and_naive_dates_are_local(self):
        self.assertEqual(ui._day("2026-10-26T15:00:00Z"), "2026-10-27")
        self.assertEqual(ui._day("2026-10-27T00:00:00+09:00"), "2026-10-27")
        self.assertEqual(ui._day("2026-10-27T00:00:00"), "2026-10-27")
        state = {}
        ui.apply_insights(state, {"place": "카페"}, now=datetime(2026, 10, 27, 0))
        self.assertEqual(state["userInsights"]["place"]["evidence"]["samples"][0]["date"], "2026-10-27")

    def test_old_calls_tone_immediate_and_invalid_values_ignored(self):
        state = {}
        self.assertIn("존댓말", ui.reply_tone(state))
        ui.apply_insights(state, {"tone": "casual", "atmosphere": "invalid", "place": " "}, NOW)
        self.assertIn("반말", ui.reply_tone(state))
        self.assertEqual(set(state["userInsights"]), {"tone"})
        ui.apply_insights(state, {"tone": "polite"}, NOW)
        self.assertIn("존댓말", ui.reply_tone(state))
        self.assertEqual(state["userInsights"]["tone"]["evidence"]["confirmations"], 1)


if __name__ == "__main__":
    unittest.main()
