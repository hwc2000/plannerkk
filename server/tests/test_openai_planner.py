import os
import unittest
from unittest.mock import patch

from server.app.openai_planner import OpenAIPlanGenerator
from server.app.planner import PlanDraftRequest, PlanGenerationError


class FakeCompletions:
    def __init__(self, content):
        self.content = content
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        message = type("Message", (), {"content": self.content})()
        choice = type("Choice", (), {"message": message})()
        return type("Completion", (), {"choices": [choice]})()


class FakeClient:
    def __init__(self, content):
        self.completions = FakeCompletions(content)
        self.chat = type("Chat", (), {"completions": self.completions})()
        self.close_calls = 0

    async def close(self):
        self.close_calls += 1


REQUEST = PlanDraftRequest.model_validate({
    "goal": "AI 연동을 작은 단계로 나눠줘",
    "project": {
        "id": "project-1",
        "title": "PlannerKK",
        "goal": "AI 플래너 완성",
        "startDate": "2026-09-27",
        "dueDate": "2026-10-10",
    },
    "existingTasks": [],
})


class OpenAIPlanGeneratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_gpt_4o_mini_and_structured_json(self):
        client = FakeClient(
            '{"summary":"두 단계로 나눴습니다.","tasks":[{"title":"API 연결",'
            '"startDate":"2026-09-28","dueDate":"2026-09-29","estimatedHours":2}]}'
        )
        generator = OpenAIPlanGenerator(client=client)

        result = await generator.generate(REQUEST)

        self.assertEqual(result["tasks"][0]["title"], "API 연결")
        self.assertEqual(client.completions.kwargs["model"], "gpt-4o-mini")
        self.assertEqual(client.completions.kwargs["max_completion_tokens"], 2000)
        self.assertEqual(
            client.completions.kwargs["response_format"]["json_schema"]["name"],
            "project_plan_draft",
        )
        schema = client.completions.kwargs["response_format"]["json_schema"]["schema"]
        self.assertFalse(schema["additionalProperties"])
        self.assertFalse(schema["$defs"]["PlanTask"]["additionalProperties"])
        self.assertIn("PlannerKK", client.completions.kwargs["messages"][1]["content"])

    async def test_rejects_non_json_output(self):
        generator = OpenAIPlanGenerator(client=FakeClient("JSON이 아닌 응답"))
        with self.assertRaises(PlanGenerationError):
            await generator.generate(REQUEST)

    async def test_close_closes_the_underlying_client(self):
        client = FakeClient("")
        generator = OpenAIPlanGenerator(client=client)

        await generator.close()

        self.assertEqual(client.close_calls, 1)

    def test_requires_api_key_from_environment(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(PlanGenerationError):
                OpenAIPlanGenerator.from_env()

    def test_rejects_unsupported_model_from_environment(self):
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_PLAN_MODEL": "gpt-4o",
        }, clear=True):
            with self.assertRaises(PlanGenerationError):
                OpenAIPlanGenerator.from_env()

    def test_configures_client_cost_and_retry_boundaries(self):
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_PLAN_MODEL": "gpt-4o-mini",
        }, clear=True), patch("server.app.openai_planner.AsyncOpenAI") as client_class:
            OpenAIPlanGenerator.from_env()

        client_class.assert_called_once_with(
            api_key="test-key",
            timeout=30.0,
            max_retries=1,
        )


if __name__ == "__main__":
    unittest.main()
