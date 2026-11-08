"""Per-user plan policy and the reasons shown with each plan.

Every value comes from the user's own confirmed profile (declared answers,
planning preferences and approved learned patterns) with the project's own
settings on top, so the same code serves any number of users and projects.
Reasons are built from the values the code applied, not from LLM text, so a
reason never claims something the plan did not do.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from ..execution_profile import FOCUS_PERIODS, generate_profile
from ..execution_scheduler import BREAK_MINUTES, MIN_PIECE_MINUTES, min_task_minutes, schedule
from .state import PREFERENCE_STRATEGY

# System boundaries for "when I focus best"; not user traits.
PERIODS = FOCUS_PERIODS
PERIOD_LABELS = {"morning": "오전", "afternoon": "오후", "evening": "저녁"}

Source = Literal["declared", "learned", "default", "profile", "memory", "project"]
Placement = Literal["preferred", "mixed", "unavailable"]
Window = tuple[datetime, datetime]


@dataclass(frozen=True)
class PlanPolicy:
    block_minutes: int  # task length cap, in planned minutes
    daily_cap_minutes: int | None
    starter_minutes: int | None
    preferred_period: str | None
    pace_percent: int | None = None  # how long planned work really takes, in percent of the plan


def paced_block(prefs: Mapping[str, Any]) -> int:
    """Planned minutes of one task: the focus block is real time, and work takes ``pacePercent`` of its plan.

    Someone who focuses 60 minutes and needs 140% of every plan gets tasks of 42 planned
    minutes, which really take the 60 they can do in one go.
    """
    block, pace = prefs["blockMinutes"], prefs.get("pacePercent")
    return max(1, block * 100 // pace) if pace else block


def plan_policy(user_profile: Mapping[str, Any]) -> PlanPolicy:
    prefs = user_profile["planningPreferences"]
    focus = prefs.get("focusTime")
    return PlanPolicy(
        block_minutes=paced_block(prefs),
        daily_cap_minutes=prefs.get("dailyPlannedMinutes"),
        starter_minutes=prefs.get("starterMinutes"),
        preferred_period=focus if focus in PERIODS else None,
        pace_percent=prefs.get("pacePercent"),
    )


def block_is_start_value(user_profile: Mapping[str, Any]) -> bool:
    """True while the focus block is only the start value: the user did not know it and nothing set it since."""
    if user_profile["declaredFacts"].get("focusMinutes") is not None:
        return False
    if "blockMinutes" in (user_profile.get("projectOverrides") or {}):
        return False
    return not any("blockMinutes" in (p.get("proposedChanges") or {}) for p in user_profile.get("learnedPatterns") or [])


def _window_slots(room: int, block: int) -> list[int]:
    """Task lengths that fill ``room`` minutes: focus blocks with a break between, then what is left."""
    slots = []
    while room >= block:
        slots.append(block)
        room -= block + BREAK_MINUTES
    if room >= min_task_minutes(block):
        slots.append(room)
    elif room >= MIN_PIECE_MINUTES and slots:
        # Too short to stand alone: share it with the block before it (60 + 15 becomes 38 + 37).
        total = slots.pop() + room
        slots += [total - total // 2, total // 2]
    return slots


def day_slots(windows: Sequence[Window], policy: PlanPolicy, block: int,
              daily_used: Mapping[str, int] | None = None) -> list[dict[str, Any]]:
    """Each day's task lengths, in placement order, that use the time the plan may fill.

    The planner sizes tasks to these: three free hours with 60-minute blocks are
    60, 60 and 50 (breaks between).  The day's first task follows the starter, and
    a daily cap ends the day early, counting work other projects already hold that
    day (``daily_used``).  A leftover too short for a task stays free.
    """
    days: dict[str, list[int]] = {}
    used: dict[str, int] = {}
    for begin, end in windows:
        day = begin.date().isoformat()
        slots = days.setdefault(day, [])
        room = int((end - begin).total_seconds() // 60)
        if day not in used:
            used[day] = (daily_used or {}).get(day, 0) + (policy.starter_minutes or 0)
            room -= policy.starter_minutes or 0
        for minutes in _window_slots(room, block):
            if policy.daily_cap_minutes is not None and used[day] + minutes > policy.daily_cap_minutes:
                # The cap ends the day: what it leaves is a task only if it is not a sliver.
                minutes = policy.daily_cap_minutes - used[day]
                if minutes >= min_task_minutes(block):
                    slots.append(minutes)
                used[day] = max(used[day], policy.daily_cap_minutes)
                break
            slots.append(minutes)
            used[day] += minutes
    return [{"date": day, "minutes": slots} for day, slots in days.items() if slots]


MIN_SHAPED_MINUTES = 10  # a stretch shorter than this after shaping is not worth a task
# System value: the share of each chosen stretch that gets work.  The rest stays free, so a
# task that runs long, a break or something unplanned does not push the day over.
PLANNED_SHARE = 0.8


def shape_windows(windows: Sequence[Window], prefs: Mapping[str, Any]) -> list[Window]:
    """The chosen time as the plan may use it, after learned limits (approved values only).

    A part of the day with a learned length holds at most that many minutes per
    stretch, and when work takes ``pacePercent`` of its plan, only that share of
    each stretch is planned: the rest stays free for the work to run long.
    """
    pace = (prefs.get("pacePercent") or 100) / 100
    caps = prefs.get("periodMinutes") or {}
    shaped = []
    for begin, end in windows:
        minutes = (end - begin).total_seconds() / 60
        period = next((name for name, (low, high) in PERIODS.items() if low <= begin.hour < high), None)
        if period in caps:
            minutes = min(minutes, caps[period])
        minutes = int(minutes / pace)
        if minutes >= MIN_SHAPED_MINUTES:
            shaped.append((begin, begin + timedelta(minutes=minutes)))
    return shaped


def leave_free(windows: Sequence[Window], block: int, daily_cap: int | None = None,
               free_minutes: Mapping[str, float] | None = None, daily_used: Mapping[str, int] | None = None,
               share: float | None = None) -> list[Window]:
    """Keep ``PLANNED_SHARE`` of each stretch for work and leave the rest free.

    A stretch no longer than one task keeps that task.  Applied last, to the stretches
    the plan will use, so leaving time free never pulls in a part of the day the
    daily cap would not have used.  A day whose cap already leaves that share of its
    free time (``free_minutes``, before the cap picked) unplanned is left as it is: the
    free share is of the chosen time, not a second cut of what the person can do.
    """
    share = PLANNED_SHARE if share is None else share
    kept = []
    for begin, end in windows:
        minutes = (end - begin).total_seconds() / 60
        day = begin.date().isoformat()
        if daily_cap is not None and free_minutes and \
                daily_cap - (daily_used or {}).get(day, 0) <= share * free_minutes.get(day, 0):
            kept.append((begin, end))
            continue
        minutes = int(max(minutes * share, min(minutes, block)))
        if minutes >= MIN_SHAPED_MINUTES:
            kept.append((begin, begin + timedelta(minutes=minutes)))
    return kept


ODDS_DAYS = 28  # records this recent decide how likely each part of the day is picked


def period_odds(records: Sequence[Mapping[str, Any]], today: str) -> dict[str, float]:
    """How likely each part of the day is to be kept when a daily cap cuts the chosen time.

    (finished + 1) / (planned + 2) of the recent tasks planned in it: with no records every
    part is even, and a part that keeps going badly is still picked now and then, so it is
    tried again and the odds can change.
    """
    cutoff = (datetime.fromisoformat(today) - timedelta(days=ODDS_DAYS)).date().isoformat()
    counts: dict[str, list[int]] = {}
    for r in records:
        start = r.get("plannedStart") or ""
        if not start or start[:10] < cutoff:
            continue
        period = next((name for name, (low, high) in PERIODS.items() if low <= int(start[11:13]) < high), None)
        if period:
            item = counts.setdefault(period, [0, 0])
            item[0] += 1
            item[1] += r.get("result") == "completed"
    return {period: (finished + 1) / (planned + 2) for period, (planned, finished) in counts.items()}


def pick_windows_for_cap(windows: Sequence[Window], cap: int, odds: Mapping[str, float], seed: str,
                         preferred: str | None = None, daily_used: Mapping[str, int] | None = None) -> list[Window]:
    """Which of a day's chosen stretches a daily cap keeps: drawn by each part of the day's odds, not the earliest first.

    Whole stretches are kept (the scheduler still stops at the cap and keeps its breaks); a
    known best part of the day (approved or declared) is kept first.  Work other projects
    already hold that day (``daily_used``) counts against the cap.  The draw is seeded by
    the user and the day, so the same plan request gives the same week.
    """
    import random
    by_day: dict[str, list[Window]] = {}
    for window in windows:
        by_day.setdefault(window[0].date().isoformat(), []).append(window)
    kept: list[Window] = []
    for day, items in by_day.items():
        room = cap - (daily_used or {}).get(day, 0)
        if room <= 0:
            continue
        total = sum((end - begin).total_seconds() / 60 for begin, end in items)
        if total <= room:
            kept += items
            continue
        rng = random.Random(f"{seed}:{day}")
        left, chosen = room, []
        pool = [w for w in items if _period_of(w[0]) != preferred]
        for window in [w for w in items if _period_of(w[0]) == preferred]:
            if left > 0:
                chosen.append(window)
                left -= (window[1] - window[0]).total_seconds() / 60
        while pool and left > 0:
            weights = [odds.get(_period_of(begin), 0.5) for begin, _ in pool]
            window = pool.pop(rng.choices(range(len(pool)), weights=weights)[0])
            chosen.append(window)
            left -= (window[1] - window[0]).total_seconds() / 60
        kept += sorted(chosen)
    return kept


def _period_of(moment: datetime) -> str | None:
    return next((name for name, (low, high) in PERIODS.items() if low <= moment.hour < high), None)


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
    tasks: Sequence[Mapping[str, Any]], windows: Sequence[Window], policy: PlanPolicy, *, fill_daily_cap: bool = False,
    shrink_to_fit: bool = False, daily_used: Mapping[str, int] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Placement | None]:
    """Schedule in the preferred period when it holds as much as the whole week does."""
    def run(chosen: Sequence[Window]):
        return schedule(tasks, list(chosen), daily_cap=policy.daily_cap_minutes, starter_minutes=policy.starter_minutes,
                        fill_daily_cap=fill_daily_cap, shrink_to_fit=shrink_to_fit, daily_used=daily_used)

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


# Same wording as the survey options (src/features/execution/profileLabels.ts).
RECOVERY_LABELS = {"replan": "시간을 다시 배치", "reduce": "할 일을 줄임", "continue": "밀린 일을 건너뛰고 계속",
                   "abandon": "그날 계획을 포기", "unknown": "잘 모르겠어요"}


def _value_text(field: str, value: Any) -> str:
    if field == "recoveryPreference":
        return RECOVERY_LABELS.get(value, str(value))
    if value is None:
        return "없음"
    if field == "pacePercent":
        return f"{value}%"
    if field == "periodMinutes":
        return ", ".join(f"{PERIOD_LABELS[k]} {v}분" for k, v in value.items()) or "없음"
    return f"{value}분"


def _project_reason(key: str, applied: str, field: str, override: Mapping[str, Any], label: str,
                    patterns: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """A value this project overrides: set by the user for it, or learned from its records."""
    if override["source"] == "learned":
        pattern = next((p for p in patterns if p.get("approvedProposalId") == override.get("proposalId")), None)
        change = ((pattern or {}).get("proposedChanges") or {}).get(field) or {}
        if change:
            count = len(pattern.get("evidenceRecordIds") or [])
            because = (f"이 프로젝트의 실행 기록 {count}건을 근거로 승인한 변경"
                       f"({_value_text(field, change.get('from'))} → {_value_text(field, change.get('to'))})을 따랐습니다.")
        else:
            # e.g. a starter shortened along with an approved focus-block change
            because = f"이 프로젝트에서 승인한 변경에 맞춰 {label}을 조정했습니다."
        return _reason(key, applied, because, "learned", ["learnedPatterns"])
    base = override.get("baseValue")
    note = f" 기본 프로필 값은 {_value_text(field, base)}입니다." if base is not None else ""
    return _reason(key, applied, f"이 프로젝트에서 {label}을 따로 정했습니다.{note}", "project", [field])


def _task_length(facts, prefs, survey, patterns, overrides) -> dict[str, Any]:
    block = prefs["blockMinutes"]
    planned = paced_block(prefs)
    applied = (f"작업은 한 번에 {block}분 이하로 나눴습니다." if planned == block
               else f"작업은 계획상 {planned}분 이하로 나눴습니다(실제로는 {block}분쯤 걸리는 양).")
    if "blockMinutes" in overrides:
        return _project_reason("taskLength", applied, "blockMinutes", overrides["blockMinutes"], "집중 구간", patterns)
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
        return _reason("dailyCap", applied, f"하루에 쓸 수 있다고 답한 {daily}분에 맞췄습니다.", "declared", ["dailyMinutes"])
    return _reason("dailyCap", applied, f"확정한 프로필의 하루 계획량 {cap}분을 따랐습니다.", "profile", ["dailyPlannedMinutes"])


def _period(prefs, patterns, placement: Placement) -> dict[str, Any]:
    period = prefs["focusTime"]
    label = PERIOD_LABELS[period]
    learned = next((p for p in patterns if ((p.get("proposedChanges") or {}).get("focusTime") or {}).get("to") == period), None)
    if learned:
        count = len(learned.get("evidenceRecordIds") or [])
        because, source, fields = (f"실행 기록 {count}건에서 {label}에 계획한 작업을 더 잘 끝내 승인한 시간대입니다.",
                                   "learned", ["learnedPatterns"])
    else:
        because, source, fields = f"{label}에 집중이 잘 된다고 답했습니다.", "declared", ["energy"]
    if placement == "preferred":
        return _reason("period", f"작업을 {label} 시간에 배치했습니다.", because, source, fields)
    if placement == "mixed":
        return _reason("period", f"{label} 시간에 먼저 배치하려 했지만 부족해 다른 시간대도 함께 썼습니다.",
                       because, source, fields)
    return _reason("period", f"선택한 가용 시간에 {label} 시간이 없어 시간대 선호는 적용하지 못했습니다.",
                   because, source, fields)


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
    fill: str = "free",
) -> list[dict[str, Any]]:
    """Explain each profile value the plan applied. Free-text survey notes never appear here."""
    facts, prefs = user_profile["declaredFacts"], user_profile["planningPreferences"]
    patterns = user_profile.get("learnedPatterns") or []
    overrides = user_profile.get("projectOverrides") or {}
    survey = _survey_preferences(facts)

    def project_or(key, applied, field, label, fallback):
        if field in overrides:
            return _project_reason(key, applied, field, overrides[field], label, patterns)
        return fallback()

    reasons = [_task_length(facts, prefs, survey, patterns, overrides)]
    if starter_used and prefs.get("starterMinutes"):
        reasons.append(project_or("starter", f"매일 첫 작업 앞에 {prefs['starterMinutes']}분짜리 시작 행동을 두었습니다.",
                                  "starterMinutes", "시작 행동 시간", lambda: _starter(facts, prefs, survey)))
    if prefs.get("dailyPlannedMinutes"):
        reasons.append(project_or("dailyCap", f"하루에 최대 {prefs['dailyPlannedMinutes']}분만 계획했습니다.",
                                  "dailyPlannedMinutes", "하루 계획량", lambda: _daily_cap(facts, prefs, survey)))
    if prefs.get("pacePercent"):
        pace = prefs["pacePercent"]
        reasons.append(project_or("pace", f"작업이 계획한 시간의 {pace}%쯤 걸려서, 고른 시간의 {round(10000 / pace)}%만 작업으로 채우고 나머지는 비웠습니다.",
                                  "pacePercent", "걸리는 시간",
                                  lambda: _reason("pace", f"고른 시간의 {round(10000 / pace)}%만 작업으로 채웠습니다.",
                                                  f"확정한 프로필의 걸리는 시간 {pace}%를 따랐습니다.", "profile", ["pacePercent"])))
    if prefs.get("periodMinutes"):
        text = ", ".join(f"{PERIOD_LABELS[k]}에는 한 번에 {v}분까지" for k, v in prefs["periodMinutes"].items())
        reasons.append(project_or("periodLength", f"{text}만 계획했습니다.", "periodMinutes", "시간대별 길이",
                                  lambda: _reason("periodLength", f"{text}만 계획했습니다.",
                                                  "확정한 프로필의 시간대별 길이를 따랐습니다.", "profile", ["periodMinutes"])))
    if prefs.get("timeSlots"):
        from ..project_profile import slots_text
        reasons.append(_reason("ownHours", f"이 프로젝트는 정한 요일·시간({slots_text(prefs['timeSlots'])})에만 넣었습니다.",
                               "이 프로젝트를 하는 요일·시간을 직접 정했습니다.", "project", ["timeSlots"]))
    if fill == "full":
        reasons.append(_reason("freeTime", "고른 시간을 비우지 않고 채웠습니다.", "고른 시간을 다 채워 달라고 했습니다.", "declared", ["fill"]))
    else:
        reasons.append(_reason("freeTime", f"고른 시간의 {round(PLANNED_SHARE * 100)}%쯤만 작업으로 채우고 나머지는 비워 두었습니다.",
                               "일이 예상보다 길어지거나 쉬어 갈 때를 위한 여유입니다. ‘다 채워 줘’라고 하면 비우지 않아요.", "default", []))
    if placement is not None:
        reasons.append(_period(prefs, patterns, placement))
    style = _schedule_style(facts, prefs, survey)
    recovery = _recovery(prefs)
    if recovery and "recoveryPreference" in overrides:
        recovery = _project_reason("recovery", recovery["applied"], "recoveryPreference",
                                   overrides["recoveryPreference"], "복구 방식", patterns)
    reasons += [r for r in (style, recovery) if r]
    if memory_count:
        reasons.append(_reason("memories", f"저장한 기억 {memory_count}개를 계획 생성에 참고 자료로 넘겼습니다.",
                               "사용자가 저장을 승인한 기억만 사용합니다.", "memory", ["memories"]))
    return reasons


def project_task_length_reasons(projects: Sequence[Mapping[str, Any]],
                                settings: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """In a week of several projects, name each project whose tasks follow its own focus block."""
    reasons = []
    for project in projects:
        profile = (settings.get(project["id"]) or {}).get("user_profile")
        overrides = (profile or {}).get("projectOverrides") or {}
        slots = (profile or {}).get("planningPreferences", {}).get("timeSlots")
        if slots:
            from ..project_profile import slots_text
            reasons.append(_reason(f"ownHours:{project['id']}", f"‘{project['title']}’은 정한 요일·시간({slots_text(slots)})에만 넣었습니다.",
                                   "이 프로젝트를 하는 요일·시간을 직접 정했습니다.", "project", ["timeSlots"]))
        if "blockMinutes" not in overrides:
            continue
        facts, prefs = profile["declaredFacts"], profile["planningPreferences"]
        reason = _task_length(facts, prefs, _survey_preferences(facts), profile.get("learnedPatterns") or [], overrides)
        reasons.append({**reason, "key": f"taskLength:{project['id']}", "applied": f"‘{project['title']}’ {reason['applied']}"})
    return reasons
