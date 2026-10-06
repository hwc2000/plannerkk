import json
import os
from typing import Any

from openai import AsyncOpenAI

from .planner import PlanDraft, PlanDraftRequest, PlanGenerationError, build_plan_prompt


class OpenAIPlanGenerator:
    def __init__(self, client: Any, model: str = "gpt-4o-mini"):
        self.client = client
        self.model = model

    @classmethod
    def from_env(cls):
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise PlanGenerationError("서버에 OPENAI_API_KEY가 설정되지 않았습니다.")
        model = os.getenv("OPENAI_PLAN_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
        if model != "gpt-4o-mini":
            raise PlanGenerationError("지원하지 않는 OPENAI_PLAN_MODEL입니다.")
        return cls(
            client=AsyncOpenAI(api_key=api_key, timeout=30.0, max_retries=1),
            model=model,
        )

    async def close(self):
        await self.client.close()

    async def generate(self, request: PlanDraftRequest) -> dict[str, Any]:
        prompt = build_plan_prompt(
            goal=request.goal,
            planning_context=request.planning_context,
            project=request.project.model_dump(by_alias=True, mode="json"),
            existing_tasks=[
                task.model_dump(by_alias=True, mode="json") for task in request.existingTasks
            ],
        )
        try:
            completion = await self.client.chat.completions.create(
                model=self.model,
                max_completion_tokens=2000,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "당신은 프로젝트 계획 초안을 만드는 도우미입니다. "
                            "사용자 검토 전에는 어떤 데이터도 저장하거나 확정하지 않습니다."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "project_plan_draft",
                        "strict": True,
                        "schema": PlanDraft.model_json_schema(by_alias=True),
                    },
                },
            )
            content = completion.choices[0].message.content
            if not content:
                raise PlanGenerationError("AI가 빈 계획을 반환했습니다.")
            return json.loads(content)
        except PlanGenerationError:
            raise
        except (json.JSONDecodeError, IndexError, AttributeError, TypeError) as exc:
            raise PlanGenerationError("AI가 유효한 JSON 계획을 반환하지 않았습니다.") from exc
        except Exception as exc:
            raise PlanGenerationError("OpenAI 요청에 실패했습니다.") from exc
