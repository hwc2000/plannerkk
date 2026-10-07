import math
import unittest

from server.app.adaptive import (
    build_adaptive_planner_graph,
    to_execution_context,
    to_profile_change_context,
)
from server.app.adaptive.local import profile_change_context_from_proposal


def base_state():
    return {
        "request": "recovery",
        "execution_context": {
            "schedule_style": "time_blocks",
            "focus_minutes": 20,
        },
        "current_task": {
            "id": "task-1",
            "title": "발표 자료 초안 작성",
            "minutes": 60,
            "done_when": "슬라이드 초안이 완성됨",
        },
        "check_in": {
            "completed": False,
            "actual_minutes": 20,
            "reason_code": "task_too_large",
            "note": "한 번에 끝내기 어려웠다",
        },
        "schedule_context": {
            "now": "2030-01-07T09:00",
            "free_windows": [["2030-01-07T18:00", "2030-01-07T21:00"]],
            "deadline": None,
            "deadline_within_plan": False,
        },
    }


class AdaptivePlannerGraphTests(unittest.TestCase):
    def test_approved_profile_proposal_is_normalized_at_boundary(self):
        proposal = {
            "id": "proposal-1", "profileId": "profile-old", "appliedProfileId": "profile-new",
            "proposedChanges": {"blockMinutes": {"from": 30, "to": 20}},
            "reason": "긴 작업이 반복해서 미완료됨", "evidenceRecordIds": ["record-1", "record-2"],
            "status": "approved",
        }
        context = to_profile_change_context(proposal, converter=profile_change_context_from_proposal)
        self.assertEqual(context, {
            "before": {"block_minutes": 30}, "after": {"block_minutes": 20},
            "changed_fields": ["block_minutes"], "reason": "긴 작업이 반복해서 미완료됨",
            "evidence_record_ids": ["record-1", "record-2"],
            "source_profile_id": "profile-old", "applied_profile_id": "profile-new",
        })

    def test_profile_change_context_rejects_mismatched_fields(self):
        with self.assertRaises(ValueError):
            to_profile_change_context(object(), converter=lambda _proposal: {
                "before": {"block_minutes": 30}, "after": {"block_minutes": 20},
                "changed_fields": ["break_minutes"], "reason": "reason",
                "evidence_record_ids": ["record-1"], "source_profile_id": "old",
                "applied_profile_id": "new",
            })

    def test_new_plan_preserves_profile_change_context_and_uses_full_plan_generator(self):
        context = {
            "before": {"block_minutes": 30}, "after": {"block_minutes": 20},
            "changed_fields": ["block_minutes"], "reason": "긴 작업 미완료",
            "evidence_record_ids": ["record-1"], "source_profile_id": "old",
            "applied_profile_id": "new",
        }
        seen = []
        expected = {"id": "draft-1", "profileId": "new", "entries": []}
        def full_plan_generator(state):
            seen.append(state["profile_change_context"])
            return expected
        result = build_adaptive_planner_graph(
            lambda _state: self.fail("recovery generator must not run"),
            full_plan_generator=full_plan_generator,
        ).invoke({"request": "new_plan", "planning_context": {"goal": "공부"},
                  "profile_change_context": context})
        self.assertEqual(seen, [context])
        self.assertEqual(result["plan_draft"], expected)
        self.assertIsNone(result["draft"])
        self.assertEqual(result["approval_status"], "waiting")

    def test_replan_strategy_uses_full_plan_generator(self):
        state = base_state()
        state["planning_context"] = {"goal": "시험 준비"}
        state["check_in"]["reason_code"] = "priority_changed"
        expected = {"id": "draft-2", "profileId": "profile-1", "entries": []}
        result = build_adaptive_planner_graph(
            lambda _state: self.fail("recovery generator must not run"),
            full_plan_generator=lambda _state: expected,
        ).invoke(state)
        self.assertEqual(result["strategy"], "replan")
        self.assertEqual(result["plan_draft"], expected)
        self.assertEqual(result["approval_status"], "waiting")

    def test_recovery_replan_requests_planning_context_before_generation(self):
        state = base_state()
        state["check_in"]["reason_code"] = "priority_changed"
        result = build_adaptive_planner_graph(
            lambda _state: self.fail("recovery generator must not run"),
            full_plan_generator=lambda _state: self.fail("full generator must not run"),
        ).invoke(state)
        self.assertEqual(result["approval_status"], "needs_input")
        self.assertEqual(result["fallback"]["missing_fields"], ["planning_context"])

    def test_malformed_full_plan_draft_falls_back(self):
        result = build_adaptive_planner_graph(
            lambda _state: self.fail("recovery generator must not run"),
            full_plan_generator=lambda _state: {"id": "draft-without-contract"},
        ).invoke({"request": "new_plan", "planning_context": {"goal": "시험 준비"}})
        self.assertEqual(result["approval_status"], "fallback")
        self.assertEqual(result["error"], "invalid_plan_draft")
        self.assertIsNone(result["plan_draft"])

    def test_full_plan_generation_failure_is_sanitized_and_keeps_current_plan(self):
        secret = "provider-secret"
        def fail(_state):
            raise RuntimeError(secret)
        result = build_adaptive_planner_graph(
            lambda _state: {}, full_plan_generator=fail,
        ).invoke({"request": "new_plan", "planning_context": {"goal": "공부"}})
        self.assertEqual(result["error"], "plan_generation_failed")
        self.assertEqual(result["fallback"]["action"], "keep_current_plan")
        self.assertIsNone(result["plan_draft"])
        self.assertNotIn(secret, repr(result))

    def test_shared_schemas_are_converted_at_one_boundary(self):
        raw_profile = object()
        raw_records = [object()]
        seen = []

        def converter(profile, records):
            seen.append((profile, records))
            return {"schedule_style": "time_blocks", "focus_minutes": 25}

        context = to_execution_context(raw_profile, raw_records, converter=converter)

        self.assertEqual(seen, [(raw_profile, raw_records)])
        self.assertEqual(context, {"schedule_style": "time_blocks", "focus_minutes": 25, "break_minutes": None})

    def test_converter_does_not_invent_missing_values(self):
        context = to_execution_context(object(), [], converter=lambda _profile, _records: {})

        self.assertEqual(context, {"schedule_style": None, "focus_minutes": None, "break_minutes": None})

    def test_malformed_focus_minutes_requests_information(self):
        for value in ("20", True, 20.0, 0):
            with self.subTest(value=value):
                state = base_state()
                state["execution_context"]["focus_minutes"] = value

                result = build_adaptive_planner_graph(
                    lambda _state: self.fail("generator must not run")
                ).invoke(state)

                self.assertEqual(result["route"], "request_information")
                self.assertEqual(
                    result["fallback"]["invalid_fields"],
                    ["execution_context.focus_minutes"],
                )

    def test_malformed_check_in_actual_minutes_requests_information(self):
        for value in ("20", True, 20.0):
            with self.subTest(value=value):
                state = base_state()
                state["check_in"]["actual_minutes"] = value

                result = build_adaptive_planner_graph(
                    lambda _state: self.fail("generator must not run")
                ).invoke(state)

                self.assertEqual(result["route"], "request_information")
                self.assertEqual(
                    result["fallback"]["invalid_fields"],
                    ["check_in.actual_minutes"],
                )

    def test_partial_check_in_requests_missing_field_instead_of_crashing(self):
        state = base_state()
        state["check_in"] = {"reason_code": "task_too_large"}

        result = build_adaptive_planner_graph(lambda _state: self.fail("generator must not run")).invoke(state)

        self.assertEqual(result["route"], "request_information")
        self.assertEqual(result["fallback"]["missing_fields"], ["check_in.completed"])

    def test_malformed_schedule_times_request_information(self):
        cases = (
            ("now", "not-a-date", "schedule_context.now"),
            ("now", 1893456000, "schedule_context.now"),
            ("free_windows", [["2030-01-07T18:00+09:00", "2030-01-07T19:00+09:00"]], "schedule_context.free_windows.0.0"),
            ("free_windows", [["2030-01-07T19:00", "2030-01-07T18:00"]], "schedule_context"),
            ("deadline", "2030/01/08", "schedule_context.deadline"),
        )
        for field, value, path in cases:
            with self.subTest(field=field, value=value):
                state = base_state()
                state["schedule_context"][field] = value

                result = build_adaptive_planner_graph(lambda _state: self.fail("generator must not run")).invoke(state)

                self.assertEqual(result["route"], "request_information")
                self.assertIn(path, result["fallback"]["invalid_fields"])

    def test_invalid_current_task_reports_invalid_field(self):
        state = base_state()
        state["current_task"]["minutes"] = "sixty"

        result = build_adaptive_planner_graph(lambda _state: self.fail("generator must not run")).invoke(state)

        self.assertEqual(result["route"], "request_information")
        self.assertEqual(result["fallback"]["invalid_fields"], ["current_task.minutes"])

    def test_unknown_reason_is_invalid_not_missing(self):
        state = base_state()
        state["check_in"]["reason_code"] = "unknown_reason"

        result = build_adaptive_planner_graph(lambda _state: self.fail("generator must not run")).invoke(state)

        self.assertEqual(result["route"], "request_information")
        self.assertEqual(result["fallback"]["invalid_fields"], ["check_in.reason_code"])
        self.assertNotIn("missing_fields", result["fallback"])

    def test_unconfigured_full_plan_generator_keeps_current_plan_explicitly(self):
        state = base_state()
        state["planning_context"] = {"goal": "시험 준비"}
        state["check_in"]["reason_code"] = "priority_changed"

        result = build_adaptive_planner_graph(lambda _state: self.fail("generator must not run")).invoke(state)

        self.assertEqual(result["route"], "recovery")
        self.assertEqual(result["strategy"], "replan")
        self.assertEqual(result["approval_status"], "fallback")
        self.assertEqual(result["fallback"]["action"], "keep_current_plan")
        self.assertEqual(result["fallback"]["source"], "route_not_connected")

    def test_large_task_uses_shrink_route_and_waits_for_approval(self):
        def generator(state):
            self.assertEqual(state["strategy"], "shrink")
            return {
                "replaces_task_id": "task-1",
                "tasks": [
                    {"title": "목차 작성", "minutes": 10, "done_when": "슬라이드 제목이 정해짐"},
                    {"title": "핵심 내용 작성", "minutes": 20, "done_when": "각 슬라이드 핵심 문장이 있음"},
                ],
                "applied_reasons": ["작업이 너무 크다는 실행 결과를 반영함"],
            }

        result = build_adaptive_planner_graph(generator).invoke(base_state())

        self.assertEqual(result["route"], "recovery")
        self.assertEqual(result["strategy"], "shrink")
        self.assertEqual(result["approval_status"], "waiting")
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["validation_errors"], [])
        self.assertEqual(len(result["draft"]["tasks"]), 2)

    def test_generator_exception_is_sanitized_in_graph_state(self):
        secret = "provider-token-and-internal-details"

        def generator(_state):
            raise RuntimeError(secret)

        result = build_adaptive_planner_graph(generator, max_retries=0).invoke(base_state())

        self.assertEqual(result["error"], "recovery_generation_failed")
        self.assertNotIn(secret, repr(result))

    def test_generated_task_minutes_must_be_strict_integer(self):
        for value in ("10", True, 10.0):
            with self.subTest(value=value):

                def generator(_state, minutes=value):
                    return {
                        "replaces_task_id": "task-1",
                        "tasks": [
                            {
                                "title": "작은 작업",
                                "minutes": minutes,
                                "done_when": "완료",
                            }
                        ],
                        "applied_reasons": ["작업 축소"],
                    }

                result = build_adaptive_planner_graph(generator, max_retries=0).invoke(
                    base_state()
                )

                self.assertEqual(result["approval_status"], "fallback")
                self.assertIsNone(result["draft"])

    def test_validated_draft_is_stored_as_canonical_model_dump(self):
        generated_draft = {
            "replaces_task_id": "task-1",
            "tasks": (
                {"title": "작은 작업", "minutes": 10, "done_when": "완료"},
            ),
            "applied_reasons": ("작업 축소",),
        }

        result = build_adaptive_planner_graph(lambda _state: generated_draft).invoke(
            base_state()
        )

        self.assertEqual(result["approval_status"], "waiting")
        self.assertEqual(
            result["draft"],
            {
                "kind": "shrink",
                "replaces_task_id": "task-1",
                "tasks": [
                    {"title": "작은 작업", "minutes": 10, "done_when": "완료",
                     "start": "2030-01-07T18:00", "end": "2030-01-07T18:10"}
                ],
                "applied_reasons": ["작업 축소"],
                "dropped_scope": [],
                "carry_over_minutes": 0,
            },
        )
        self.assertIsInstance(result["draft"]["tasks"], list)

    def test_max_retries_requires_bounded_strict_integer(self):
        invalid_values = (-1, 6, True, False, "2", 2.0, math.nan, math.inf, -math.inf)
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_adaptive_planner_graph(lambda _state: {}, max_retries=value)

        for value in (0, 5):
            with self.subTest(valid=value):
                build_adaptive_planner_graph(lambda _state: {}, max_retries=value)

    def test_invalid_draft_loops_back_to_generator_then_succeeds(self):
        calls = []

        def generator(state):
            calls.append(list(state.get("validation_errors", [])))
            if len(calls) == 1:
                return {
                    "replaces_task_id": "task-1",
                    "tasks": [{"title": "여전히 큰 작업", "minutes": 50, "done_when": "완료"}],
                    "applied_reasons": [],
                }
            return {
                "replaces_task_id": "task-1",
                "tasks": [{"title": "작은 작업", "minutes": 20, "done_when": "초안 한 장 완료"}],
                "applied_reasons": ["집중 가능 시간 안으로 축소함"],
            }

        result = build_adaptive_planner_graph(generator, max_retries=2).invoke(base_state())

        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[1])
        self.assertEqual(result["retry_count"], 1)
        self.assertEqual(result["approval_status"], "waiting")
        self.assertEqual(result["validation_errors"], [])

    def test_retry_exhaustion_keeps_current_plan_without_numeric_fallback(self):
        def invalid_generator(_state):
            return {
                "replaces_task_id": "task-1",
                "tasks": [{"title": "너무 긴 작업", "minutes": 60, "done_when": "완료"}],
                "applied_reasons": [],
            }

        result = build_adaptive_planner_graph(invalid_generator, max_retries=1).invoke(base_state())

        self.assertEqual(result["approval_status"], "fallback")
        self.assertEqual(result["fallback"]["action"], "keep_current_plan")
        self.assertEqual(result["fallback"]["source"], "validation_policy")
        self.assertNotIn("used_value", result["fallback"])
        self.assertIsNone(result["draft"])

    def test_missing_focus_minutes_requests_input_instead_of_guessing(self):
        state = base_state()
        state["execution_context"]["focus_minutes"] = None

        result = build_adaptive_planner_graph(lambda _state: self.fail("generator must not run")).invoke(state)

        self.assertEqual(result["route"], "request_information")
        self.assertEqual(result["approval_status"], "needs_input")
        self.assertEqual(result["fallback"]["action"], "request_input")
        self.assertEqual(result["fallback"]["missing_fields"], ["execution_context.focus_minutes"])
        self.assertNotIn("used_value", result["fallback"])

    def test_shrink_rejects_task_as_long_as_original(self):
        state = base_state()
        state["current_task"]["minutes"] = 20

        def unchanged_generator(_state):
            return {
                "replaces_task_id": "task-1",
                "tasks": [{"title": "발표 자료 초안 작성", "minutes": 20, "done_when": "완료"}],
                "applied_reasons": ["그대로 둠"],
            }

        result = build_adaptive_planner_graph(unchanged_generator, max_retries=0).invoke(state)

        self.assertEqual(result["approval_status"], "fallback")
        self.assertTrue(
            any(e.startswith("tasks.0.minutes:") for e in result["fallback"]["validation_errors"])
        )

    def test_whitespace_only_text_fails_validation(self):
        for field, value in (("title", " "), ("done_when", "\t"), ("applied_reasons", [" "])):
            with self.subTest(field=field):
                draft = {
                    "replaces_task_id": "task-1",
                    "tasks": [{"title": "작은 작업", "minutes": 10, "done_when": "완료"}],
                    "applied_reasons": ["작업 축소"],
                }
                if field == "applied_reasons":
                    draft["applied_reasons"] = value
                else:
                    draft["tasks"][0][field] = value

                result = build_adaptive_planner_graph(
                    lambda _state, d=draft: d, max_retries=0
                ).invoke(base_state())

                self.assertEqual(result["approval_status"], "fallback")

    def test_whitespace_only_current_task_requests_information(self):
        state = base_state()
        state["current_task"]["title"] = "   "

        result = build_adaptive_planner_graph(lambda _state: self.fail("generator must not run")).invoke(state)

        self.assertEqual(result["fallback"]["invalid_fields"], ["current_task.title"])

    def test_retry_feedback_names_the_failing_field(self):
        seen = []

        def generator(state):
            seen.append(list(state["validation_errors"]))
            return {
                "replaces_task_id": "task-1",
                "tasks": [{"title": "작은 작업", "minutes": 10, "done_when": " "}],
                "applied_reasons": [],
            }

        build_adaptive_planner_graph(generator, max_retries=1).invoke(base_state())

        feedback = seen[1]
        self.assertTrue(any(e.startswith("tasks.0.done_when:") for e in feedback))
        self.assertTrue(any(e.startswith("applied_reasons:") for e in feedback))

    def test_missing_or_unknown_request_asks_for_it(self):
        for value, key in ((None, "missing_fields"), ("chat", "invalid_fields")):
            with self.subTest(value=value):
                state = base_state()
                if value is None:
                    del state["request"]
                else:
                    state["request"] = value

                result = build_adaptive_planner_graph(lambda _state: self.fail("generator must not run")).invoke(state)

                self.assertEqual(result["route"], "request_information")
                self.assertEqual(result["fallback"][key], ["request"])

    def test_new_plan_without_planning_context_is_not_generated(self):
        state = {"request": "new_plan", "user_id": "user-1", "project_id": "project-a"}

        result = build_adaptive_planner_graph(lambda _state: self.fail("generator must not run")).invoke(state)

        self.assertEqual(result["route"], "request_information")
        self.assertEqual(result["fallback"]["missing_fields"], ["planning_context"])

    def test_new_plan_does_not_require_check_in(self):
        state = {
            "request": "new_plan",
            "user_id": "user-1",
            "project_id": "project-a",
            "planning_context": {"project": {"title": "졸업작품"}},
        }

        result = build_adaptive_planner_graph(lambda _state: self.fail("generator must not run")).invoke(state)

        self.assertEqual(result["route"], "new_plan")
        self.assertEqual(result["fallback"]["source"], "route_not_connected")

    def test_every_reason_code_maps_to_a_strategy_except_other(self):
        expected = {
            "task_too_large": "shrink",
            "unclear_task": "shrink",
            "fatigue": "shrink",
            "time_shortage": "reschedule",
            "interruption": "reschedule",
            "underestimated": "reschedule",
            "priority_changed": "replan",
        }
        for reason, strategy in expected.items():
            with self.subTest(reason=reason):
                state = base_state()
                state["check_in"]["reason_code"] = reason
                if strategy == "replan":
                    state["planning_context"] = {"goal": "시험 준비"}

                result = build_adaptive_planner_graph(
                    lambda _state: {
                        "replaces_task_id": "task-1",
                        "tasks": [{"title": "작은 작업", "minutes": 10, "done_when": "완료"}],
                        "applied_reasons": ["작업 축소"],
                    }
                ).invoke(state)

                self.assertEqual(result["strategy"], strategy)

    def test_other_reason_asks_user_to_pick_strategy(self):
        state = base_state()
        state["check_in"]["reason_code"] = "other"

        result = build_adaptive_planner_graph(lambda _state: self.fail("generator must not run")).invoke(state)

        self.assertEqual(result["route"], "request_information")
        self.assertEqual(result["fallback"]["missing_fields"], ["strategy"])

    def test_user_chosen_strategy_overrides_reason(self):
        state = base_state()
        state["check_in"]["reason_code"] = "time_shortage"
        state["strategy"] = "shrink"

        result = build_adaptive_planner_graph(
            lambda _state: {
                "replaces_task_id": "task-1",
                "tasks": [{"title": "작은 작업", "minutes": 10, "done_when": "완료"}],
                "applied_reasons": ["사용자가 축소를 선택함"],
            }
        ).invoke(state)

        self.assertEqual(result["strategy"], "shrink")
        self.assertEqual(result["approval_status"], "waiting")

    def test_invalid_top_level_fields_request_information(self):
        for field, value in (("base_revision", -1), ("base_revision", "3"), ("user_id", " "), ("strategy", "skip")):
            with self.subTest(field=field, value=value):
                state = base_state()
                state[field] = value

                result = build_adaptive_planner_graph(lambda _state: self.fail("generator must not run")).invoke(state)

                self.assertEqual(result["fallback"]["invalid_fields"], [field])

    def test_profile_change_context_is_preserved(self):
        state = base_state()
        state["profile_change_context"] = {
            "before": {"block_minutes": 30}, "after": {"block_minutes": 20},
            "changed_fields": ["block_minutes"], "reason": "반복 미완료",
            "evidence_record_ids": ["record-1"], "source_profile_id": "old",
            "applied_profile_id": "new",
        }

        result = build_adaptive_planner_graph(
            lambda _state: {
                "replaces_task_id": "task-1",
                "tasks": [{"title": "작은 작업", "minutes": 10, "done_when": "완료"}],
                "applied_reasons": ["작업 축소"],
            }
        ).invoke(state)

        self.assertEqual(result["profile_change_context"], state["profile_change_context"])

    def test_shrink_without_schedule_style_asks_for_it(self):
        state = base_state()
        del state["execution_context"]["schedule_style"]

        result = build_adaptive_planner_graph(lambda _state: self.fail("generator must not run")).invoke(state)

        self.assertEqual(result["route"], "request_information")
        self.assertEqual(result["fallback"]["missing_fields"], ["execution_context.schedule_style"])

    def test_flexible_queue_shrink_needs_no_focus_minutes(self):
        state = base_state()
        state["execution_context"]["schedule_style"] = "flexible_queue"
        state["execution_context"]["focus_minutes"] = None

        # One 40-minute chunk with a smaller scope: too long for a 20-minute
        # focus session, but fine for a chunk planner.
        result = build_adaptive_planner_graph(
            lambda _state: {
                "replaces_task_id": "task-1",
                "tasks": [{"title": "슬라이드 목차와 핵심 문장만", "minutes": 40, "done_when": "목차와 문장 초안 완성"}],
                "applied_reasons": ["범위를 목차와 핵심 문장으로 줄임"],
            }
        ).invoke(state)

        self.assertEqual(result["approval_status"], "waiting")

    def test_shrink_total_must_be_shorter_than_original(self):
        # Seen with a real LLM: pieces that add up to exactly the original minutes.
        result = build_adaptive_planner_graph(
            lambda _state: {
                "replaces_task_id": "task-1",
                "tasks": [
                    {"title": f"조각 {i}", "minutes": 20, "done_when": "완료"} for i in range(3)
                ],
                "applied_reasons": ["축소"],
            },
            max_retries=0,
        ).invoke(base_state())

        self.assertEqual(result["approval_status"], "fallback")
        self.assertTrue(any(e.startswith("tasks: 축소 계획의 총 작업 시간") for e in result["fallback"]["validation_errors"]))

    def test_flexible_queue_still_requires_less_time_than_original(self):
        state = base_state()
        state["execution_context"]["schedule_style"] = "flexible_queue"

        result = build_adaptive_planner_graph(
            lambda _state: {
                "replaces_task_id": "task-1",
                "tasks": [{"title": "그대로", "minutes": 60, "done_when": "완료"}],
                "applied_reasons": ["그대로 둠"],
            },
            max_retries=0,
        ).invoke(state)

        self.assertEqual(result["approval_status"], "fallback")

    def test_time_blocks_rejects_piece_longer_than_focus(self):
        result = build_adaptive_planner_graph(
            lambda _state: {
                "replaces_task_id": "task-1",
                "tasks": [{"title": "긴 조각", "minutes": 40, "done_when": "완료"}],
                "applied_reasons": ["축소"],
            },
            max_retries=0,
        ).invoke(base_state())

        self.assertEqual(result["approval_status"], "fallback")
        self.assertTrue(any("집중 가능 시간" in e for e in result["fallback"]["validation_errors"]))

    def test_completed_task_continues_without_recovery_generation(self):
        state = base_state()
        state["check_in"]["completed"] = True

        result = build_adaptive_planner_graph(lambda _state: self.fail("generator must not run")).invoke(state)

        self.assertEqual(result["route"], "continue")
        self.assertEqual(result["approval_status"], "not_required")
        self.assertIsNone(result["draft"])


if __name__ == "__main__":
    unittest.main()
