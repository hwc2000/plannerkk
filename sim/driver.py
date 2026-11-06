"""Play one virtual user through the real app, week by week, on a fake clock.

Only the HTTP API is used, the same calls the screens make: survey, this
week's hours, plan, confirm, a check-in every evening, approving what the
planner proposes (which replans the rest of the week, as in the app), and a
line of feedback on Sunday.  Every AI call is logged for the review queue.
"""
import json
import random
import time
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path

import time_machine
from fastapi.testclient import TestClient

from server.app.execution_llm import ExecutionLLM
from server.app.execution_store import ExecutionStore
from server.app.main import create_app

import os

from . import writer
from .behavior import check_in_text, day_session, play_day
from .personas import FIRST_MONDAY, PROJECT, SLOTS, SURVEY, at_week

KST = timezone(timedelta(hours=9))
PLAN_ATTEMPTS = 2


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, dtime(hour, minute), KST)


class ApiError(Exception):
    def __init__(self, path, status, detail):
        super().__init__(f"{path} {status}: {detail}")
        self.path, self.status, self.detail = path, status, detail


class LoggingLLM:
    """The app's own LLM client, with every call written down."""

    def __init__(self, inner, log):
        self.inner, self.log = inner, log

    async def generate(self, **kwargs):
        began = time.monotonic()
        entry = {"at": datetime.now(KST).isoformat(timespec="minutes"), "name": kwargs.get("name"),
                 "context": kwargs.get("context")}
        try:
            output = await self.inner.generate(**kwargs)
            entry.update(ok=True, output=output)
            return output
        except Exception as exc:
            entry.update(ok=False, error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            entry["seconds"] = round(time.monotonic() - began, 1)
            self.log.append(entry)


class App:
    def __init__(self, client):
        self.client = client
        self.revision = None
        self.state()

    def state(self):
        data = self.client.get("/api/execution").json()
        self.revision = data["revision"]
        return data

    def call(self, path, method="post", **body):
        response = getattr(self.client, method)(path, json={"revision": self.revision, **body})
        try:
            data = response.json()
        except ValueError:
            data = {"detail": response.text}
        if response.status_code != 200:
            raise ApiError(path, response.status_code, data.get("detail") if isinstance(data, dict) else data)
        if isinstance(data, dict) and "revision" in data:
            self.revision = data["revision"]
        return data


def tasks_of(plan):
    return [{k: e.get(k) for k in ("id", "title", "minutes", "start", "end", "doneWhen", "completed")}
            for e in (plan or {}).get("entries", []) if e["kind"] == "task"]


def snapshot(state):
    """What the app believes about the user at this moment."""
    profile = state.get("profile") or {}
    prefs = profile.get("planningPreferences") or {}
    overrides = ((state.get("projectProfiles") or {}).get(PROJECT["id"]) or {}).get("overrides") or {}
    return {
        "profile": {k: prefs.get(k) for k in ("blockMinutes", "dailyPlannedMinutes", "starterMinutes",
                                               "scheduleStyle", "recoveryPreference", "focusTime")},
        "projectOverrides": {k: v.get("value") for k, v in overrides.items()},
        "effectiveBlock": (overrides.get("blockMinutes") or {}).get("value") or prefs.get("blockMinutes"),
        "insights": {k: v.get("value") for k, v in (state.get("userInsights") or {}).items()},
        "learnedPatterns": len(profile.get("learnedPatterns") or [])
                           + len(((state.get("projectProfiles") or {}).get(PROJECT["id"]) or {}).get("learnedPatterns") or []),
        "feedbackCount": len((state.get("projectFeedback") or {}).get(PROJECT["id"]) or []),
        "records": len(state.get("executionRecords") or []),
    }


def make_plan(app, monday, week, *, proposal_id=None, label="새 주 계획"):
    body = {"goal": PROJECT["goal"], "startDate": monday.isoformat(), "consent": True, "project": PROJECT,
            "events": [], "existingTasks": [], "memories": []}
    if proposal_id:
        body["profileChangeProposalId"] = proposal_id
    else:
        body["merge"] = True
    errors = []
    for _ in range(PLAN_ATTEMPTS):
        try:
            draft = app.call("/api/execution/plan", **body)["planDraft"]
            confirmed = app.call("/api/execution/plan/confirm", planId=draft["id"], project=PROJECT, events=[])
            week["plans"].append({"label": label, "at": datetime.now(KST).isoformat(timespec="minutes"),
                                  "tasks": tasks_of(confirmed["plan"]), "pending": draft.get("pendingTasks") or [],
                                  "personalization": draft.get("personalization") or [], "errors": errors})
            return confirmed["plan"]
        except ApiError as exc:
            errors.append(str(exc))
            if proposal_id and exc.status == 400 and "다음 계획부터" in str(exc.detail):
                break
    week["plans"].append({"label": label, "at": datetime.now(KST).isoformat(timespec="minutes"), "tasks": [],
                          "pending": [], "personalization": [], "errors": errors, "failed": True})
    return None


def approve_pending(app, monday, week):
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
        # As in the app: approving replans what is left of the week.
        entry["replanned"] = make_plan(app, monday, week, proposal_id=proposal["id"],
                                       label=f"승인 후 재계획 ({proposal.get('ruleVersion')})") is not None
        week["proposals"].append(entry)


def weekly_feedback(persona, week):
    outcomes = [o for d in week["days"] for o in d["outcomes"]]
    note = persona.remarks[0] if persona.remarks else ""
    if not outcomes:
        return {"load": "right", "timeFit": "unknown", "note": note}
    done = sum(o["result"] == "completed" for o in outcomes) / len(outcomes)
    reasons = Counter(o["reason"] for o in outcomes if o["reason"])
    top = reasons.most_common(1)[0][0] if reasons else None
    time_fit = {"task_too_large": "too_long", "underestimated": "too_short", "time_shortage": "too_short"}.get(top, "right")
    return {"load": "too_much" if done < 0.6 else "right", "timeFit": time_fit, "note": note}


def run_persona(persona, weeks, out_dir: Path):
    log, rng = [], random.Random(f"{persona.id}-{os.getenv('SIM_SEED', '1')}")
    result = {"persona": persona.id, "weeks": [], "started": datetime.now().isoformat(timespec="seconds")}
    store = ExecutionStore(out_dir / f"{persona.id}.sqlite3")
    with time_machine.travel(at(FIRST_MONDAY, 7), tick=True) as clock:
        client = TestClient(create_app(execution_store=store, execution_llm=LoggingLLM(ExecutionLLM(), log)),
                            raise_server_exceptions=False)
        app = App(client)
        app.call("/api/execution/profile", answers=SURVEY)
        app.call("/api/execution/profile/confirm")
        result["start"] = snapshot(app.state())
        check_ins = 0
        for index in range(weeks):
            monday = FIRST_MONDAY + timedelta(weeks=index)
            who = at_week(persona, index + 1)  # how the person is this week
            clock.move_to(at(monday, 7))
            week = {"week": index + 1, "monday": monday.isoformat(), "plans": [], "days": [], "proposals": []}
            app.call("/api/execution/settings", method="put", settings={"slots": SLOTS, "view": "timeline"})
            if make_plan(app, monday, week):
                for offset in range(7):
                    day = monday + timedelta(days=offset)
                    plan = app.state()["plan"]
                    todays = [t for t in tasks_of(plan) if t["start"][:10] == day.isoformat() and not t["completed"]]
                    if not todays:
                        continue
                    clock.move_to(at(day, 22, 30))
                    entry = check_in(app, who, todays, rng, check_ins, log)
                    week["days"].append(entry)
                    if not entry.get("skipped"):
                        check_ins += 1
                        approve_pending(app, monday, week)
                clock.move_to(at(monday + timedelta(days=6), 21))
                feedback = weekly_feedback(who, week)
                try:
                    app.call(f"/api/execution/projects/{PROJECT['id']}/feedback", **feedback)
                except ApiError as exc:
                    feedback["error"] = str(exc)
                week["feedback"] = feedback
            week["end"] = snapshot(app.state())
            result["weeks"].append(week)
        client.close()
    result["llm"] = log
    result["finished"] = datetime.now().isoformat(timespec="seconds")
    (out_dir / f"{persona.id}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return result


def check_in(app, persona, todays, rng, count, log):
    outcomes = play_day(persona, todays, rng)
    session = day_session(persona, outcomes)
    if rng.random() < persona.skip:
        # They did the day but never told the app about it.
        return {"date": todays[0]["start"][:10], "outcomes": [asdict(o) for o in outcomes], "session": session,
                "skipped": True}
    asked = [q["key"] for q in app.client.get("/api/execution/insights", params={"projectId": PROJECT["id"]}).json()["next"]]
    remark = persona.remarks[count // 3 % len(persona.remarks)] if persona.remarks and count % 3 == 1 else None
    written = None
    if os.getenv("SIM_WRITER", "1") == "1":
        answers = {key: persona.answers[key] for key in asked if key in persona.answers}
        written = writer.write(persona, outcomes, session, answers, remark, log)
    if written:
        text, per_task, said = written
        for o in outcomes:
            o.said_minutes, o.said_reason = per_task[o.task_id]
    else:
        text, said = check_in_text(persona, outcomes, session, asked, remark, rng)
    day = {"date": todays[0]["start"][:10], "outcomes": [asdict(o) for o in outcomes], "session": session,
           "said": said, "asked": asked, "remark": remark, "text": text, "words": "ai" if written else "template"}
    try:
        state = app.call("/api/execution/chat/check-in", consent=True, project=PROJECT, text=text, asked=asked,
                         results=[{"taskId": o.task_id, "result": o.result} for o in outcomes])
        action = state["plannerThreads"][PROJECT["id"]]["action"]
        payload = action["payload"]
        day["extracted"] = {"records": payload["records"], "insights": payload.get("insights") or {},
                            "session": payload.get("session") or {}}
        app.call("/api/execution/chat/check-in/confirm", project=PROJECT, actionId=action["id"])
    except ApiError as exc:
        day["error"] = str(exc)
    return day
