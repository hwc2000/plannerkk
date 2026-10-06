import unittest
from typing import cast

from server.app.adaptive import build_adaptive_planner_graph
from server.app.adaptive.ports import PlanConflictError
from server.app.adaptive.state import PlannerState
from server.tests.test_adaptive_planner_graph import base_state


def valid_draft(**overrides):
    draft = {
        "replaces_task_id": "task-1",
        "tasks": [
            {"title": "목차 작성", "minutes": 10, "done_when": "슬라이드 제목이 정해짐"},
            {"title": "핵심 내용 작성", "minutes": 20, "done_when": "각 슬라이드 핵심 문장이 있음"},
        ],
        "applied_reasons": ["작업이 너무 크다는 실행 결과를 반영함"],
    }
    draft.update(overrides)
    return draft


def placed_draft():
    """valid_draft() as the graph stores it: pieces placed in base_state's free time."""
    draft = valid_draft(kind="shrink")
    draft["tasks"] = [
        {**draft["tasks"][0], "start": "2030-01-07T18:00", "end": "2030-01-07T18:10"},
        {**draft["tasks"][1], "start": "2030-01-07T18:10", "end": "2030-01-07T18:30"},
    ]
    return draft


def review_state(decision, **fields):
    state = base_state()
    del state["check_in"]
    state.update(
        request="review",
        decision=decision,
        strategy="shrink",
        pending_draft=placed_draft(),
        base_revision=3,
        revision_count=0,
    )
    state.update(fields)
    return state


def never_generate(_state):
    raise AssertionError("generator must not run")


class RecordingWriter:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def apply_recovery(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error


class ShrinkLimitTests(unittest.TestCase):
    def test_piece_below_minimum_is_rejected(self):
        result = build_adaptive_planner_graph(
            lambda _state: valid_draft(
                tasks=[{"title": "아주 작은 조각", "minutes": 3, "done_when": "완료"}]
            ),
            max_retries=0,
        ).invoke(base_state())

        self.assertEqual(result["approval_status"], "fallback")
        self.assertTrue(any("최소 5분" in e for e in result["fallback"]["validation_errors"]))

    def test_task_that_cannot_be_split_offers_other_strategies(self):
        state = base_state()
        state["current_task"]["minutes"] = 5

        result = build_adaptive_planner_graph(never_generate).invoke(state)

        self.assertEqual(result["approval_status"], "needs_input")
        self.assertEqual(result["fallback"]["source"], "shrink_not_possible")
        self.assertEqual(result["fallback"]["options"], ["reschedule", "replan"])

    def test_focus_shorter_than_minimum_cannot_shrink_time_blocks(self):
        state = base_state()
        state["execution_context"]["focus_minutes"] = 4

        result = build_adaptive_planner_graph(never_generate).invoke(state)

        self.assertEqual(result["fallback"]["source"], "shrink_not_possible")

    def test_already_shrunk_task_offers_other_strategies(self):
        state = base_state()
        state["current_task"]["recovery_depth"] = 1

        result = build_adaptive_planner_graph(never_generate).invoke(state)

        self.assertEqual(result["fallback"]["source"], "shrink_not_possible")
        self.assertEqual(result["fallback"]["options"], ["reschedule", "replan"])

    def test_shrink_depth_is_a_policy_limit(self):
        state = base_state()
        state["current_task"]["recovery_depth"] = 1

        result = build_adaptive_planner_graph(lambda _state: valid_draft(), max_shrink_depth=2).invoke(state)

        self.assertEqual(result["approval_status"], "waiting")

    def test_policy_limits_are_bounded_strict_integers(self):
        for name, bad in (
            ("max_revisions", -1), ("max_revisions", 6), ("max_revisions", True),
            ("min_task_minutes", 0), ("min_task_minutes", 61), ("min_task_minutes", 5.0),
            ("max_shrink_depth", -1), ("max_shrink_depth", 4),
        ):
            with self.subTest(name=name, value=bad), self.assertRaises(ValueError):
                build_adaptive_planner_graph(never_generate, **{name: bad})


class ReviewTests(unittest.TestCase):
    def test_reject_keeps_current_plan_without_writing(self):
        writer = RecordingWriter()

        result = build_adaptive_planner_graph(never_generate, plan_writer=writer).invoke(
            {"request": "review", "decision": "reject"}
        )

        self.assertEqual(result["approval_status"], "rejected")
        self.assertEqual(result["fallback"]["action"], "keep_current_plan")
        self.assertIsNone(result["draft"])
        self.assertEqual(writer.calls, [])

    def test_approve_revalidates_then_writes_once(self):
        writer = RecordingWriter()

        result = build_adaptive_planner_graph(never_generate, plan_writer=writer).invoke(
            review_state("approve", user_id="user-1", project_id="project-a")
        )

        self.assertEqual(result["approval_status"], "approved")
        self.assertEqual(len(writer.calls), 1)
        call = writer.calls[0]
        self.assertEqual(call["base_revision"], 3)
        self.assertEqual(call["task_id"], "task-1")
        self.assertEqual(call["strategy"], "shrink")
        self.assertEqual(call["user_id"], "user-1")
        self.assertEqual(call["draft"]["tasks"][0]["title"], valid_draft()["tasks"][0]["title"])
        self.assertEqual(call["draft"]["kind"], "shrink")

    def test_approve_requires_base_revision(self):
        state = review_state("approve")
        del state["base_revision"]

        result = build_adaptive_planner_graph(never_generate, plan_writer=RecordingWriter()).invoke(state)

        self.assertEqual(result["fallback"]["missing_fields"], ["base_revision"])

    def test_invalid_pending_draft_is_never_written(self):
        writer = RecordingWriter()
        for draft in (
            valid_draft(replaces_task_id="other-task"),
            valid_draft(tasks=[{"title": "그대로", "minutes": 60, "done_when": "완료"}]),
            {"tasks": "not a list"},
        ):
            with self.subTest(draft=draft):
                result = build_adaptive_planner_graph(never_generate, plan_writer=writer).invoke(
                    review_state("approve", pending_draft=draft)
                )

                self.assertEqual(result["approval_status"], "fallback")
                self.assertEqual(result["fallback"]["source"], "approval_validation")
        self.assertEqual(writer.calls, [])

    def test_stale_plan_is_not_overwritten(self):
        writer = RecordingWriter(PlanConflictError())

        result = build_adaptive_planner_graph(never_generate, plan_writer=writer).invoke(
            review_state("approve")
        )

        self.assertEqual(result["approval_status"], "fallback")
        self.assertEqual(result["fallback"]["source"], "plan_changed")

    def test_storage_error_details_are_not_exposed(self):
        secret = "postgres://user:password@host"
        writer = RecordingWriter(RuntimeError(secret))

        result = build_adaptive_planner_graph(never_generate, plan_writer=writer).invoke(
            review_state("approve")
        )

        self.assertEqual(result["error"], "plan_apply_failed")
        self.assertEqual(result["fallback"]["source"], "storage_error")
        self.assertNotIn(secret, repr(result))

    def test_approve_records_only_the_drafts_own_strategy(self):
        writer = RecordingWriter()

        result = build_adaptive_planner_graph(never_generate, plan_writer=writer).invoke(
            review_state("approve", strategy="reschedule")
        )

        self.assertEqual(result["fallback"]["source"], "approval_validation")
        self.assertTrue(any(e.startswith("kind:") for e in result["validation_errors"]))
        self.assertEqual(writer.calls, [])

    def test_shrink_pieces_are_placed_in_free_time_by_code(self):
        state = base_state()
        state["schedule_context"]["now"] = "2030-01-07T18:20"
        state["schedule_context"]["free_windows"] = [["2030-01-07T18:20", "2030-01-07T18:35"],
                                                     ["2030-01-08T18:00", "2030-01-08T19:00"]]

        result = build_adaptive_planner_graph(lambda _state: valid_draft()).invoke(state)

        self.assertEqual([(t["start"], t["end"]) for t in result["draft"]["tasks"]],
                         [("2030-01-07T18:20", "2030-01-07T18:30"), ("2030-01-08T18:00", "2030-01-08T18:20")])

    def test_shrink_without_free_time_offers_other_strategies(self):
        state = base_state()
        state["schedule_context"]["free_windows"] = [["2030-01-07T18:00", "2030-01-07T18:04"]]

        result = build_adaptive_planner_graph(never_generate).invoke(state)

        self.assertEqual(result["fallback"]["source"], "shrink_not_possible")

    def test_unplaced_draft_is_never_written(self):
        writer = RecordingWriter()

        result = build_adaptive_planner_graph(never_generate, plan_writer=writer).invoke(
            review_state("approve", pending_draft=valid_draft(kind="shrink"))
        )

        self.assertEqual(result["fallback"]["source"], "approval_validation")
        self.assertEqual(writer.calls, [])

    def test_approve_without_writer_is_explicit(self):
        result = build_adaptive_planner_graph(never_generate).invoke(review_state("approve"))

        self.assertEqual(result["approval_status"], "fallback")
        self.assertEqual(result["fallback"]["source"], "writer_not_connected")


class RevisionTests(unittest.TestCase):
    def test_revise_passes_feedback_and_previous_draft_to_generator(self):
        seen = []

        def generator(state):
            seen.append((state["pending_draft"], state["user_feedback"]))
            return valid_draft(
                tasks=[{"title": "목차만 작성", "minutes": 5, "done_when": "목차 5줄"}],
                applied_reasons=["피드백대로 목차를 5분으로 줄임"],
            )

        result = build_adaptive_planner_graph(generator).invoke(
            review_state("revise", user_feedback="목차를 더 짧게 해줘", revision_count=1)
        )

        self.assertEqual(seen, [(placed_draft(), "목차를 더 짧게 해줘")])
        self.assertEqual(result["approval_status"], "waiting")
        self.assertEqual(result["revision_count"], 2)
        self.assertEqual(result["draft"]["applied_reasons"], ["피드백대로 목차를 5분으로 줄임"])

    def test_revision_identical_to_pending_draft_is_rejected(self):
        # Seen with a real LLM: same tasks, but reasons claiming the feedback was applied.
        calls = []

        def generator(state):
            calls.append(list(state["validation_errors"]))
            return valid_draft(applied_reasons=["피드백을 반영함"])

        result = build_adaptive_planner_graph(generator, max_retries=1).invoke(
            review_state("revise", user_feedback="첫 작업을 더 작게")
        )

        self.assertEqual(len(calls), 2)
        self.assertTrue(any("이전 초안과 같습니다" in e for e in calls[1]))
        self.assertEqual(result["fallback"]["action"], "keep_pending_draft")

    def test_revision_limit_keeps_draft_for_approve_or_reject(self):
        result = build_adaptive_planner_graph(never_generate, max_revisions=2).invoke(
            review_state("revise", user_feedback="또 바꿔줘", revision_count=2)
        )

        self.assertEqual(result["approval_status"], "waiting")
        self.assertEqual(result["draft"], placed_draft())
        self.assertEqual(result["fallback"]["action"], "approve_or_reject")

    def test_failed_revision_keeps_pending_draft(self):
        result = build_adaptive_planner_graph(
            lambda _state: valid_draft(replaces_task_id="other-task"), max_retries=1
        ).invoke(review_state("revise", user_feedback="다르게", revision_count=0))

        self.assertEqual(result["approval_status"], "waiting")
        self.assertEqual(result["draft"], placed_draft())
        self.assertEqual(result["fallback"]["action"], "keep_pending_draft")

    def test_revise_to_unconnected_strategy_keeps_pending_draft(self):
        state = cast(PlannerState, review_state(
            "revise", user_feedback="우선순위를 다시 정해줘", strategy="replan"
        ))
        state["planning_context"] = {"goal": "시험 준비"}

        result = build_adaptive_planner_graph(never_generate).invoke(state)

        self.assertEqual(result["approval_status"], "waiting")
        self.assertEqual(result["fallback"]["source"], "route_not_connected")

    def test_revise_requires_real_feedback(self):
        for feedback, key in ((None, "missing_fields"), ("   ", "invalid_fields")):
            with self.subTest(feedback=feedback):
                result = build_adaptive_planner_graph(never_generate).invoke(
                    review_state("revise", user_feedback=feedback)
                )

                self.assertEqual(result["route"], "request_information")
                self.assertIn("user_feedback", result["fallback"][key])


if __name__ == "__main__":
    unittest.main()
