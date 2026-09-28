"""Validated onboarding facts and provisional planning preferences."""
import json
from datetime import datetime, timezone

OPTIONS = {
    "roles": ["student", "employee", "job_seeker", "freelancer", "other"],
    "regularity": ["regular", "mixed", "irregular", "unknown"],
    "barriers": ["starting", "overplanning", "distraction", "fatigue", "interruptions", "unclear", "none", "unknown"],
    "recovery": ["replan", "reduce", "continue", "abandon", "unknown"],
    "energy": ["morning", "afternoon", "evening", "variable", "unknown"],
}

def validate_answers(value):
    if not isinstance(value, dict):
        raise ValueError("답변은 JSON 객체여야 합니다.")
    result = {}
    for key, choices in OPTIONS.items():
        v = value.get(key)
        if key in ("roles", "barriers"):
            if not isinstance(v, list) or not v or any(not isinstance(x, str) or x not in choices for x in v) or len(set(v)) != len(v):
                raise ValueError(f"{key}: 항목을 선택해 주세요.")
            if key == "barriers" and len(v) > 1 and ("none" in v or "unknown" in v):
                raise ValueError("어려움 없음 / 잘 모르겠어요는 단독으로 선택해 주세요.")
        elif not isinstance(v, str) or v not in choices:
            raise ValueError(f"{key}: 올바른 항목을 선택해 주세요.")
        result[key] = v
    for key, upper in (("focusMinutes", 180), ("dailyMinutes", 720)):
        v = value.get(key)
        if v is not None and (type(v) is not int or not 5 <= v <= upper):
            raise ValueError(f"{key}: 5~{upper}분 또는 모름을 입력해 주세요.")
        result[key] = v
    for key in ("constraints", "context"):
        v = value.get(key, "")
        if not isinstance(v, str) or len(v) > 1500:
            raise ValueError("추가 설명은 각각 1,500자 이내로 입력해 주세요.")
        result[key] = v.strip()
    return result

def object_schema(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

SCHEMA = object_schema({
    "summary": {"type": "string"},
    "strategies": {"type": "array", "items": object_schema({"action": {"type": "string"}, "reason": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string", "enum": list(OPTIONS) + ["focusMinutes", "dailyMinutes", "constraints", "context"]}}})},
    "followUpQuestions": {"type": "array", "items": {"type": "string"}},
})

def validate_insights(data):
    if not isinstance(data, dict) or set(data) != set(SCHEMA["properties"]):
        raise ValueError("LLM 응답 형식이 올바르지 않습니다.")
    if not isinstance(data["summary"], str) or not 1 <= len(data["summary"]) <= 2000:
        raise ValueError("LLM 요약이 올바르지 않습니다.")
    strategies = data["strategies"]
    if not isinstance(strategies, list) or not 1 <= len(strategies) <= 6:
        raise ValueError("LLM 전략 개수가 올바르지 않습니다.")
    fields = set(OPTIONS) | {"focusMinutes", "dailyMinutes", "constraints", "context"}
    for s in strategies:
        if not isinstance(s, dict) or set(s) != {"action", "reason", "evidence"} or any(not isinstance(s[k], str) or not 1 <= len(s[k]) <= 1500 for k in ("action", "reason")):
            raise ValueError("LLM 전략 형식이 올바르지 않습니다.")
        if not isinstance(s["evidence"], list) or not s["evidence"] or any(not isinstance(e, str) or e not in fields for e in s["evidence"]):
            raise ValueError("LLM 근거가 올바르지 않습니다.")
    qs = data["followUpQuestions"]
    if not isinstance(qs, list) or len(qs) > 4 or any(not isinstance(q, str) or not 1 <= len(q) <= 500 for q in qs):
        raise ValueError("LLM 후속 질문이 올바르지 않습니다.")
    return data

def generate_profile(raw):
    mode = "demo"
    a = validate_answers(raw)
    if mode not in ("demo", "llm"):
        raise ValueError("지원하지 않는 생성 방식입니다.")
    focus = a["focusMinutes"]
    daily = a["dailyMinutes"]
    block = min(focus or 15, daily or 180, 50)
    if "distraction" in a["barriers"]:
        block = min(block, 20)
    buffer = 40 if a["regularity"] in ("irregular", "unknown") or "overplanning" in a["barriers"] else 25
    prefs = {
        "blockMinutes": block, "breakMinutes": 5,
        "bufferPercent": buffer,
        "dailyPlannedMinutes": int(daily * (100 - buffer) / 100) if daily else None,
        "scheduleStyle": "time_blocks" if a["regularity"] == "regular" else "flexible_queue",
        "recoveryPreference": a["recovery"],
        "starterMinutes": min(5, block) if "starting" in a["barriers"] else None,
        "status": "provisional",
    }
    if prefs["dailyPlannedMinutes"] is not None:
        prefs["blockMinutes"] = min(block, prefs["dailyPlannedMinutes"])
        if prefs["starterMinutes"] is not None:
            prefs["starterMinutes"] = min(prefs["starterMinutes"], prefs["blockMinutes"])
    strategies = [{"action": f"첫 집중 구간을 {prefs['blockMinutes']}분으로 시도해 보세요.", "reason": "응답한 집중 시간과 하루 여유 시간을 상한으로 둔 초기 제안입니다. 모르는 경우 15분부터 탐색합니다.", "evidence": ["focusMinutes", "dailyMinutes"]}]
    actions = {
        "starting": ("첫 행동을 5분 이내로 줄이기", "시작이 어렵다는 응답에 맞춰 준비와 첫 행동을 분리합니다."),
        "overplanning": ("하루 여유 시간의 40%를 비워 두기", "계획량이 많다는 응답을 반영한 초기 여유분입니다."),
        "distraction": ("한 구간에 한 작업만 배치하기", "집중이 흐트러지는 상황에서 전환 횟수를 줄여 봅니다."),
        "fatigue": ("힘이 덜 드는 대체 작업 준비하기", "피곤한 날에도 작업량을 조절할 수 있게 합니다."),
        "interruptions": ("중단할 때 다음 행동 한 줄 남기기", "다시 시작하는 부담을 줄여 봅니다."),
        "unclear": ("완료 조건을 한 문장으로 정하기", "무엇부터 해야 할지 모르는 상황을 줄여 봅니다."),
    }
    for barrier in a["barriers"]:
        if barrier in actions and len(strategies) < 6:
            action, reason = actions[barrier]
            strategies.append({"action": action, "reason": reason, "evidence": ["barriers"]})
    questions = []
    if focus is None:
        questions.append("최근 방해 없이 한 가지 일을 했던 시간은 대략 몇 분이었나요?")
    if daily is None:
        questions.append("필수 일정을 제외하고 하루에 확보할 수 있는 시간은 어느 정도인가요?")
    if focus and daily and focus > daily:
        questions.append("집중 가능 시간이 하루 여유 시간보다 깁니다. 서로 다른 상황을 기준으로 답하셨나요?")
    if a["recovery"] in ("abandon", "unknown"):
        questions.append("계획이 틀어졌을 때 작업량 줄이기와 시간 다시 잡기 중 무엇이 덜 부담스러울까요?")
    insights = {"summary": "답변을 바탕으로 만든 첫 실행 프로필입니다. 제안한 시간과 여유분은 실제 실행 후 조정할 초기값입니다.", "strategies": strategies, "followUpQuestions": questions}
    return {"schemaVersion": "1.0", "createdAt": datetime.now(timezone.utc).isoformat(), "source": mode, "status": "draft", "facts": a, "planningPreferences": prefs, "insights": insights}
