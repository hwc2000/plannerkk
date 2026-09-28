import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from server.app.main import create_app


class FakeGenerator:
    async def generate(self, request):
        return {
            "summary": f"{request.project.title} 계획",
            "tasks": [
                {
                    "title": "API 연결",
                    "startDate": "2026-09-28",
                    "dueDate": "2026-09-29",
                    "estimatedHours": 2,
                }
            ],
        }


class OutOfRangeGenerator:
    async def generate(self, request):
        return {
            "summary": "프로젝트 기간 밖 계획",
            "tasks": [{
                "title": "늦은 작업",
                "startDate": "2026-10-11",
                "dueDate": "2026-10-12",
                "estimatedHours": 2,
            }],
        }


class ClosableGenerator(FakeGenerator):
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.close_calls = 0

    async def generate(self, request):
        if self.should_fail:
            raise RuntimeError("generation failed")
        return await super().generate(request)

    async def close(self):
        self.close_calls += 1


class PlanDraftApiTests(unittest.TestCase):
    request_payload = {
        "goal": "AI 연동을 작은 단계로 나눠줘",
        "project": {
            "id": "project-1",
            "title": "PlannerKK",
            "goal": "AI 플래너 완성",
            "startDate": "2026-09-27",
            "dueDate": "2026-10-10",
        },
        "existingTasks": [],
    }
    def test_health_endpoint(self):
        client = TestClient(create_app(generator=FakeGenerator()))
        response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_project_overview_endpoint_survives_execution_integration(self):
        with TestClient(create_app(generator=FakeGenerator())) as client:
            response = client.get("/api/projects/project-1/overview")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["projectId"], "project-1")
        # Completed estimated hours: 15 of 35.
        self.assertEqual(response.json()["progressPercent"], 43)

    def test_returns_structured_plan_without_persisting_it(self):
        client = TestClient(create_app(generator=FakeGenerator()))
        response = client.post(
            "/api/ai/plan-draft",
            json={
                "goal": "AI 연동을 작은 단계로 나눠줘",
                "project": {
                    "id": "project-1",
                    "title": "PlannerKK",
                    "goal": "AI 플래너 완성",
                    "startDate": "2026-09-27",
                    "dueDate": "2026-10-10",
                },
                "existingTasks": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tasks"][0]["title"], "API 연결")
        self.assertNotIn("saved", response.json())

    def test_rejects_generated_tasks_outside_project_period(self):
        client = TestClient(create_app(generator=OutOfRangeGenerator()))
        response = client.post(
            "/api/ai/plan-draft",
            json={
                "goal": "AI 연동을 작은 단계로 나눠줘",
                "project": {
                    "id": "project-1",
                    "title": "PlannerKK",
                    "goal": "AI 플래너 완성",
                    "startDate": "2026-09-27",
                    "dueDate": "2026-10-10",
                },
                "existingTasks": [],
            },
        )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "AI가 프로젝트 기간을 벗어난 계획을 반환했습니다.")

    def test_closes_default_generator_after_success_and_failure(self):
        for should_fail, expected_status in ((False, 200), (True, 502)):
            with self.subTest(should_fail=should_fail):
                generator = ClosableGenerator(should_fail=should_fail)
                with patch(
                    "server.app.openai_planner.OpenAIPlanGenerator.from_env",
                    return_value=generator,
                ):
                    response = TestClient(create_app()).post(
                        "/api/ai/plan-draft",
                        json=self.request_payload,
                    )
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(generator.close_calls, 1)

    def test_does_not_close_injected_generator(self):
        generator = ClosableGenerator()
        response = TestClient(create_app(generator=generator)).post(
            "/api/ai/plan-draft",
            json=self.request_payload,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(generator.close_calls, 0)


if __name__ == "__main__":
    unittest.main()


class LegacyProjectRequestTests(unittest.TestCase):
    def test_full_project_from_older_client_is_accepted(self):
        payload = {**PlanDraftApiTests.request_payload, "project": {**PlanDraftApiTests.request_payload["project"], "priority":"high", "status":"active"}}
        response = TestClient(create_app(generator=FakeGenerator())).post("/api/ai/plan-draft", json=payload)
        self.assertEqual(response.status_code, 200)

    def test_invalid_input_has_readable_detail(self):
        payload = {**PlanDraftApiTests.request_payload, "goal":"a"}
        response = TestClient(create_app(generator=FakeGenerator())).post("/api/ai/plan-draft", json=payload)
        self.assertEqual(response.status_code, 422)
        self.assertIsInstance(response.json()["detail"], str)
