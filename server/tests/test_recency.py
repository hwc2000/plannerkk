"""recency-v1: recent records count more; pure tests on state dicts (no API, database or model)."""
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from server.app import execution_learning as learning
from server.app import recency
from server.app.execution_profile import generate_profile

ANSWERS = {"roles": ["student"], "regularity": "regular", "barriers": ["none"], "focusMinutes": 60, "dailyMinutes": None,
           "energy": "unknown", "recovery": "replan", "constraints": "", "context": "", "scheduleStyle": "time_blocks"}


def ago(days, hour=12):
    """A moment ``days`` Korean calendar days ago, as stored (UTC)."""
    kst = datetime.now(recency.KST).replace(hour=hour, minute=0, second=0, microsecond=0) - timedelta(days=days)
    return kst.astimezone(timezone.utc).isoformat()


class WeightTests(unittest.TestCase):
    def test_weight_halves_every_half_life_and_ends_at_the_horizon(self):
        now = datetime(2026, 11, 9, 12, tzinfo=recency.KST)
        self.assertEqual(recency.weight("2026-11-09", now), 1.0)
        self.assertEqual(recency.weight("2026-11-12", now), 1.0)  # a future day counts as today
        self.assertAlmostEqual(recency.weight("2026-10-26", now), 0.5)
        self.assertAlmostEqual(recency.weight("2026-10-12", now), 0.25)
        last = (now - timedelta(days=recency.HORIZON_DAYS - 1)).date().isoformat()
        gone = (now - timedelta(days=recency.HORIZON_DAYS)).date().isoformat()
        self.assertGreater(recency.weight(last, now), 0)
        self.assertEqual(recency.weight(gone, now), 0.0)
        self.assertEqual(recency.weight(None, now), 0.0)

    def test_age_is_in_korean_calendar_days(self):
        now = datetime(2026, 11, 9, 0, 30, tzinfo=recency.KST)
        self.assertEqual(recency.age_days("2026-11-08T15:10:00+00:00", now), 0)  # 00:10 KST, same day
        self.assertEqual(recency.age_days("2026-11-08T14:50:00+00:00", now), 1)

    def test_equal_weights_keep_the_old_median_and_share(self):
        for values in ([3], [1, 2], [5, 1, 3], [4, 1, 3, 2], [9, 7, 5, 3, 1, 8]):
            self.assertEqual(recency.weighted_median([(v, 1.0) for v in values]), learning.median(values))
        self.assertEqual(recency.weighted_share([(True, 1.0)] * 3 + [(False, 1.0)]), 0.75)
        self.assertIsNone(recency.weighted_share([]))
        self.assertIsNone(recency.weighted_median([(1, 0.0)]))

    def test_a_heavier_recent_value_moves_the_median(self):
        self.assertEqual(recency.weighted_median([(1.0, 0.5)] * 3 + [(1.5, 1.0)] * 2), 1.5)


class RuleTests(unittest.TestCase):
    def setUp(self):
        profile = generate_profile(ANSWERS)
        profile.update(id="profile-1", version=1)
        self.state = {"profile": profile, "projectProfiles": {}, "profileUpdateProposals": [], "executionRecords": []}

    def add(self, days, planned, actual, result="completed", reason=None, hour=9):
        start = (datetime.now(recency.KST) - timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
        self.state["executionRecords"].append({
            "id": str(uuid4()), "profileId": "profile-1", "projectId": None, "projectProfileId": None,
            "plannedMinutes": planned, "actualMinutes": actual, "result": result, "reasonCode": reason,
            "plannedStart": start.replace(tzinfo=None).isoformat(timespec="minutes"), "createdAt": ago(days, hour + 1)})

    def proposals(self, key):
        return [p for p in self.state["profileUpdateProposals"] if key in p["proposedChanges"]]

    def test_pace_follows_the_recent_records(self):
        # Six tasks two weeks ago took as long as planned; the last four took 1.5 times as long.
        for d in (10, 11, 12, 13, 12, 11):
            self.add(d, 60, 60)
        for d in (0, 1, 1, 2):
            self.add(d, 60, 90)
        # Equal weights read the middle of all ten: 1.0, no change.
        ratios = [r["actualMinutes"] / r["plannedMinutes"] for r in self.state["executionRecords"]]
        self.assertEqual(learning.median(ratios), 1.0)
        learning.propose_pace(self.state)
        [pace] = self.proposals("pacePercent")
        self.assertEqual(pace["proposedChanges"]["pacePercent"]["to"], 150)
        self.assertIn("최근 작업일수록", pace["sizing"])

    def test_a_long_history_is_not_thrown_away_after_two_weeks(self):
        # Sixteen tasks three to four weeks ago took as long as planned; one slow week since.
        # Before, everything past 14 days was dropped and the slow week alone set the pace (150%).
        # Now the long history still counts (about a third each), so one week does not change it.
        for d in range(20, 28):
            self.add(d, 60, 60)
            self.add(d, 60, 60)
        for d in (0, 1, 2, 3):
            self.add(d, 60, 90)
        recent = [r for r in self.state["executionRecords"] if learning.is_recent(r)]
        self.assertEqual(learning.median([r["actualMinutes"] / r["plannedMinutes"] for r in recent]), 1.5)
        learning.propose_pace(self.state)
        self.assertEqual(self.proposals("pacePercent"), [])
        weights = [learning.record_weight(r) for r in self.state["executionRecords"][:16]]
        self.assertTrue(all(0.25 < w < 0.4 for w in weights))

    def test_a_daily_cap_needs_recent_run_out_days_and_weighs_them_more(self):
        def run_out_day(d, worked):
            self.add(d, 60, 60, hour=9)
            self.add(d, 60, worked, "partial", "fatigue", hour=11)
            self.add(d, 120, 0, "not_started", "fatigue", hour=19)
        for d in (40, 41, 42):
            run_out_day(d, 50)  # long ago: worked 110 of 240
        learning.propose_daily_cap(self.state)
        self.assertEqual(self.proposals("dailyPlannedMinutes"), [])  # nothing lately: no proposal
        for d in (1, 2, 3):
            run_out_day(d, 30)  # lately: worked 90 of 240
        learning.propose_daily_cap(self.state)
        [cap] = self.proposals("dailyPlannedMinutes")
        # The weighted middle day is a recent one (90), not between old and new.
        self.assertEqual(cap["proposedChanges"]["dailyPlannedMinutes"]["to"], 90)
        self.assertIn("최근 날일수록", cap["sizing"])

    def test_a_record_counts_by_the_day_it_was_told(self):
        self.add(0, 30, 30)
        self.add(13, 30, 30)
        today, older = (learning.record_weight(r) for r in self.state["executionRecords"])
        self.assertEqual(today, 1.0)
        self.assertAlmostEqual(older, 0.5 ** (13 / 14))


if __name__ == "__main__":
    unittest.main()
