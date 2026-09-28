import unittest
from datetime import date

from server.app.planner import (
    PlanDraftRequest,
    PlanGenerationError,
    build_plan_prompt,
    parse_plan_for_project,
    parse_plan_payload,
)


class ParsePlanPayloadTests(unittest.TestCase):
    def test_accepts_valid_plan(self):
        result = parse_plan_payload({
            "summary": "실행 가능한 단계로 나눴습니다.",
            "tasks": [
                {
                    "title": "요구사항 정리",
                    "startDate": "2026-09-28",
                    "dueDate": "2026-09-29",
                    "estimatedHours": 2,
                }
            ],
        })
        self.assertEqual(result.tasks[0].title, "요구사항 정리")

    def test_rejects_reversed_date_range(self):
        with self.assertRaises(PlanGenerationError):
            parse_plan_payload({
                "summary": "잘못된 일정",
                "tasks": [
                    {
                        "title": "역순 일정",
                        "startDate": "2026-09-30",
                        "dueDate": "2026-09-28",
                        "estimatedHours": 1,
                    }
                ],
            })
    def test_rejects_task_outside_project_period(self):
        with self.assertRaises(PlanGenerationError):
            parse_plan_for_project(
                {
                    "summary": "기간 밖 일정",
                    "tasks": [
                        {
                            "title": "너무 늦은 작업",
                            "startDate": "2026-10-11",
                            "dueDate": "2026-10-12",
                            "estimatedHours": 2,
                        }
                    ],
                },
                project_start=date(2026, 9, 27),
                project_due=date(2026, 10, 10),
            )


class PromptTests(unittest.TestCase):
    def test_prompt_contains_user_goal_and_existing_context(self):
        prompt = build_plan_prompt(
            goal="졸업 작품 API 연결",
            project={"title": "PlannerKK", "goal": "AI 플래너 완성"},
            existing_tasks=[{"title": "CRUD 완성", "dueDate": "2026-09-27"}],
        )
        self.assertIn("졸업 작품 API 연결", prompt)
        self.assertIn("PlannerKK", prompt)
        self.assertIn("CRUD 완성", prompt)
        self.assertNotIn("Hermes", prompt)


class PlanDraftRequestTests(unittest.TestCase):
    def test_rejects_overlong_nested_project_fields(self):
        with self.assertRaises(ValueError):
            PlanDraftRequest.model_validate({
                "goal": "계획을 세워줘",
                "project": {
                    "id": "project-1",
                    "title": "가" * 121,
                    "goal": "AI 플래너 완성",
                    "startDate": "2026-09-27",
                    "dueDate": "2026-10-10",
                },
                "existingTasks": [],
            })

    def test_rejects_overlong_nested_existing_task_fields(self):
        with self.assertRaises(ValueError):
            PlanDraftRequest.model_validate({
                "goal": "계획을 세워줘",
                "project": {
                    "id": "project-1",
                    "title": "PlannerKK",
                    "goal": "AI 플래너 완성",
                    "startDate": "2026-09-27",
                    "dueDate": "2026-10-10",
                },
                "existingTasks": [{
                    "title": "가" * 121,
                    "startDate": "2026-09-28",
                    "dueDate": "2026-09-29",
                    "estimatedHours": 2,
                    "status": "todo",
                }],
            })


if __name__ == "__main__":
    unittest.main()
