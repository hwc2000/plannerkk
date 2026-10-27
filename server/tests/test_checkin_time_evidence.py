"""Duration evidence is local to the task quote, exact and bounded; never guessed."""
import unittest

from server.app.planner_checkin import draft_records


class DurationEvidenceTests(unittest.TestCase):
    def minutes(self, quote, claimed, message=None):
        task = {"id": "t", "title": "work", "minutes": 30}
        record = draft_records({"id": "p"}, [(task, "partial", None)], {
            "tasks": [{"taskId": "t", "quote": quote, "actualMinutes": claimed}]
        }, quote if message is None else message)[0]
        self.assertIsNone(record["reasonCode"])
        return record["actualMinutes"]

    def test_explicit_duration_forms(self):
        for quote, minutes in (("한 시간", 60), ("1시간 반", 90), ("두 시간 십오 분", 135),
                               ("2시간 15분", 135), ("반 시간", 30), ("삼십 분", 30),
                               ("1.5 hours", 90), ("1 hour 20 minutes", 80), ("45 min", 45),
                               ("0분", 0), ("24시간", 1440)):
            with self.subTest(quote=quote):
                self.assertEqual(self.minutes(quote, minutes), minutes)

    def test_unbacked_ambiguous_or_out_of_bounds_values_are_unknown(self):
        for quote, claimed, message in (("좀 했어", 60, "60번 보고 좀 했어"),
                                        ("한 시간", 90, None), ("135분", 35, None),
                                        ("35분", 35, "다 했어"), ("25시간", 1500, None),
                                        ("-5분", 5, None), ("1~2시간", 120, None),
                                        ("30분 또는 60분", 30, None), ("35분", True, None),
                                        ("1.333시간", 80, None)):
            with self.subTest(quote=quote, claimed=claimed):
                self.assertIsNone(self.minutes(quote, claimed, message))
