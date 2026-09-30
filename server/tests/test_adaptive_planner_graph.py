import math
import unittest

from server.app.adaptive_planner_graph import (
    build_adaptive_planner_graph,
    to_execution_context,
)


def base_state():
    return {
        "execution_context": {
            "focus_minutes": 20,
            "recovery_preference": "reduce",
            "recent_failure_count": 1,
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
    }


class AdaptivePlannerGraphTests(unittest.TestCase):
    def test_shared_schemas_are_converted_at_one_boundary(self):
        raw_profile = object()
        raw_records = [object()]
        seen = []

        def converter(profile, records):
            seen.append((profile, records))
            return {
                "focus_minutes": 25,
                "recovery_preference": "reduce",
                "recent_failure_count": 2,
            }

        context = to_execution_context(raw_profile, raw_records, converter=converter)

        self.assertEqual(seen, [(raw_profile, raw_records)])
        self.assertEqual(context["focus_minutes"], 25)
        self.assertEqual(context["recent_failure_count"], 2)

    def test_converter_does_not_invent_failure_count(self):
        context = to_execution_context(
            object(),
            [],
            converter=lambda _profile, _records: {
                "focus_minutes": 25,
                "recovery_preference": "reduce",
            },
        )

        self.assertIsNone(context["recent_failure_count"])

    def test_malformed_execution_context_integers_request_information(self):
        invalid_values = ("20", True, 20.0)
        for field in ("focus_minutes", "recent_failure_count"):
            for value in invalid_values:
                with self.subTest(field=field, value=value):
                    state = base_state()
                    state["execution_context"][field] = value

                    result = build_adaptive_planner_graph(
                        lambda _state: self.fail("generator must not run")
                    ).invoke(state)

                    self.assertEqual(result["route"], "request_information")
                    self.assertEqual(
                        result["fallback"]["invalid_fields"],
                        [f"execution_context.{field}"],
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

    def test_not_yet_connected_route_keeps_current_plan_explicitly(self):
        state = base_state()
        state["check_in"]["reason_code"] = "time_shortage"

        result = build_adaptive_planner_graph(lambda _state: self.fail("generator must not run")).invoke(state)

        self.assertEqual(result["route"], "reschedule")
        self.assertEqual(result["approval_status"], "fallback")
        self.assertEqual(result["fallback"]["action"], "keep_current_plan")
        self.assertEqual(result["fallback"]["source"], "route_not_connected")

    def test_large_task_uses_shrink_route_and_waits_for_approval(self):
        def generator(state):
            self.assertEqual(state["route"], "shrink")
            return {
                "replaces_task_id": "task-1",
                "tasks": [
                    {"title": "목차 작성", "minutes": 10, "done_when": "슬라이드 제목이 정해짐"},
                    {"title": "핵심 내용 작성", "minutes": 20, "done_when": "각 슬라이드 핵심 문장이 있음"},
                ],
                "applied_reasons": ["작업이 너무 크다는 실행 결과를 반영함"],
            }

        result = build_adaptive_planner_graph(generator).invoke(base_state())

        self.assertEqual(result["route"], "shrink")
        self.assertEqual(result["approval_status"], "waiting")
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["validation_errors"], [])
        self.assertEqual(len(result["recovery_draft"]["tasks"]), 2)

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
                self.assertIsNone(result["recovery_draft"])

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
            result["recovery_draft"],
            {
                "replaces_task_id": "task-1",
                "tasks": [
                    {"title": "작은 작업", "minutes": 10, "done_when": "완료"}
                ],
                "applied_reasons": ["작업 축소"],
            },
        )
        self.assertIsInstance(result["recovery_draft"]["tasks"], list)

    def test_max_retries_requires_bounded_strict_integer(self):
        invalid_values = (-1, 6, True, False, "2", 2.0, math.nan, math.inf, -math.inf)
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
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
        self.assertIsNone(result["recovery_draft"])

    def test_missing_focus_minutes_requests_input_instead_of_guessing(self):
        state = base_state()
        state["execution_context"]["focus_minutes"] = None

        result = build_adaptive_planner_graph(lambda _state: self.fail("generator must not run")).invoke(state)

        self.assertEqual(result["route"], "request_information")
        self.assertEqual(result["approval_status"], "needs_input")
        self.assertEqual(result["fallback"]["action"], "request_input")
        self.assertEqual(result["fallback"]["missing_fields"], ["execution_context.focus_minutes"])
        self.assertNotIn("used_value", result["fallback"])

    def test_completed_task_continues_without_recovery_generation(self):
        state = base_state()
        state["check_in"]["completed"] = True

        result = build_adaptive_planner_graph(lambda _state: self.fail("generator must not run")).invoke(state)

        self.assertEqual(result["route"], "continue")
        self.assertEqual(result["approval_status"], "not_required")
        self.assertIsNone(result["recovery_draft"])


if __name__ == "__main__":
    unittest.main()
