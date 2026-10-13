"""Per-user plan policy and the reasons shown with each plan.

Every value comes from the user's own confirmed profile (declared answers,
planning preferences and approved learned patterns), so the same code serves
any number of users.  Reasons are built from the values the code applied, not
from LLM text, so a reason never claims something the plan did not do.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from ..execution_profile import generate_profile
from ..execution_scheduler import schedule
from .state import PREFERENCE_STRATEGY

# System boundaries for "when I focus best"; not user traits.
PERIODS = {"morning": (5, 12), "afternoon": (12, 18), "evening": (18, 24)}
MIN_HINT_PIECE = 10  # a day's leftover shorter than this is not worth a task
PERIOD_LABELS = {"morning": "오전", "afternoon": "오후", "evening": "저녁"}

Source = Literal["declared", "learned", "default", "profile", "memory"]
Placement = Literal["preferred", "mixed", "unavailable"]
Window = tuple[datetime, datetime]


@dataclass(frozen=True)
class PlanPolicy:
    block_minutes: int  # task length cap
    buffer_percent: int
    daily_cap_minutes: int | None
    starter_minutes: int | None
    preferred_period: str | None


def plan_policy(user_profile: Mapping[str, Any]) -> PlanPolicy:
    prefs = user_profile["planningPreferences"]
    energy = user_profile["declaredFacts"].get("energy")
    return PlanPolicy(
        block_minutes=prefs["blockMinutes"],
        buffer_percent=prefs["bufferPercent"],
        daily_cap_minutes=prefs.get("dailyPlannedMinutes"),
        starter_minutes=prefs.get("starterMinutes"),
        preferred_period=energy if energy in PERIODS else None,
    )


def day_task_minutes(policy: PlanPolicy) -> list[int]:
    """One day's task lengths that fill the daily cap, e.g. [50, 40] for 90 minutes with 50-minute blocks.

    Given to the LLM as a hint: tasks are placed in order, so a day of two
    50-minute blocks would not fit 90 minutes and push work out of the week.
    """
    if policy.daily_cap_minutes is None:
        return []
    left = policy.daily_cap_minutes - (policy.starter_minutes or 0)
    pieces = [policy.block_minutes] * (left // policy.block_minutes)
    if left % policy.block_minutes >= MIN_HINT_PIECE:
        pieces.append(left % policy.block_minutes)
    return pieces


def preferred_windows(windows: Sequence[Window], period: str) -> list[Window]:
    start_hour, end_hour = PERIODS[period]
    result = []
    for begin, end in windows:
        midnight = begin.replace(hour=0, minute=0, second=0, microsecond=0)
        low, high = max(begin, midnight + timedelta(hours=start_hour)), min(end, midnight + timedelta(hours=end_hour))
        if low < high:
            result.append((low, high))
    return result


def place_tasks(
    tasks: Sequence[Mapping[str, Any]], windows: Sequence[Window], policy: PlanPolicy,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Placement | None]:
    """Schedule in the preferred period when it holds as much as the whole week does."""
    def run(chosen: Sequence[Window]):
        return schedule(tasks, list(chosen), policy.buffer_percent,
                        daily_cap=policy.daily_cap_minutes, starter_minutes=policy.starter_minutes)

    entries, pending = run(windows)
    if policy.preferred_period is None:
        return entries, pending, None
    preferred = preferred_windows(windows, policy.preferred_period)
    if not preferred:
        return entries, pending, "unavailable"
    preferred_entries, preferred_pending = run(preferred)
    if len(preferred_pending) <= len(pending):
        return preferred_entries, preferred_pending, "preferred"
    return entries, pending, "mixed"


def _reason(key: str, applied: str, because: str, source: Source, fields: list[str]) -> dict[str, Any]:
    return {"key": key, "applied": applied, "because": because, "source": source, "fields": fields}


def _survey_preferences(facts: Mapping[str, Any]) -> dict[str, Any] | None:
    """What A's survey rule gives for these answers; a different stored value was set elsewhere."""
    try:
        return generate_profile({**facts, "constraints": "", "context": ""})["planningPreferences"]
    except (KeyError, TypeError, ValueError):
        return None


def _task_length(facts, prefs, survey, patterns) -> dict[str, Any]:
    block = prefs["blockMinutes"]
    applied = f"작업은 한 번에 {block}분 이하로 나눴습니다."
    for pattern in patterns:
        change = (pattern.get("proposedChanges") or {}).get("blockMinutes") or {}
        if change.get("to") == block:
            count = len(pattern.get("evidenceRecordIds") or [])
            return _reason("taskLength", applied,
                           f"최근 실행 기록 {count}건을 근거로 승인한 변경({change.get('from')}분 → {block}분)을 따랐습니다.",
                           "learned", ["learnedPatterns"])
    focus = facts.get("focusMinutes")
    if survey and survey["blockMinutes"] == block:
        if focus is None:
            return _reason("taskLength", applied,
                           f"집중 가능 시간을 아직 몰라 {block}분부터 시작합니다. 실행 기록이 쌓이면 조정을 제안합니다.",
                           "default", ["focusMinutes"])
        if focus == block:
            return _reason("taskLength", applied, f"확정한 집중 가능 시간 {focus}분에 맞췄습니다.",
                           "declared", ["focusMinutes"])
        return _reason("taskLength", applied,
                       f"답한 집중 가능 시간 {focus}분을 바탕으로 정한 초기 집중 구간 {block}분을 따랐습니다.",
                       "declared", ["focusMinutes"])
    return _reason("taskLength", applied, f"확정한 프로필의 집중 구간 {block}분을 따랐습니다.",
                   "profile", ["blockMinutes"])


def _starter(facts, prefs, survey) -> dict[str, Any]:
    minutes = prefs["starterMinutes"]
    applied = f"매일 첫 작업 앞에 {minutes}분짜리 시작 행동을 두었습니다."
    if survey and survey["starterMinutes"] == minutes and "starting" in facts.get("barriers", []):
        return _reason("starter", applied, "시작하기가 어렵다고 답했습니다.", "declared", ["barriers"])
    return _reason("starter", applied, f"확정한 프로필의 시작 작업 {minutes}분을 따랐습니다.", "profile", ["starterMinutes"])


def _daily_cap(facts, prefs, survey) -> dict[str, Any]:
    cap = prefs["dailyPlannedMinutes"]
    applied = f"하루에 최대 {cap}분만 계획했습니다."
    daily = facts.get("dailyMinutes")
    if survey and survey["dailyPlannedMinutes"] == cap and daily is not None:
        return _reason("dailyCap", applied,
                       f"하루에 쓸 수 있다고 답한 {daily}분에서 여유분 {prefs['bufferPercent']}%를 뺐습니다.",
                       "declared", ["dailyMinutes"])
    return _reason("dailyCap", applied, f"확정한 프로필의 하루 계획량 {cap}분을 따랐습니다.", "profile", ["dailyPlannedMinutes"])


def _buffer(facts, prefs, survey) -> dict[str, Any]:
    percent = prefs["bufferPercent"]
    applied = f"선택한 가용 시간의 {percent}% 이상을 여유분으로 비워 두었습니다."
    if survey and survey["bufferPercent"] == percent:
        regularity, barriers = facts.get("regularity"), facts.get("barriers", [])
        if regularity == "irregular":
            return _reason("buffer", applied, "일정이 불규칙하다고 답했습니다.", "declared", ["regularity"])
        if "overplanning" in barriers:
            return _reason("buffer", applied, "계획을 많이 세우는 편이라고 답했습니다.", "declared", ["barriers"])
        if regularity == "unknown":
            return _reason("buffer", applied, "일정이 규칙적인지 아직 몰라 여유를 넉넉히 두었습니다.", "default", ["regularity"])
        if regularity in ("regular", "mixed"):
            label = "규칙적" if regularity == "regular" else "어느 정도 규칙적"
            return _reason("buffer", applied, f"일정이 {label}이라고 답해 여유분을 적게 잡았습니다.", "declared", ["regularity"])
    return _reason("buffer", applied, f"확정한 프로필의 여유분 {percent}%를 따랐습니다.", "profile", ["bufferPercent"])


def _period(period: str, placement: Placement) -> dict[str, Any]:
    label = PERIOD_LABELS[period]
    because = f"{label}에 집중이 잘 된다고 답했습니다."
    if placement == "preferred":
        return _reason("period", f"작업을 {label} 시간에 배치했습니다.", because, "declared", ["energy"])
    if placement == "mixed":
        return _reason("period", f"{label} 시간에 먼저 배치하려 했지만 부족해 다른 시간대도 함께 썼습니다.",
                       because, "declared", ["energy"])
    return _reason("period", f"선택한 가용 시간에 {label} 시간이 없어 시간대 선호는 적용하지 못했습니다.",
                   because, "declared", ["energy"])


REGULARITY_ANSWERS = {
    "regular": "일정이 규칙적이라고 답했습니다.",
    "mixed": "일정이 어느 정도만 규칙적이라고 답했습니다.",
    "irregular": "일정이 불규칙하다고 답했습니다.",
    "unknown": "일정이 규칙적인지 아직 모른다고 답했습니다.",
}


def _schedule_style(facts, prefs, survey) -> dict[str, Any] | None:
    style, source = prefs.get("scheduleStyle"), prefs.get("scheduleStyleSource")
    applied = ("작업마다 시각을 정한 시간표로 배치했습니다." if style == "time_blocks"
               else "시각 대신 순서만 정한 할 일 목록으로 보여 줍니다.")
    if source == "user":
        return _reason("scheduleStyle", applied, "계획 방식을 직접 골랐습니다.", "declared", ["scheduleStyle"])
    if source == "rule" and survey and survey["scheduleStyle"] == style and facts.get("regularity") in REGULARITY_ANSWERS:
        return _reason("scheduleStyle", applied, REGULARITY_ANSWERS[facts["regularity"]], "declared", ["regularity"])
    return None


def _recovery(prefs) -> dict[str, Any] | None:
    preference = prefs.get("recoveryPreference")
    if PREFERENCE_STRATEGY.get(preference) == "shrink":
        return _reason("recovery", "계획이 틀어지면 할 일을 줄이는 안을 먼저 제안합니다.",
                       "계획이 틀어지면 할 일을 줄이는 편이라고 답했습니다.", "declared", ["recovery"])
    if PREFERENCE_STRATEGY.get(preference) == "reschedule":
        return _reason("recovery", "계획이 틀어지면 다른 시간으로 다시 잡는 안을 먼저 제안합니다.",
                       "계획이 틀어지면 시간을 다시 잡는 편이라고 답했습니다.", "declared", ["recovery"])
    return None


def personalization_reasons(
    user_profile: Mapping[str, Any],
    *,
    placement: Placement | None,
    starter_used: bool,
    memory_count: int = 0,
) -> list[dict[str, Any]]:
    """Explain each profile value the plan applied. Free-text survey notes never appear here."""
    facts, prefs = user_profile["declaredFacts"], user_profile["planningPreferences"]
    survey = _survey_preferences(facts)
    reasons = [_task_length(facts, prefs, survey, user_profile.get("learnedPatterns") or [])]
    if starter_used and prefs.get("starterMinutes"):
        reasons.append(_starter(facts, prefs, survey))
    if prefs.get("dailyPlannedMinutes"):
        reasons.append(_daily_cap(facts, prefs, survey))
    reasons.append(_buffer(facts, prefs, survey))
    if placement is not None:
        reasons.append(_period(facts["energy"], placement))
    reasons += [r for r in (_schedule_style(facts, prefs, survey), _recovery(prefs)) if r]
    if memory_count:
        reasons.append(_reason("memories", f"저장한 기억 {memory_count}개를 계획 생성에 참고 자료로 넘겼습니다.",
                               "사용자가 저장을 승인한 기억만 사용합니다.", "memory", ["memories"]))
    return reasons
