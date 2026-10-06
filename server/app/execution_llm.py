"""Use the host app's configured OpenAI model; no secret reaches React."""
import json
import os
from openai import AsyncOpenAI, AuthenticationError, RateLimitError
from .planner import PlanGenerationError


class LLMUnavailableError(PlanGenerationError):
    """Missing key, rejected key or exhausted quota: retrying will not help."""


class ExecutionLLM:
    async def generate(self, *, schema, name, instructions, context):
        key = os.getenv("OPENAI_API_KEY", "").strip()
        if not key:
            raise LLMUnavailableError("서버에 OPENAI_API_KEY를 설정해 주세요.")
        try:
            async with AsyncOpenAI(api_key=key, timeout=60, max_retries=0) as client:
                result = await client.chat.completions.create(
                    model=os.getenv("OPENAI_PLAN_MODEL", "gpt-4o-mini"),
                    store=False, max_completion_tokens=6500,
                    messages=[{"role": "system", "content": instructions},
                              {"role": "user", "content": json.dumps(context, ensure_ascii=False)}],
                    response_format={"type": "json_schema", "json_schema": {
                        "name": name, "strict": True, "schema": schema}},
                )
            if not result.choices or result.choices[0].finish_reason != "stop" or not result.choices[0].message.content:
                raise PlanGenerationError("AI 응답이 완료되지 않았거나 요청이 거절되었습니다. 다시 시도해 주세요.")
            return json.loads(result.choices[0].message.content)
        except AuthenticationError as exc:
            raise LLMUnavailableError("등록된 API 키가 유효하지 않거나 무효화되었습니다. 새 키를 등록하고 서버를 다시 시작해 주세요.") from exc
        except RateLimitError as exc:
            raise LLMUnavailableError("API 사용 한도 또는 크레딧이 부족합니다. 잔액과 한도를 확인해 주세요.") from exc
        except PlanGenerationError:
            raise
        except Exception as exc:
            raise PlanGenerationError("AI 연결 또는 응답 처리에 실패했습니다. 다시 시도해 주세요.") from exc
