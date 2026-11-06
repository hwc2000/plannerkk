"""Check-in words written fresh by an AI for each day, checked against the truth by code.

The words are written by the app's own model (``OPENAI_PLAN_MODEL``, now
gpt-6.1-terra) unless ``SIM_WRITER_MODEL`` names another one.  A different
writer would keep the reader from getting text in its own style; the team chose
one model for both on 2026-11-07, so the reading score may read a little high.  The writer reports what it actually said (minutes, reasons, how
the day went); code checks every stated fact against what really happened and
retries, then falls back to the fixed sentences in behavior.py.  The reading
test scores the app against what the words say, never against what was not said.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

from openai import OpenAI

MODEL = os.getenv("SIM_WRITER_MODEL") or os.getenv("OPENAI_PLAN_MODEL") or "gpt-6.1-terra"
ATTEMPTS = 2
REASONS = ["time_shortage", "task_too_large", "fatigue", "interruption", "underestimated"]
LEVELS = ["good", "ok", "poor"]

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["text", "tasks", "day"],
    "properties": {
        "text": {"type": "string"},
        "tasks": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["title", "minutes", "reason"],
            "properties": {"title": {"type": "string"}, "minutes": {"type": ["integer", "null"]},
                           "reason": {"type": ["string", "null"], "enum": [*REASONS, None]}}}},
        "day": {"type": "object", "additionalProperties": False, "required": ["focus", "condition"],
                "properties": {"focus": {"type": ["string", "null"], "enum": [*LEVELS, None]},
                               "condition": {"type": ["string", "null"], "enum": [*LEVELS, None]}}},
    },
}

INSTRUCTIONS = (
    "너는 공부 플래너 앱을 쓰는 사람이다. 오늘 계획한 작업을 버튼으로 표시한 뒤, 체크인 칸에 오늘 어땠는지 직접 쓴다. "
    "facts에 있는 사실만 쓰고, 없는 사실(다른 작업, 다른 숫자, 다른 이유)을 만들지 않는다. 말투는 style을 따른다. "
    "작업마다 얼마나 했는지·왜 못 했는지를 말할지는 자유다. 분을 말하면 facts의 minutes와 정확히 같은 수를 '40분'처럼 "
    "숫자와 '분'으로 쓴다(시간 단위, 범위, '쯤'만 있는 숫자 없는 표현은 괜찮지만 그때는 minutes를 null로 둔다). "
    "이유를 말하면 facts의 reason과 같은 뜻이어야 한다. 작업 이름은 알아볼 수 있게 줄여도 된다. "
    "day의 집중·컨디션은 말해도 되고 안 해도 된다. 말하면 facts.day와 같은 뜻이어야 한다. "
    "answers는 오늘 앱이 물어본 질문에 대한 그 사람의 평소 모습이다: 뜻을 바꾸지 말고 자기 말로 답한다(장소 이름은 그대로). "
    "remark가 있으면 그 문장을 그대로 한 번 넣는다. "
    "그리고 tasks에는 text에서 네가 실제로 말한 것만 적는다: 작업마다 facts의 title, 말한 분(말 안 했으면 null), "
    "말한 이유(말 안 했으면 null). day에는 text에서 말한 집중·컨디션(말 안 했으면 null)."
)

STYLES = {
    "plain": "평범한 존댓말, 두세 문장",
    "casual": "아주 짧은 반말이나 대충 몇 마디, 숫자를 자주 빼먹음",
}


def client():
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"].strip(), timeout=60, max_retries=1)


def facts_for(outcomes, session, answers, remark):
    return {
        "tasks": [{"title": o.title, "result": {"completed": "다 함", "partial": "조금 함", "not_started": "못 함"}[o.result],
                   "minutes": o.actual if o.result != "not_started" else None, "reason": o.reason,
                   "plannedMinutes": o.planned} for o in outcomes],
        "day": {"focus": session["focus"], "condition": session["condition"], "place": session["place"]},
        "answers": answers, "remark": remark,
    }


def check(said, outcomes, session):
    """Problems with what the writer claims to have said; empty when every stated fact is true."""
    problems = []
    text = said.get("text") or ""
    by_title = {o.title: o for o in outcomes}
    stated = {}
    for item in said.get("tasks") or []:
        o = by_title.get(item.get("title"))
        if o is None:
            problems.append(f"없는 작업: {item.get('title')}")
            continue
        stated[o.task_id] = item
        minutes, reason = item.get("minutes"), item.get("reason")
        if minutes is not None:
            if o.result == "not_started" or minutes != o.actual:
                problems.append(f"{o.title}: {minutes}분은 사실이 아님 ({o.actual}분)")
            elif f"{minutes}분" not in text.replace(" 분", "분"):
                problems.append(f"{o.title}: {minutes}분이 글에 없음")
        if reason is not None and (o.result == "completed" or reason != o.reason):
            problems.append(f"{o.title}: 이유 {reason}는 사실이 아님 ({o.reason})")
    allowed = {o.actual for o in outcomes}
    for number in re.findall(r"(\d+)\s*분", text):
        if int(number) not in allowed:
            problems.append(f"글에 사실이 아닌 {number}분")
    for field in ("focus", "condition"):
        value = (said.get("day") or {}).get(field)
        if value is not None and value != session[field]:
            problems.append(f"하루 {field}: {value}는 사실이 아님 ({session[field]})")
    if not text.strip():
        problems.append("빈 글")
    return problems, stated


def write(persona, outcomes, session, answers, remark, log):
    """(text, {task_id: (minutes, reason)}, day said) written by the AI and checked; None when it never passes."""
    facts = facts_for(outcomes, session, answers, remark)
    style = STYLES.get(persona.phrasing, persona.phrasing)
    feedback = []
    with client() as api:
        for attempt in range(ATTEMPTS):
            context = {"style": style, "facts": facts, **({"previousProblems": feedback} if feedback else {})}
            entry = {"name": "sim_writer", "model": MODEL, "attempt": attempt + 1,
                     "at": datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="minutes")}
            try:
                result = api.chat.completions.create(
                    model=MODEL, messages=[{"role": "system", "content": INSTRUCTIONS},
                                           {"role": "user", "content": json.dumps(context, ensure_ascii=False)}],
                    response_format={"type": "json_schema", "json_schema": {"name": "checkin_words", "strict": True, "schema": SCHEMA}})
                said = json.loads(result.choices[0].message.content)
            except Exception as exc:  # noqa: BLE001 - a failed write falls back to fixed sentences
                entry.update(ok=False, error=f"{type(exc).__name__}: {exc}")
                log.append(entry)
                continue
            problems, stated = check(said, outcomes, session)
            entry.update(ok=not problems, problems=problems, text=said.get("text"))
            log.append(entry)
            if not problems:
                per_task = {o.task_id: ((stated.get(o.task_id) or {}).get("minutes"), (stated.get(o.task_id) or {}).get("reason"))
                            for o in outcomes}
                return said["text"], per_task, {k: (said.get("day") or {}).get(k) for k in ("focus", "condition")}
            feedback = problems
    return None
