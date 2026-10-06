import unittest
from datetime import datetime

from server.app.adaptive import build_adaptive_planner_graph
from server.app.adaptive.scheduling import fill, pack
from server.tests.test_adaptive_planner_graph import base_state


def dt(text):
    return datetime.fromisoformat(f"2030-01-{text}")


def windows(*pairs):
    return [(dt(a), dt(b)) for a, b in pairs]


def never_generate(_state):
    raise AssertionError("generator must not run")


def reschedule_state(free, *, deadline=None, within_plan=False, remaining=None, style="flexible_queue", focus=None):
    state = base_state()
    state["execution_context"] = {"schedule_style": style, "focus_minutes": focus, "break_minutes": 5}
    state["check_in"]["reason_code"] = "time_shortage"
    state["check_in"]["remaining_minutes"] = remaining
    state["schedule_context"] = {
        "now": "2030-01-07T17:00",
        "free_windows": [[f"2030-01-{a}", f"2030-01-{b}"] for a, b in free],
        "deadline": deadline,
        "deadline_within_plan": within_plan,
    }
    return state


class FillTests(unittest.TestCase):
    def test_uses_short_window_first_then_continues_later(self):
        # 60 minutes of work, 50 free today: do 50 today and 10 tomorrow, not all 60 tomorrow.
        placements, left = fill(60, windows(("07T18:00", "07T18:50"), ("08T18:00", "08T20:00")),
                                min_piece=5, max_piece=None, gap=0)

        self.assertEqual(placements, windows(("07T18:00", "07T18:50"), ("08T18:00", "08T18:10")))
        self.assertEqual(left, 0)

    def test_time_blocks_cap_each_piece_and_leave_breaks(self):
        placements, _ = fill(60, windows(("07T18:00", "07T20:00")), min_piece=5, max_piece=25, gap=5)

        self.assertEqual(placements, windows(("07T18:00", "07T18:25"), ("07T18:30", "07T18:55"), ("07T19:00", "07T19:10")))

    def test_never_leaves_a_sliver_behind(self):
        placements, left = fill(52, windows(("07T18:00", "07T18:50"), ("08T18:00", "08T19:00")),
                                min_piece=5, max_piece=None, gap=0)

        self.assertEqual([round((e - s).total_seconds() / 60) for s, e in placements], [47, 5])
        self.assertEqual(left, 0)

    def test_skips_windows_too_short_and_reports_what_did_not_fit(self):
        placements, left = fill(60, windows(("07T18:00", "07T18:03"), ("07T19:00", "07T19:30")),
                                min_piece=5, max_piece=None, gap=0)

        self.assertEqual(placements, windows(("07T19:00", "07T19:30")))
        self.assertEqual(left, 30)

    def test_pack_keeps_order_and_whole_tasks(self):
        free = windows(("07T18:00", "07T18:30"), ("08T18:00", "08T19:00"))

        self.assertEqual(pack([20, 40], free, gap=0), windows(("07T18:00", "07T18:20"), ("08T18:00", "08T18:40")))
        self.assertIsNone(pack([20, 70], free, gap=0))


class RescheduleGraphTests(unittest.TestCase):
    def test_remaining_work_fills_earliest_free_time(self):
        state = reschedule_state([("07T18:00", "07T18:50"), ("08T18:00", "08T20:00")])

        result = build_adaptive_planner_graph(never_generate).invoke(state)

        self.assertEqual(result["strategy"], "reschedule")
        self.assertEqual(result["approval_status"], "waiting")
        draft = result["draft"]
        self.assertEqual(draft["kind"], "reschedule")
        self.assertEqual([(t["start"], t["minutes"]) for t in draft["tasks"]],
                         [("2030-01-07T18:00", 50), ("2030-01-08T18:00", 10)])
        self.assertEqual(draft["tasks"][0]["title"], "발표 자료 초안 작성 (1/2)")
        self.assertEqual(draft["tasks"][1]["done_when"], "슬라이드 초안이 완성됨")
        self.assertIn("01/07 18:00~18:50(50분)", draft["applied_reasons"][0])

    def test_user_estimate_of_remaining_work_is_used(self):
        state = reschedule_state([("07T18:00", "07T20:00")], remaining=20)

        result = build_adaptive_planner_graph(never_generate).invoke(state)

        self.assertEqual([t["minutes"] for t in result["draft"]["tasks"]], [20])

    def test_time_blocks_pieces_respect_focus(self):
        state = reschedule_state([("07T18:00", "07T20:00")], style="time_blocks", focus=25)

        result = build_adaptive_planner_graph(never_generate).invoke(state)

        self.assertEqual([t["minutes"] for t in result["draft"]["tasks"]], [25, 25, 10])

    def test_overflow_moves_to_next_plan_when_deadline_allows(self):
        state = reschedule_state([("07T18:00", "07T18:40")], deadline="2030-01-20")

        result = build_adaptive_planner_graph(never_generate).invoke(state)

        self.assertEqual(result["approval_status"], "waiting")
        self.assertEqual(result["draft"]["carry_over_minutes"], 20)
        self.assertTrue(any("다음 계획" in r for r in result["draft"]["applied_reasons"]))

    def test_no_free_time_before_deadline_asks_to_replan(self):
        state = reschedule_state([], deadline="2030-01-08", within_plan=True)

        result = build_adaptive_planner_graph(never_generate).invoke(state)

        self.assertEqual(result["approval_status"], "needs_input")
        self.assertEqual(result["fallback"]["source"], "no_time_before_deadline")

    def test_deadline_too_close_asks_ai_to_cut_scope_then_places_it(self):
        seen = []

        def generator(state):
            seen.append(dict(state["fit_limits"]))
            return {
                "replaces_task_id": "task-1",
                "tasks": [
                    {"title": "핵심 슬라이드 5장", "minutes": 25, "done_when": "5장 초안"},
                    {"title": "결론 슬라이드", "minutes": 10, "done_when": "결론 1장"},
                ],
                "applied_reasons": ["마감 전 40분에 맞춰 핵심만 남김"],
                "dropped_scope": ["디자인 다듬기"],
            }

        state = reschedule_state([("07T18:00", "07T18:30"), ("08T18:00", "08T18:10")], deadline="2030-01-08", within_plan=True)

        result = build_adaptive_planner_graph(generator).invoke(state)

        self.assertEqual(seen, [{"max_total_minutes": 40, "max_piece_minutes": 30}])
        self.assertEqual(result["approval_status"], "waiting")
        draft = result["draft"]
        self.assertEqual(draft["kind"], "fit_deadline")
        self.assertEqual([(t["start"], t["end"]) for t in draft["tasks"]],
                         [("2030-01-07T18:00", "2030-01-07T18:25"), ("2030-01-08T18:00", "2030-01-08T18:10")])
        self.assertEqual(draft["dropped_scope"], ["디자인 다듬기"])

    def test_fit_that_cannot_be_placed_is_regenerated(self):
        replies = [
            [{"title": "한 번에 다", "minutes": 40, "done_when": "완료"}],  # no 40-minute window
            [{"title": "앞부분", "minutes": 30, "done_when": "완료"}, {"title": "뒷부분", "minutes": 10, "done_when": "완료"}],
        ]
        errors = []

        def generator(state):
            errors.append(list(state["validation_errors"]))
            return {"replaces_task_id": "task-1", "tasks": replies.pop(0),
                    "applied_reasons": ["마감에 맞춤"]}

        state = reschedule_state([("07T18:00", "07T18:30"), ("08T18:00", "08T18:10")], deadline="2030-01-08", within_plan=True)

        result = build_adaptive_planner_graph(generator).invoke(state)

        self.assertEqual(result["approval_status"], "waiting")
        self.assertTrue(any("tasks.0.minutes" in e for e in errors[1]))

    def test_missing_schedule_context_is_requested(self):
        state = reschedule_state([])
        del state["schedule_context"]

        result = build_adaptive_planner_graph(never_generate).invoke(state)

        self.assertEqual(result["fallback"]["missing_fields"], ["schedule_context"])

    def test_approval_rechecks_placement_against_fresh_free_time(self):
        state = reschedule_state([("07T18:00", "07T18:50"), ("08T18:00", "08T20:00")])
        draft = build_adaptive_planner_graph(never_generate).invoke(state)["draft"]
        writes = []

        class Writer:
            def apply_recovery(self, **kwargs):
                writes.append(kwargs)

        review = {**state, "request": "review", "decision": "approve", "strategy": "reschedule",
                  "pending_draft": draft, "base_revision": 1}
        approved = build_adaptive_planner_graph(never_generate, plan_writer=Writer()).invoke(review)
        self.assertEqual(approved["approval_status"], "approved")

        # By the time the user approves, the first slot has passed.
        late = {**review, "schedule_context": {**review["schedule_context"], "now": "2030-01-07T18:30"}}
        stale = build_adaptive_planner_graph(never_generate, plan_writer=Writer()).invoke(late)
        self.assertEqual(stale["fallback"]["source"], "approval_validation")
        self.assertEqual(len(writes), 1)

    def test_revising_a_code_built_placement_keeps_it_pending(self):
        state = reschedule_state([("07T18:00", "07T20:00")])
        draft = build_adaptive_planner_graph(never_generate).invoke(state)["draft"]
        review = {**state, "request": "review", "decision": "revise", "strategy": "reschedule",
                  "pending_draft": draft, "user_feedback": "토요일로", "revision_count": 0}

        result = build_adaptive_planner_graph(never_generate).invoke(review)

        self.assertEqual(result["approval_status"], "waiting")
        self.assertEqual(result["fallback"]["source"], "revise_not_supported")
        self.assertEqual(result["draft"], draft)


if __name__ == "__main__":
    unittest.main()
