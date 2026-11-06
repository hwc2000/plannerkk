"""Tests applied to each virtual user's weeks, and an audit of what the app stored.

Every target comes from the user's hidden truth with one formula for all users
(never a per-user branch), so the same tests judge a new user the same way.

| test            | question                                                    | app state it depends on              |
| --------------- | ----------------------------------------------------------- | ------------------------------------ |
| length          | does each task fit what they can do at that time of day?   | blockMinutes (profile / project)     |
| time_of_day     | is the work in the part of the day that suits them?         | focusTime                            |
| daily_load      | does a day hold what they can really do in a day?           | dailyPlannedMinutes                  |
| completion      | do they finish what was planned? (the outcome)              | all of the above                     |
| progress        | is the week's finished work near what they could do?        | all of the above (stops "plan less") |
| right_direction | was each approved change justified by what the app knew?    | profileUpdateProposals               |
| extraction      | did the check-in AI read the words right, inventing nothing?| executionRecords (from the words)    |

Per user, across weeks: what the app believes against the truth (``beliefs``), the
day it got each trait right and kept it (``learned``), and whether every check-in
was stored once and what it learned about the person reads right (``audit``).
"""
import json
import sqlite3
from datetime import date
from statistics import mean

from .personas import FIRST_MONDAY, at_week

STRETCH = 120          # the longest stretch of time the users chose (10-12, 19-21)
CHOSEN_PER_DAY = 230   # planned minutes a chosen weekday holds (two 2-hour stretches, breaks out)
WORKDAYS = 5
FIT_SLACK = 1.1        # a task may run 10% past what they can do in one go
FIT_SHARE = 0.8
TIME_OF_DAY_SHARE = 0.6
LOAD_TOLERANCE = 1.15
BELIEF_TOLERANCE = 0.25
COMPLETION_TARGET = 0.8
PROGRESS_TARGET = 0.7
EXTRACTION_TARGET = 0.9
GROW_NEEDS = 0.8       # finished share since the last change that justifies trying a longer cap
WINDOW_DAYS = 14
UNDO_DAYS = 7          # a change that made things worse should be undone within this many days
WORSE_BY = 0.2         # finished share falling this much after a longer cap means the try failed


def part_of_day(start):
    hour = int(start[11:13])
    return "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"


def ideal_length(p):
    """Planned minutes they can finish in one go at their best time: focus, within a stretch, at their pace."""
    return min(p.focus, STRETCH) / p.pace


def focus_at(p, start):
    return p.focus * (1.0 if p.best in (None, part_of_day(start)) else p.off_focus)


def fits(p, o):
    """The task, at its pace, fits the focus they have at that time of day (shorter is always fine)."""
    return o["planned"] * p.pace <= min(focus_at(p, o["start"]), STRETCH) * FIT_SLACK


def day_number(day):
    return (date.fromisoformat(day[:10]) - FIRST_MONDAY).days + 1


# ---------------------------------------------------------------- per week

def week_metrics(p, week, judged=()):
    p = at_week(p, week["week"])
    outs = [o for d in week["days"] for o in d["outcomes"]]
    m = {"week": week["week"], "tasks": len(outs), "skippedDays": sum(bool(d.get("skipped")) for d in week["days"])}
    if not outs:
        return m
    planned = [o["planned"] for o in outs]
    m["avgTask"] = round(mean(planned), 1)
    m["completion"] = round(sum(o["result"] == "completed" for o in outs) / len(outs), 2)
    days = {}
    for o in outs:
        days[o["start"][:10]] = days.get(o["start"][:10], 0) + o["planned"]
    m["dailyPlanned"] = round(mean(days.values()))
    by_part = {}
    for o in outs:
        by_part[part_of_day(o["start"])] = by_part.get(part_of_day(o["start"]), 0) + o["planned"]
    m["morningShare"] = round(by_part.get("morning", 0) / sum(planned), 2)
    m["reasons"] = {}
    for o in outs:
        if o["reason"]:
            m["reasons"][o["reason"]] = m["reasons"].get(o["reason"], 0) + 1

    tests = {}
    share = sum(fits(p, o) for o in outs) / len(outs)
    tests["length"] = {"value": round(share, 2), "target": f"작업 {FIT_SHARE:.0%} 이상이 그때의 집중 안에",
                       "pass": share >= FIT_SHARE}
    if p.best:
        best = by_part.get(p.best, 0) / sum(planned)
        tests["time_of_day"] = {"value": round(best, 2), "target": f"잘 되는 때 ≥ {TIME_OF_DAY_SHARE:.0%}",
                                "pass": best >= TIME_OF_DAY_SHARE}
    if p.capacity:
        tests["daily_load"] = {"value": m["dailyPlanned"], "target": f"≤ {p.capacity * LOAD_TOLERANCE:.0f}분",
                               "pass": m["dailyPlanned"] <= p.capacity * LOAD_TOLERANCE}
    tests["completion"] = {"value": m["completion"], "target": f"≥ {COMPLETION_TARGET:.0%}",
                           "pass": m["completion"] >= COMPLETION_TARGET}
    possible = min(p.capacity or CHOSEN_PER_DAY, CHOSEN_PER_DAY) / p.pace * WORKDAYS
    m["finishedMinutes"] = sum(o["planned"] for o in outs if o["result"] == "completed")
    progress = m["finishedMinutes"] / possible
    tests["progress"] = {"value": round(progress, 2), "target": f"≥ {PROGRESS_TARGET:.0%} ({possible:.0f}분 중)",
                         "pass": progress >= PROGRESS_TARGET}
    tests["extraction"] = extraction(week)
    m["tests"] = tests
    m["proposals"] = list(judged)
    m["state"] = week.get("end")
    m["planFailures"] = sum(bool(plan.get("failed")) for plan in week["plans"])
    m["checkInErrors"] = sum("error" in d for d in week["days"])
    return m


def extraction(week):
    """How often the check-in AI read back what the words said; a number they did not say must stay empty."""
    hits = total = invented = 0
    misses = []
    for day in week["days"]:
        if day.get("skipped") or "extracted" not in day:
            continue
        records = {r["taskId"]: r for r in day["extracted"].get("records", [])}
        session = day["extracted"].get("session") or {}
        said = day.get("said") or {"focus": day["session"]["focus"], "condition": day["session"]["condition"]}
        checks = []
        for o in day["outcomes"]:
            r = records.get(o["task_id"])
            if r is None:
                continue
            truth_minutes = o.get("said_minutes", o["actual"])
            truth_reason = o.get("said_reason", o["reason"])
            if o["result"] != "not_started":
                checks.append((o["title"], "actualMinutes", truth_minutes, r.get("actualMinutes"), o["actual"]))
            if o["result"] != "completed":
                checks.append((o["title"], "reasonCode", truth_reason, r.get("reasonCode"), o["reason"]))
        for field in ("focus", "condition"):
            got = session.get(field) if field in (session.get("reportedFields") or [field]) else None
            checks.append(("(하루 상태)", field, said[field], got, day["session"][field]))
        for task, field, truth, got, real in checks:
            # Not said, but true (read from other words, e.g. "집중 끊김" as poor focus): an inference, not an invention.
            ok = truth == got or (truth is None and got == real)
            total += 1
            hits += ok
            invented += truth is None and got is not None and not ok
            if not ok:
                misses.append({"date": day["date"], "task": task, "field": field, "truth": truth, "got": got,
                               "words": next((o["sentence"] for o in day["outcomes"] if o["title"] == task), day.get("text", "")[-160:])})
    rate = round(hits / total, 2) if total else None
    return {"value": rate, "target": f"≥ {EXTRACTION_TARGET:.0%}, 지어낸 값 0", "invented": invented,
            "pass": rate is not None and rate >= EXTRACTION_TARGET and invented == 0, "misses": misses}


# ---------------------------------------------------------------- per user

def reported_outcomes(result):
    return [(d["date"], o) for w in result["weeks"] for d in w["days"] if not d.get("skipped") and "error" not in d
            for o in d["outcomes"]]


def judge_changes(p, result):
    """Each approved change against what the app knew then: {week: [judged change, ...]}.

    A longer cap is fine to try once what was planned since the last change was
    mostly finished; trying it while tasks were still being missed is not.  A
    shorter cap must move toward the truth, and a time of day must be the right one.
    """
    told = reported_outcomes(result)
    approved = [(w["week"], x) for w in result["weeks"] for x in w["proposals"] if x.get("approved")]
    judged, last = {}, None
    for week in result["weeks"]:
        who = at_week(p, week["week"])
        for x in week["proposals"]:
            if not x.get("approved"):
                continue  # failed approvals are listed apart (stale cards)
            entry = {"rule": x["rule"], "changes": x["changes"], "approved": True,
                     "replanned": x.get("replanned"), "at": x.get("at", ""),
                     "reason": x.get("reason"), "sizing": x.get("sizing")}
            since = [o for day, o in told if (last is None or day > last[:10]) and day <= x["at"][:10]
                     and day_number(x["at"]) - day_number(day) < WINDOW_DAYS]
            done = sum(o["result"] == "completed" for o in since) / len(since) if since else None
            entry["recentCompletion"] = None if done is None else round(done, 2)
            finished = finished_per_day(result, x["at"])
            entry["finishedPerDay"] = finished
            asked = [w["feedback"].get("timeFit") for w in result["weeks"] if w.get("feedback")
                     and (w["monday"] < x["at"][:10]) and day_number(x["at"]) - day_number(w["monday"]) >= 6][-2:]
            entry["verdict"], entry["why"] = verdict(who, x["changes"], done, finished, asked)
            later = [y for _, y in approved if y["at"] > x["at"]]
            entry["undoneAfter"] = undone_after(x, later)
            after = [o for day, o in told if day > x["at"][:10] and day_number(day) - day_number(x["at"]) <= UNDO_DAYS]
            if after:
                entry["completionAfter"] = round(sum(o["result"] == "completed" for o in after) / len(after), 2)
            grew = "blockMinutes" in x["changes"] and x["changes"]["blockMinutes"]["to"] > x["changes"]["blockMinutes"]["from"]
            entry["worseAfterProbe"] = bool(grew and done is not None and entry.get("completionAfter") is not None
                                            and entry["completionAfter"] < done - WORSE_BY)
            last = x["at"]
            judged.setdefault(week["week"], []).append(entry)
    return judged


def undone_after(x, later):
    """Days until a later approved change put the value back (None: never)."""
    for key, change in x["changes"].items():
        for y in later:
            back = (y["changes"].get(key) or {}).get("to")
            if back is not None and back == change.get("from"):
                return day_number(y["at"]) - day_number(x["at"])
            if key == "blockMinutes" and isinstance(back, int) and isinstance(change.get("from"), int) \
                    and (back - change["from"]) * (change["to"] - change["from"]) <= 0:
                return day_number(y["at"]) - day_number(x["at"])
    return None


def stale_cards(result):
    """Proposals the app kept offering that could not be approved, once each."""
    cards = {}
    for week in result["weeks"]:
        for x in week["proposals"]:
            # An already-closed card (closed because the settings changed) is the fix working, not a stuck card.
            if not x.get("approved") and "이미 처리한" not in (x.get("error") or ""):
                card = cards.setdefault(x["id"], {"rule": x["rule"], "changes": x["changes"], "first": x["at"], "tries": 0,
                                                  "error": x.get("error", "")})
                card["tries"] += 1
                card["last"] = x["at"]
    return list(cards.values())


def finished_per_day(result, at, days=UNDO_DAYS):
    """Planned minutes the person really finished per workday, in the days before and after a moment (truth)."""
    before, after = {}, {}
    for week in result["weeks"]:
        for day in week["days"]:
            gap = day_number(day["date"]) - day_number(at)
            side = after if 0 < gap <= days else before if -days < gap <= 0 else None
            if side is not None:
                side[day["date"]] = sum(o["planned"] for o in day["outcomes"] if o["result"] == "completed")
    return {"before": round(mean(before.values())) if before else None, "after": round(mean(after.values())) if after else None}


def verdict(p, changes, done, finished=None, asked=()):
    """ok / wrong and why, judged against the truth (or, where the truth has no number, against what got done).

    A change the person asked for in their last two weekly feedbacks has its reason, whatever the numbers.
    """
    for key, change in changes.items():
        before, after = change.get("from"), change.get("to")
        if key == "blockMinutes" and isinstance(before, int) and isinstance(after, int):
            wanted = "too_short" if after > before else "too_long"
            if len(asked) == 2 and all(a == wanted for a in asked):
                return "ok", f"사용자가 주간 의견에 두 번 '{'시간이 짧았다' if after > before else '시간이 길었다'}'고 함"
            if after > before:
                if done is not None and done >= GROW_NEEDS:
                    return "ok", f"직전까지 {done:.0%} 끝내서 늘려 볼 만함"
                return "wrong", f"못 한 작업이 섞인 상태(완료 {0 if done is None else done:.0%})에서 늘림"
            ideal = ideal_length(p)
            if abs(after - ideal) < abs(before - ideal) or after >= ideal * (1 - BELIEF_TOLERANCE):
                return "ok", f"진짜 길이 {ideal:.0f}분 쪽이거나 그 근처로 줄임"
            return "wrong", f"진짜 길이 {ideal:.0f}분보다 너무 줄임"
        if key == "focusTime":
            if p.best is not None and after == p.best:
                return "ok", "진짜 잘 되는 시간대"
            return "wrong", "시간대가 원인이 아닌데 시간대로 판단함" if p.best is None else "다른 시간대를 고름"
        if key == "dailyPlannedMinutes" and p.capacity is not None:
            if isinstance(after, int) and (before is None or abs(after - p.capacity) < abs(before - p.capacity)
                                           or abs(after - p.capacity) <= p.capacity * BELIEF_TOLERANCE):
                return "ok", f"진짜 처리량 {p.capacity}분 쪽으로"
            return "wrong", f"진짜 처리량 {p.capacity}분에서 멀어짐"
        if key in ("dailyPlannedMinutes", "pacePercent", "periodMinutes"):
            # No single true number: the change is wrong if it cut work the person was getting done.
            b, a = (finished or {}).get("before"), (finished or {}).get("after")
            if b is None or a is None:
                return None, "판단할 기록 부족"
            if a >= b * 0.85:
                return "ok", f"끝내던 일은 그대로 (하루 끝낸 분 {b} → {a})"
            return "wrong", f"끝내던 일까지 줄임 (하루 끝낸 분 {b} → {a})"
    return None, "판단 기준 없음"


def belief_state(app, truth, *, unknown=(None,), lower_is_safe=True):
    """right | under (knows less, plans stay safe) | wrong (plans go past the truth) for one number."""
    if app in unknown:
        return "under"
    if abs(app - truth) <= truth * BELIEF_TOLERANCE:
        return "right"
    return "under" if lower_is_safe and app < truth else "wrong"


def beliefs(p, result):
    """What the app believes at each week's end, against the truth that week."""
    rows = []
    for week in result["weeks"]:
        who, state = at_week(p, week["week"]), week.get("end") or {}
        prof = state.get("profile") or {}
        block, focus_time = state.get("effectiveBlock"), prof.get("focusTime")
        daily = (state.get("projectOverrides") or {}).get("dailyPlannedMinutes") or prof.get("dailyPlannedMinutes")
        unknown_time = focus_time in (None, "unknown", "variable")
        if who.best:
            time_state = "right" if focus_time == who.best else "under" if unknown_time else "wrong"
        else:
            time_state = "right" if unknown_time else "wrong"
        if who.capacity:
            daily_state = "wrong" if daily is None else belief_state(daily, who.capacity)
        else:
            daily_state = "right" if daily is None else "under"
        rows.append({
            "week": week["week"],
            "block": {"app": block, "truth": round(ideal_length(who)),
                      "state": belief_state(block, ideal_length(who)) if isinstance(block, int) else "under"},
            "focusTime": {"app": focus_time, "truth": who.best, "state": time_state},
            # One cap serves every part of the day: for someone with a bad part of the day it should be shorter there.
            "offBlock": None if not who.best else {
                "app": block, "truth": round(min(who.focus * who.off_focus, STRETCH) / who.pace),
                "state": belief_state(block, min(who.focus * who.off_focus, STRETCH) / who.pace) if isinstance(block, int) else "under"},
            "daily": {"app": daily, "truth": who.capacity, "state": daily_state},
            # The app has no field for how much longer than planned work takes.
            "pace": {"app": None, "truth": who.pace, "state": "right" if who.pace == 1 else "nofield"},
        })
    return rows


def learned(p, result):
    """The day the app first held the right block / time of day and kept it to the end (None: never)."""
    start = result.get("start") or {}
    block = start.get("effectiveBlock")
    focus_time = (start.get("profile") or {}).get("focusTime")
    events = [(x["at"], x["changes"]) for w in result["weeks"] for x in w["proposals"] if x.get("approved")]
    ideal = ideal_length(p)
    right = {"block": lambda: isinstance(block, int) and abs(block - ideal) <= ideal * BELIEF_TOLERANCE,
             "focusTime": lambda: focus_time == p.best if p.best else focus_time in (None, "unknown", "variable")}
    since = {k: (0 if ok() else None) for k, ok in right.items()}
    for at, changes in events:
        if "blockMinutes" in changes:
            block = changes["blockMinutes"]["to"]
        if "focusTime" in changes:
            focus_time = changes["focusTime"]["to"]
        for key, ok in right.items():
            if ok() and since[key] is None:
                since[key] = day_number(at)
            elif not ok():
                since[key] = None
    return since


def audit(p, result, db_path):
    """Was every check-in stored once, and does what the app learned about the person read right?"""
    doc = json.loads(sqlite3.connect(db_path).execute("SELECT document FROM execution_state").fetchone()[0])
    told = [o["task_id"] for _, o in reported_outcomes(result)]
    counts = {}
    for r in doc["executionRecords"]:
        counts[r["taskId"]] = counts.get(r["taskId"], 0) + 1
    reported_days = sum(1 for w in result["weeks"] for d in w["days"] if not d.get("skipped") and "error" not in d)
    planned_weeks = sum(1 for w in result["weeks"] if w.get("feedback"))
    insights = {k: v.get("value") for k, v in (doc.get("userInsights") or {}).items()}
    reading = {}
    for key, truth in p.told.items():
        got = insights.get(key)
        if got is None:
            reading[key] = {"truth": truth, "got": None, "right": None}  # never filled: empty, not wrong
            continue
        reading[key] = {"truth": truth, "got": got, "right": (truth in got) if key == "place" and isinstance(got, str) else got == truth}
    for key, answer in p.answers.items():
        if key in p.told:
            continue
        if key not in insights:
            reading[key] = {"truth": answer, "got": None, "right": None}  # never filled
            continue
        got = insights[key]
        # A free-text field should hold words from the person's own answer for it.
        overlap = any(word[:2] in answer for word in str(got).split() if len(word) >= 2)
        reading[key] = {"truth": answer, "got": got, "right": overlap}
    return {
        "toldTasks": len(told), "records": len(doc["executionRecords"]),
        "missing": sum(1 for t in told if counts.get(t, 0) == 0), "duplicated": sum(1 for c in counts.values() if c > 1),
        "sessions": len(doc.get("checkInSessions") or []), "reportedDays": reported_days,
        "feedback": len((doc.get("projectFeedback") or {}).get("sim-project") or []), "plannedWeeks": planned_weeks,
        "overrunsStored": sum(1 for r in doc["executionRecords"] if (r.get("actualMinutes") or 0) > r["plannedMinutes"]),
        "reading": reading,
    }


def remarks_reach(result):
    """Did each thing said outside the fields reach a later plan request to the AI?"""
    plan_contexts = [(c["at"], json_text(c.get("context"))) for c in result.get("llm", [])
                     if not str(c.get("name")).startswith(("planner_", "sim_"))]
    rows = []
    for week in result["weeks"]:
        for day in week["days"]:
            if not day.get("remark"):
                continue
            key = day["remark"][:12]
            later = [text for at, text in plan_contexts if at > day["date"]]
            stored = any(key in (r.get("note") or "") for r in (day.get("extracted") or {}).get("records", []))
            # None: no plan was made after it, so there was nothing to reach.
            reached = any(key in text for text in later) if later else None
            rows.append({"date": day["date"], "remark": day["remark"], "keptInRecord": stored, "reachedPlanAI": reached})
    feedback_notes = [w.get("feedback", {}).get("note") for w in result["weeks"] if w.get("feedback")]
    return {"rows": rows, "feedbackNotes": feedback_notes}


def json_text(value):
    return json.dumps(value, ensure_ascii=False) if value is not None else ""


def divergence(all_metrics, baseline="steady"):
    """How far each user's week is from the control user's: same survey, so any gap came from check-ins."""
    base = {m["week"]: m for m in all_metrics.get(baseline, [])}
    table = {}
    for pid, weeks in all_metrics.items():
        table[pid] = []
        for m in weeks:
            b = base.get(m["week"])
            if not b or "avgTask" not in m or "avgTask" not in b:
                table[pid].append(None)
                continue
            table[pid].append({
                "avgTask": round(m["avgTask"] - b["avgTask"], 1),
                "morningShare": round(m["morningShare"] - b["morningShare"], 2),
                "dailyPlanned": m["dailyPlanned"] - b["dailyPlanned"],
            })
    return table


def llm_stats(result):
    calls = result.get("llm", [])
    by_name = {}
    for c in calls:
        s = by_name.setdefault(c["name"], {"calls": 0, "failed": 0, "seconds": []})
        s["calls"] += 1
        s["failed"] += not c.get("ok")
        s["seconds"].append(c.get("seconds") or 0)
    return {name: {"calls": s["calls"], "failed": s["failed"], "avgSeconds": round(mean(s["seconds"]), 1),
                   "maxSeconds": max(s["seconds"])} for name, s in by_name.items()}
