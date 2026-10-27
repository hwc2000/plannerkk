"""Approved global declarations and provisional, dated check-in evidence.

Declarations retain the UI's raw value/history without claiming established habits.
Independent calendar days provide scoped associations, never personality or causal
inferences. AI suggestions remain optional and varied; this module never changes
plans, task titles, or UserProfile. All operations are in-memory and deterministic
apart from the injectable clock.
"""
from datetime import datetime, timedelta, timezone

ASK_PER_CHECK_IN = 2
ASK_AGAIN_AFTER = timedelta(days=3)  # a skipped question waits before it comes back
HISTORY = 5
KST = timezone(timedelta(hours=9))

# key: (label, question, choices or None for free text).  Order is the order they are asked in.
SLOTS = {
    "tone": ("말투", "제가 어떤 말투로 얘기하면 편하세요? 편한 반말도, 지금 같은 존댓말도 괜찮아요.",
             {"casual": "편한 반말", "polite": "존댓말"}),
    "place": ("주로 하는 곳", "주로 어디서 공부하거나 일하세요?", None),
    "atmosphere": ("잘 맞는 분위기", "어떤 분위기에서 잘 되세요? 조용한 곳(도서관 같은), 적당히 소리 있는 열린 곳(카페 같은), 상관없음 중에서요.",
                   {"quiet": "조용한 곳", "lively": "적당히 소리 있는 열린 곳", "any": "상관없음"}),
    "focus_aids": ("집중에 도움 되는 습관", "집중할 때 도움이 되는 습관이 있어요? 음악, 휴대폰 멀리 두기 같은 거요.", None),
    "distractions": ("집중이 깨지는 이유", "주로 무엇 때문에 집중이 깨지세요?", None),
    "task_order": ("일하는 순서", "할 일이 여러 개면 어려운 것부터 하세요, 쉬운 것부터 하세요?",
                   {"hard_first": "어려운 것부터", "easy_first": "쉬운 것부터", "any": "상관없음"}),
    "condition": ("컨디션에 영향 주는 것", "컨디션에 영향을 많이 주는 게 있어요? 잠, 식사, 운동 같은 거요.", None),
    "rest": ("쉬는 방식", "쉴 때는 어떻게 쉬는 게 잘 맞아요?", None),
}


def _now():
    return datetime.now(KST)


def _local_time(value):
    """Aware instants convert to KST; naive check-in times already mean KST."""
    return value.replace(tzinfo=KST) if value.tzinfo is None else value.astimezone(KST)


def next_questions(state, now=None):
    """Up to two empty fields to ask about, skipping the ones asked lately."""
    now = now or _now()
    known = state.get("userInsights") or {}
    asked = state.get("insightAsks") or {}
    due = [key for key in SLOTS if key not in known
           and (key not in asked or now - datetime.fromisoformat(asked[key]) >= ASK_AGAIN_AFTER)]
    return [{"key": key, "label": SLOTS[key][0], "question": SLOTS[key][1]} for key in due[:ASK_PER_CHECK_IN]]


def clean_value(key, value):
    """A value fit for the field, or None: a choice must be one of its options, text is kept short."""
    choices = SLOTS[key][2]
    if choices is not None:
        return value if value in choices else None
    if not isinstance(value, str) or value.strip().lower() in ("", "null", "none", "없음", "모름"):
        return None
    return value.strip()[:100]


def apply_insights(state, values, now=None, event_id=None, date=None, project_id=None):
    """Store approved declarations, NOT inferred habits. Call only after confirmation.

    Old callers remain valid. Without an event id, repeated calls on the same day
    are conservatively one confirmation per value/day across all projects.
    Raw event provenance is retained separately from day-weighted confirmations.
    Historical values without evidence are preserved but never backfilled as proof.
    """
    now = _local_time(now or _now())
    day = _day(date) if date is not None else now.date().isoformat()
    insights = state.setdefault("userInsights", {})
    for key, value in values.items():
        if key not in SLOTS or (value := clean_value(key, value)) is None:
            continue
        old = insights.get(key) or {}
        history = [v for v in old.get("history", [old.get("value")]) if v and v != value][-(HISTORY - 1):] + [value]
        samples = list((old.get("evidence") or {}).get("samples") or [])
        sample = {"eventId": event_id, "date": day, "projectId": project_id, "value": value}
        identity = lambda s: (s.get("projectId"), s.get("eventId") or s.get("date"))
        samples = [s for s in samples if identity(s) != identity(sample)] + [sample]
        samples = samples[-100:]
        current = [s for s in samples if s.get("value") == value and _in_window(s.get("date"), now)]
        insights[key] = {"value": value, "history": history, "updatedAt": now.isoformat(),
                         "source": "check_in", "kind": "declared",
                         "evidence": {"samples": samples, "confirmations": len({s["date"] for s in current}),
                                      "distinctDays": len({s["date"] for s in current}),
                                      "windowDays": WINDOW_DAYS, "observationUnit": "calendar_day",
                                      "calendarTimezone": "Asia/Seoul"}}


def mark_asked(state, keys, now=None):
    now = (now or _now()).isoformat()
    asks = state.setdefault("insightAsks", {})
    for key in keys:
        if key in SLOTS:
            asks[key] = now


def value_text(key, value):
    choices = SLOTS[key][2]
    return choices.get(value, value) if choices else value


def known_insights(state):
    """What is known, as the AI reads it: label → value (text fields with their recent answers)."""
    result = {}
    for key, item in (state.get("userInsights") or {}).items():
        if key not in SLOTS:
            continue
        label = SLOTS[key][0]
        history = item.get("history") or [item.get("value")]
        if SLOTS[key][2] is None and len(history) > 1:
            result[label] = ", ".join(history)
        elif item.get("value") is not None:
            result[label] = value_text(key, item["value"])
    return result


WINDOW_DAYS = 30
MAX_SESSIONS = 100
MIN_OBSERVATIONS = 3
MIN_DAYS = 3
GOOD_RATIO = 0.7
FOCUS_VALUES = {"good", "ok", "poor"}
SELECTION_POLICY = ("optional, varied, not every task; leave titles generic; location only optional suggestion "
                    "and no forced cost/time; success ratio is not recommendation share; "
                    "never automatically rewrite schedules or titles")


def _day(value):
    """KST date: aware timestamps convert; naive dates/times already mean KST.

    Missing dates are never inferred from task dates.
    """
    try:
        return _local_time(datetime.fromisoformat(str(value).replace("Z", "+00:00"))).date().isoformat()
    except (ValueError, TypeError):
        return None


def _in_window(day, now=None):
    day = _day(day)
    if day is None:
        return False
    age = (_local_time(now or _now()).date() - datetime.fromisoformat(day).date()).days
    return 0 <= age < WINDOW_DAYS


def _sessions(state, project_id=None):
    """Primary check-ins plus uncovered legacy days, never one observation per task.

    Conflicting task copies become unknown rather than choosing a favorable result.
    Undated legacy rows remain visible as one unverified group per project; they
    cannot contribute known dated focus evidence. No input state is mutated.
    """
    fields = ("place", "atmosphere", "focus", "condition", "note")
    groups = {}
    covered_ids, covered_days = set(), set()
    for row in state.get("checkInSessions") or []:
        project, day = row.get("projectId"), _day(row.get("date"))
        if project_id is not None and project != project_id:
            continue
        if row.get("id"):
            covered_ids.add((project, row["id"]))
        if day:
            covered_days.add((project, day))
        key = (project, "primary", row.get("id") or day)
        groups.setdefault(key, []).append(dict(row, date=day))
    for row in state.get("executionRecords") or []:
        project = row.get("projectId")
        if project_id is not None and project != project_id:
            continue
        day = _day(row.get("checkInDate") or row.get("createdAt"))
        event = row.get("checkInId")
        if (project, event) in covered_ids or (day and (project, day) in covered_days):
            continue
        key = (project, "legacy", event or day or "undated")
        groups.setdefault(key, []).append(dict(row, date=day))
    sessions = []
    for (project, _, _), rows in groups.items():
        dates = {r.get("date") for r in rows if r.get("date")}
        result = {"projectId": project, "date": next(iter(dates)) if len(dates) == 1 else None}
        for field in fields:
            values = {r[field] for r in rows if isinstance(r.get(field), str) and r[field].strip()}
            result[field] = next(iter(values)) if len(values) == 1 else None
        if any(result.get(f) for f in fields):
            sessions.append(result)
    return sorted((s for s in sessions if s["date"] is None or _in_window(s["date"])),
                  key=lambda s: s["date"] or "")


def session_summary(state, last=10, project_id=None):
    """Recent independent sessions; original Korean summary keys remain available."""
    sessions = _sessions(state, project_id)[-MAX_SESSIONS:]
    sessions = sessions[-last:] if last > 0 else []
    if not sessions:
        return {}
    def count(field, names):
        return {names.get(v, v): sum(r.get(field) == v for r in sessions)
                for v in dict.fromkeys(r.get(field) for r in sessions) if v}
    return {"기록 수": len(sessions), "장소": count("place", {}),
            "분위기": count("atmosphere", {"quiet": "조용한 곳", "lively": "소리 있는 열린 곳"}),
            "집중": count("focus", {"good": "집중 잘 됨", "ok": "집중 보통", "poor": "집중 안 됨"}),
            "컨디션": count("condition", {"good": "컨디션 좋음", "ok": "컨디션 보통", "poor": "컨디션 나쁨"}),
            "datedSessions": sum(s["date"] is not None for s in sessions), "windowDays": WINDOW_DAYS}


def _pattern(field, value, sessions):
    """One observation per KST day/field/value, including across projects.

    A day's focus is known only when every matching session agrees on one valid
    focus value. Conflicting, missing or invalid focus makes that day unknown,
    not success or failure. Undated history is one unverified unknown bucket.
    Aggregate before any limit: duplicate sessions must not evict other days.
    """
    raw = [s for s in sessions if s.get(field) == value]
    grouped = {}
    for sample in raw:
        grouped.setdefault(sample["date"], []).append(sample)
    samples = []
    for day, rows in grouped.items():
        focuses = {s.get("focus") if s.get("focus") in FOCUS_VALUES else None for s in rows}
        focus = next(iter(focuses)) if len(focuses) == 1 else None
        samples.append({"date": day, "focus": focus})
    known = [s for s in samples if s["date"] and s.get("focus") in FOCUS_VALUES]
    days = {s["date"] for s in known}
    good = sum(s["focus"] == "good" for s in known)
    ratio = good / len(known) if known else None
    # Compare recent independent DAYS, so several tasks/check-ins cannot hide reversal.
    recent_days = sorted(days)[-5:]
    recent = [s for s in known if s["date"] in recent_days]
    recent_ratio = sum(s["focus"] == "good" for s in recent) / len(recent) if recent else None
    enough = len(known) >= MIN_OBSERVATIONS and len(days) >= MIN_DAYS
    status = "insufficient" if not enough else (
        "supported" if ratio is not None and recent_ratio is not None
        and ratio >= GOOD_RATIO and recent_ratio >= GOOD_RATIO else "mixed")
    return {"field": field, "value": value, "status": status, "samples": len(samples),
            "distinctDays": len({s["date"] for s in samples if s["date"]}),
            "knownFocus": len(known), "knownFocusDays": len(days), "unknownFocus": len(samples) - len(known),
            "goodFocus": good, "goodFocusRatio": ratio, "recentGoodFocusRatio": recent_ratio,
            "recentKnownFocus": len(recent), "windowDays": WINDOW_DAYS,
            "observationUnit": "calendar_day", "calendarTimezone": "Asia/Seoul",
            "projectIds": sorted({s["projectId"] for s in raw if s.get("projectId")})}


def insights_for_ai(state, project_id=None):
    """Declared global facts and revocable, scoped evidence; no profile mutation."""
    known, summary = known_insights(state), session_summary(state, project_id=project_id)
    sessions = _sessions(state, project_id)
    candidates = [_pattern(field, value, sessions) for field in ("place", "atmosphere")
                  for value in dict.fromkeys(s.get(field) for s in sessions) if value]
    places = [p for p in candidates if p["field"] == "place"]
    # Unspecified is an actual opt-out, NOT an invented place or claimed outcome.
    options = [{"place": p["value"], "evidence": p} for p in places]
    options.append({"place": None, "kind": "unspecified", "optional": True})
    recommendations = [{"field": p["field"], "value": p["value"], "optional": True,
                        "maxShare": .6, "evidence": p} for p in places if p["status"] == "supported"]
    return {**({"알게 된 것": known} if known else {}), **({"최근 체크인": summary} if summary else {}),
            "scope": {"kind": "project", "projectId": project_id} if project_id is not None else {"kind": "global_aggregate"},
            "declaredFacts": known, "candidatePatterns": candidates, "placeOptions": options,
            "recommendations": recommendations, "selectionPolicy": SELECTION_POLICY,
            "evidencePolicy": {"minObservations": MIN_OBSERVATIONS, "minDistinctDays": MIN_DAYS,
                               "minGoodFocusRatio": GOOD_RATIO, "windowDays": WINDOW_DAYS,
                               "maxSessions": MAX_SESSIONS, "recentDays": 5,
                               "maxSessionsAppliesTo": "session_summary_only",
                               "observationUnit": "calendar_day", "calendarTimezone": "Asia/Seoul",
                               "sameDayFocusPolicy": "unanimous_valid_focus_else_unknown"},
            "interpretationPolicy": "Declarations are reported statements, not established habits. "
                                    "Compare dated evidence, not personality; associations are not causal. "
                                    "Unknown focus is not failure; undated history is unverified. "
                                    "Patterns are provisional and may decline or expire. Global aggregation "
                                    "is descriptive only, not an automatic UserProfile update."}

def reply_tone(state):
    """The way the planner talks: the user's own answer, polite until they say otherwise."""
    tone = ((state.get("userInsights") or {}).get("tone") or {}).get("value")
    return "편한 반말(친구처럼 다정하게, 무례하지 않게)" if tone == "casual" else "부드러운 존댓말"
