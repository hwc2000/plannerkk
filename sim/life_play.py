"""Play one person through several projects at once, the way the screens use the app.

Every Monday the person picks the week's hours, then opens each project's chat
in turn and asks for that project's plan (``merge``: the other projects' tasks
stay, as the project chat does).  Every evening they go through the day across
all projects (one day, one energy: a long task in one project eats the time and
energy of the next), then check in once in each project's chat, then approve
the cards the app offers (each approval replans as in the app).  On Sunday a
line of feedback per project; a project whose due date has come is ended.
"""
import json
import os
import random
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import time_machine
from fastapi.testclient import TestClient

from server.app.execution_llm import ExecutionLLM
from server.app.execution_store import ExecutionStore
from server.app.main import create_app

from . import writer
from .behavior import BREAK, STRETCH_GAP, Outcome, _round5, casual_sentence, check_in_text, part_of_day, sentence
from .driver import KST, ApiError, App, LoggingLLM, at
from .personas import FIRST_MONDAY

PLAN_ATTEMPTS = 2
REASON_OF = {"focus": "task_too_large", "off_time": "fatigue", "time": "time_shortage", "spent": "fatigue",
             "pace": "underestimated", "interrupted": "interruption", "quota": "other"}


@dataclass
class LifeOutcome(Outcome):
    project_id: str = ""
    note: str | None = None   # why a session was skipped, in the person's words (sent to the writer as a fact)


def entries_of(plan):
    owner = (plan or {}).get("projectId")
    return [{**{k: e.get(k) for k in ("id", "title", "minutes", "start", "end", "doneWhen", "completed")},
             "projectId": e.get("projectId") or owner,
             "place": (e.get("environmentSuggestion") or {}).get("place")}
            for e in (plan or {}).get("entries", []) if e["kind"] == "task"]


def busy_on(scenario, day):
    """The day's fixed calendar things as (start, end) datetimes."""
    out = []
    for e in scenario.events:
        if e.day == day.weekday():
            out.append((datetime.fromisoformat(f"{day.isoformat()}T{e.start}"), datetime.fromisoformat(f"{day.isoformat()}T{e.end}")))
    return out


def stretch_ends(tasks, chosen, busy):
    """When the time the person set aside runs out for each task: the end of the chosen hours it sits in,
    or the start of a fixed thing on the calendar, whichever comes first."""
    ends = {}
    for task in tasks:
        start = datetime.fromisoformat(task["start"])
        day, hour = start.weekday(), start.hour
        if (day, hour) in chosen:
            while (day, hour + 1) in chosen:
                hour += 1
            end = start.replace(hour=hour, minute=0) + timedelta(hours=1)
            for begin, _ in busy:
                if start <= begin < end:
                    end = begin
            ends[task["id"]] = end
        else:
            ends[task["id"]] = datetime.fromisoformat(task["end"])
    return ends


def play_day(person, scenario, tasks, week_sessions, rng, busy):
    """Outcomes of one day's tasks across every project, in the order they were planned."""
    tasks = sorted(tasks, key=lambda t: t["start"])
    ends = stretch_ends(tasks, set(scenario.slots), busy)
    capacity = person.busy_capacity if (busy and person.busy_capacity) else person.capacity
    today = rng.uniform(1 - person.day_noise, 1 + person.day_noise)
    cursor, used, outcomes, today_sessions = None, 0, [], Counter()
    last = {}  # project -> (planned end of its last task, that session's skip note, counted)
    for task in tasks:
        project = scenario.project(task["projectId"])
        planned = task["minutes"]
        start = datetime.fromisoformat(task["start"])
        # Parts of one session: the plan put them back to back (a workout split into "start" and "finish").
        before = last.get(project.id)
        continues = before is not None and timedelta(0) <= start - before[0] <= timedelta(minutes=STRETCH_GAP)
        pushed = bool(cursor and cursor > start)
        if pushed:
            start = cursor
        name = f"‘{task['title']}’"
        if continues:
            note = before[1]
        elif project.per_day and today_sessions[project.id] >= project.per_day:
            note = f"오늘은 이미 {project.per_day}번 했어요(목표가 하루 {project.per_day}번)"
        elif project.per_week and week_sessions[project.id] >= project.per_week:
            note = f"이번 주 {project.per_week}번을 이미 채웠어요(목표가 주 {project.per_week}회)"
        else:
            note = None
        counted = bool(continues and before[2])
        last[project.id] = (datetime.fromisoformat(task["end"]), note, counted)
        if note:
            # The goal does not need this session: they skip it and say why (no time or energy used).
            text = f"{name}은 {note}. 그래서 안 했어요."
            said_reason = "other"
            if person.phrasing == "casual":
                text, said_reason = f"{name} 이미 채워서 패스", None
            outcomes.append(LifeOutcome(task["id"], task["title"], task["start"], planned, "not_started", 0, "other", "quota",
                                        text, None, said_reason, project_id=project.id, note=note))
            continue
        left_in_stretch = max(0, int((ends[task["id"]] - start).total_seconds() // 60))
        period = part_of_day(start.hour)
        focus, pace = person.at(project.kind, period)
        focus *= today
        best = person.best_for(project.kind)
        spent_left = None if capacity is None else max(0, capacity - used)
        need = planned * pace
        limits = {"focus" if best in (None, period) else "off_time": focus, "time": left_in_stretch}
        if spent_left is not None:
            limits["spent"] = spent_left
        why, room = min(limits.items(), key=lambda kv: kv[1])
        if rng.random() < person.noise and need <= room:
            worked, result, why = _round5(planned / 2), "partial", "interrupted"
        elif need <= room:
            worked, result = int(round(need)), "completed"
            why = "pace" if pace > 1 else "done"
        elif room < 5:
            worked, result = 0, "not_started"
        else:
            worked, result = _round5(min(room, need)), "partial"
            if pace > 1 and ((why == "focus" and planned <= person.at(project.kind, period)[0]) or (why == "time" and not pushed)):
                why = "pace"
        reason = None if result == "completed" else REASON_OF[why]
        if person.phrasing == "casual":
            text, said_minutes, said_reason = casual_sentence(task["title"], result, worked, why, reason, rng)
        else:
            text = sentence(task["title"], result, worked, why, planned)
            said_minutes, said_reason = (worked if result != "not_started" else None), reason
        outcomes.append(LifeOutcome(task["id"], task["title"], task["start"], planned, result, worked, reason, why,
                                    text, said_minutes, said_reason, project_id=project.id))
        if worked > 0 and not counted:
            today_sessions[project.id] += 1
            week_sessions[project.id] += 1
            last[project.id] = (last[project.id][0], None, True)
        used += worked
        cursor = start + timedelta(minutes=worked + BREAK)
    return outcomes


def day_state(outcomes, place):
    """How the day went (the same day for every project's check-in); skipped extra sessions do not count."""
    played = [o for o in outcomes if o.why != "quota"]
    if not played:
        return {"place": place, "focus": "ok", "condition": "ok"}
    done = sum(o.result == "completed" for o in played) / len(played)
    focus = "good" if done == 1 else "ok" if done >= 0.5 else "poor"
    tired = any(o.why in ("spent", "off_time") for o in played)
    return {"place": place, "focus": focus, "condition": "poor" if tired else "good" if done == 1 else "ok"}


# ---------------------------------------------------------------- the app, as the screens use it

def snapshot(state, scenario):
    profile = state.get("profile") or {}
    prefs = profile.get("planningPreferences") or {}
    projects = {}
    for p in scenario.projects:
        overrides = ((state.get("projectProfiles") or {}).get(p.id) or {}).get("overrides") or {}
        projects[p.id] = {k: v.get("value") for k, v in overrides.items()}
    return {
        "profile": {k: prefs.get(k) for k in ("blockMinutes", "dailyPlannedMinutes", "pacePercent", "periodMinutes",
                                               "focusTime", "recoveryPreference", "starterMinutes")},
        "projects": projects,
        "insights": {k: v.get("value") for k, v in (state.get("userInsights") or {}).items()},
        "records": len(state.get("executionRecords") or []),
        "closed": sorted((state.get("closedProjects") or {}).keys()),
    }


def make_plan(app, scenario, project, monday, week, events, *, proposal_id=None, label=None, others=()):
    """One project's plan from its own chat (``merge``), or a replan after an approved card.

    ``others``: the week's other open projects, sent as the screen sends them.
    """
    body = {"goal": project.goal if project else scenario.projects[0].goal, "startDate": monday.isoformat(), "consent": True,
            "project": project.context() if project else None, "events": events, "existingTasks": [], "memories": [],
            "projects": [project.context(), *(p.context() for p in others if p.id != project.id)] if project else []}
    if proposal_id:
        body["profileChangeProposalId"] = proposal_id
    else:
        body["merge"] = True
    errors = []
    label = label or f"{project.title} 계획"
    for _ in range(PLAN_ATTEMPTS):
        try:
            draft = app.call("/api/execution/plan", **body)["planDraft"]
            # As the screen: the draft's own project (none when the week holds several).
            confirmed = app.call("/api/execution/plan/confirm", planId=draft["id"], project=draft.get("project"), events=events)
            plan = confirmed["plan"]
            week["plans"].append({"label": label, "project": project.id if project else None,
                                  "at": datetime.now(KST).isoformat(timespec="minutes"),
                                  "tasks": entries_of(plan), "pending": plan.get("pendingTasks") or [], "errors": errors})
            return plan
        except ApiError as exc:
            errors.append(str(exc))
            if proposal_id and exc.status == 400 and "다음 계획부터" in str(exc.detail):
                break
            if "사용 가능한 시간이 없습니다" in str(exc.detail) or "계획할 시간이 남지 않았습니다" in str(exc.detail):
                break  # no AI call was made; asking again gives the same answer
    week["plans"].append({"label": label, "project": project.id if project else None,
                          "at": datetime.now(KST).isoformat(timespec="minutes"), "tasks": [], "pending": [],
                          "errors": errors, "failed": True})
    return None


def approve_pending(app, scenario, monday, week, events):
    for proposal in [p for p in app.state()["profileUpdateProposals"] if p["status"] == "pending"]:
        entry = {"id": proposal["id"], "at": datetime.now(KST).isoformat(timespec="minutes"),
                 "rule": proposal.get("ruleVersion"), "changes": proposal["proposedChanges"],
                 "reason": proposal.get("reason"), "sizing": proposal.get("sizing"), "projectId": proposal.get("projectId")}
        try:
            app.call(f"/api/execution/proposals/{proposal['id']}/approve")
            entry["approved"] = True
        except ApiError as exc:
            entry.update(approved=False, error=str(exc))
            week["proposals"].append(entry)
            continue
        project = scenario.project(proposal["projectId"]) if proposal.get("projectId") else None
        entry["replanned"] = make_plan(app, scenario, project, monday, week, events, proposal_id=proposal["id"],
                                       label=f"승인 후 재계획 ({proposal.get('ruleVersion')}, "
                                             f"{project.title if project else '기본 프로필'})") is not None
        week["proposals"].append(entry)


def weekly_feedback(person, project, outcomes):
    played = [o for o in outcomes if o.why != "quota"]
    skipped = len(outcomes) - len(played)
    note = person.remarks[0] if person.remarks else ""
    if skipped:
        note = f"{project.title}은 주 {project.per_week}번이면 충분해요."  # what they would say about the extra sessions
    if not played:
        return {"load": "too_much" if skipped else "right", "timeFit": "unknown", "note": note}
    done = sum(o.result == "completed" for o in played) / len(played)
    reasons = Counter(o.reason for o in played if o.reason)
    top = reasons.most_common(1)[0][0] if reasons else None
    time_fit = {"task_too_large": "too_long", "underestimated": "too_short", "time_shortage": "too_short"}.get(top, "right")
    return {"load": "too_much" if done < 0.6 or skipped else "right", "timeFit": time_fit, "note": note}


def check_in(app, person, project, outcomes, session, rng, count, log):
    if rng.random() < person.skip:
        return {"project": project.id, "outcomes": [asdict(o) for o in outcomes], "skipped": True}
    asked = [q["key"] for q in app.client.get("/api/execution/insights", params={"projectId": project.id}).json()["next"]]
    remark = person.remarks[count // 3 % len(person.remarks)] if person.remarks and count % 3 == 1 else None
    written = None
    if os.getenv("SIM_WRITER", "1") == "1":
        answers = {key: person.answers[key] for key in asked if key in person.answers}
        written = writer.write(person, outcomes, session, answers, remark, log)
    if written:
        text, per_task, said = written
        for o in outcomes:
            o.said_minutes, o.said_reason = per_task[o.task_id]
    else:
        text, said = check_in_text(person, outcomes, session, asked, remark, rng)
    entry = {"project": project.id, "outcomes": [asdict(o) for o in outcomes], "session": session, "said": said,
             "asked": asked, "remark": remark, "text": text, "words": "ai" if written else "template"}
    try:
        state = app.call("/api/execution/chat/check-in", consent=True, project=project.context(), text=text, asked=asked,
                         results=[{"taskId": o.task_id, "result": o.result} for o in outcomes])
        action = state["plannerThreads"][project.id]["action"]
        payload = action["payload"]
        entry["extracted"] = {"records": payload["records"], "insights": payload.get("insights") or {},
                              "session": payload.get("session") or {}}
        app.call("/api/execution/chat/check-in/confirm", project=project.context(), actionId=action["id"])
    except ApiError as exc:
        entry["error"] = str(exc)
    return entry


def run_life(uid, weeks, out_dir: Path):
    from .life import resolve
    scenario, person = resolve(uid)
    log, rng = [], random.Random(f"{uid}-{os.getenv('SIM_SEED', '1')}")
    result = {"uid": uid, "scenario": scenario.id, "person": person.id, "weeks": [],
              "started": datetime.now().isoformat(timespec="seconds")}
    store = ExecutionStore(out_dir / f"{uid}.sqlite3")
    slots = [{"day": d, "hour": h} for d, h in scenario.slots]
    closed = set()
    with time_machine.travel(at(FIRST_MONDAY, 7), tick=True) as clock:
        client = TestClient(create_app(execution_store=store, execution_llm=LoggingLLM(ExecutionLLM(), log)),
                            raise_server_exceptions=False)
        app = App(client)
        app.call("/api/execution/profile", answers=scenario.survey)
        app.call("/api/execution/profile/confirm")
        # Making each project on the form: when it is done ("딱히 없어요" for most).
        for project in scenario.projects:
            app.call(f"/api/execution/projects/{project.id}/profile", method="put",
                     overrides={"timeSlots": [{"day": d, "hour": h} for d, h in project.hours]})
        result["start"] = snapshot(app.state(), scenario)
        counts = Counter()
        for index in range(weeks):
            monday = FIRST_MONDAY + timedelta(weeks=index)
            sunday = monday + timedelta(days=6)
            clock.move_to(at(monday, 7))
            week = {"week": index + 1, "monday": monday.isoformat(), "plans": [], "days": [], "proposals": [],
                    "feedback": {}, "closed": {}}
            events = scenario.events_for(monday)
            active = [p for p in scenario.projects if p.id not in closed and p.due() >= monday]
            week["active"] = [p.id for p in active]
            app.call("/api/execution/settings", method="put", settings={"slots": slots, "view": "timeline"})
            for project in active:
                # The person opens each project's chat; one whose tasks are already in the week is not asked again.
                if any(t["projectId"] == project.id for t in entries_of(app.state()["plan"])
                       if t["start"][:10] >= monday.isoformat()):
                    continue
                make_plan(app, scenario, project, monday, week, events, others=active)
            played = {p.id: [] for p in active}
            week_sessions = Counter()
            for offset in range(7):
                day = monday + timedelta(days=offset)
                todays = [t for t in entries_of(app.state()["plan"]) if t["start"][:10] == day.isoformat() and not t["completed"]]
                known = {p.id for p in active}
                unowned = [t for t in todays if t["projectId"] not in known]  # work outside the person's projects
                todays = [t for t in todays if t["projectId"] in known]
                if not todays:
                    continue
                clock.move_to(at(day, 22, 30))
                busy = busy_on(scenario, day)
                outcomes = play_day(person, scenario, todays, week_sessions, rng, busy)
                day_entry = {"date": day.isoformat(), "busy": bool(busy), "outcomes": [asdict(o) for o in outcomes],
                             "checkIns": [], "unowned": unowned}
                home = person.answers.get("place", "").replace("주로 ", "").replace("에서 해요.", "") or "집"
                for project in active:
                    mine = [o for o in outcomes if o.project_id == project.id]
                    if not mine:
                        continue
                    played[project.id] += mine
                    session = day_state(outcomes, person.habit(project.kind).place or home)
                    entry = check_in(app, person, project, mine, session, rng, counts[project.id], log)
                    if not entry.get("skipped"):
                        counts[project.id] += 1
                    day_entry["checkIns"].append(entry)
                # The cards, after the evening's check-ins (each approval replans as in the app).
                approve_pending(app, scenario, monday, week, events)
                week["days"].append(day_entry)
            clock.move_to(at(sunday, 21))
            plan_projects = {t["projectId"] for t in entries_of(app.state()["plan"])}
            for project in active:
                if project.id not in plan_projects:
                    week["feedback"][project.id] = {"error": "이번 주 계획에 없는 프로젝트라 의견을 남길 수 없음"}
                    continue
                feedback = weekly_feedback(person, project, played[project.id])
                try:
                    app.call(f"/api/execution/projects/{project.id}/feedback", **feedback)
                except ApiError as exc:
                    feedback["error"] = str(exc)
                week["feedback"][project.id] = feedback
            clock.move_to(at(sunday, 21, 30))
            for project in active:
                if project.due() > sunday:
                    continue
                preview = client.get(f"/api/execution/projects/{project.id}/close-preview").json()
                try:
                    state = app.call(f"/api/execution/projects/{project.id}/close", project=project.context(), outcome="completed")
                    week["closed"][project.id] = {"preview": preview, "result": (state.get("closedProjects") or {}).get(project.id)}
                    closed.add(project.id)
                except ApiError as exc:
                    week["closed"][project.id] = {"preview": preview, "error": str(exc)}
            week["end"] = snapshot(app.state(), scenario)
            result["weeks"].append(week)
        client.close()
    result["llm"] = log
    result["finished"] = datetime.now().isoformat(timespec="seconds")
    (out_dir / f"{uid}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return result
