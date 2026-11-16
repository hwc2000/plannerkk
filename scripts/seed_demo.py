"""Fill an exhibition demo account with a week of history and this week's plan.

Everything goes through the app's own HTTP API, as the screens do, on a fake
clock: survey, three projects, a shared weekly plan, a week of check-ins, the
change the learning rules propose from them, its approval, and this week's plan
made with the approved value.  Only the plan AI is replaced: a scripted stand-in
writes the task titles, so no OpenAI credit is needed.  Placement, validation,
learning rules and proposals are the real code.

    .venv/bin/python scripts/seed_demo.py            # writes data/demo.sqlite3 (replaces it)
    REPLAN_DB_PATH=data/demo.sqlite3 .venv/bin/python run_local.py

Run it again on the day of the exhibition: dates are counted from today.
"""
import argparse
import os
import sys
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path

import time_machine
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY") or "demo-no-calls"

from server.app.execution_profile import generate_profile  # noqa: E402
from server.app.main import create_app  # noqa: E402

KST = timezone(timedelta(hours=9))
EMAIL, PASSWORD, NAME = "demo@replan.kr", "replan2026", "전시 체험"

SURVEY = {"roles": ["student"], "regularity": "irregular", "barriers": ["overplanning"], "focusMinutes": 60,
          "dailyMinutes": None, "energy": "unknown", "recovery": "unknown", "constraints": "", "context": "",
          "scheduleStyle": "time_blocks"}
# Weekdays 10-12 and 19-21, Saturday morning: the hours the demo user picks every week.
SLOTS = [{"day": d, "hour": h} for d in range(5) for h in (10, 11, 19, 20)] + [{"day": 5, "hour": h} for h in (10, 11)]

TEMPLATES = {
    "study": [("정처기 실기 (SQL) 문제 풀이", "SQL 문제 풀이 채점"), ("정처기 실기 (C언어 코드) 공부", "코드 문제 풀이 채점"),
              ("정처기 실기 (Java) 공부", "Java 문제 풀이 채점"), ("정처기 실기 (데이터베이스) 이론 정리", "핵심 개념 노트 정리"),
              ("정처기 실기 (운영체제·네트워크) 이론 정리", "핵심 개념 노트 정리"), ("정처기 실기 오답 복습", "틀린 문제 다시 풀기")],
    "toeic": [("토익 LC 공부", "LC 문제 풀이 채점"), ("토익 RC 공부", "RC 문제 풀이 채점"), ("토익 단어 복습", "단어 테스트 기록")],
    "gym": [("헬스장 운동", "운동 기록 남기기")],
}
GOALS = {"study": "정보처리기사 실기 시험 대비: 이론 정리와 문제 풀이", "toeic": "토익 800점: LC·RC 공부와 문제 풀이",
         "gym": "체력 관리: 주 3회 운동하기"}
TITLES = {"study": "정보처리기사 실기", "toeic": "토익 800점", "gym": "운동 주 3회"}


class DemoLLM:
    """Stands in for the plan AI only; never called for anything that teaches the profile."""

    async def generate(self, **kwargs):
        if kwargs["name"] == "execution_profile":
            return generate_profile(SURVEY)["insights"]
        if kwargs["name"].startswith("planner_"):
            return {"reply": "좋아요"}
        context = kwargs["context"]
        projects = context.get("projects") or []
        caps = {p["id"]: p.get("maxBlockMinutes") or context["maxBlockMinutes"] for p in projects}
        # Fill the week's slots in order, the way a person would split a day: study in the morning,
        # TOEIC in the evening, the gym on three evenings.  A slot holds as many tasks of the
        # project's length as fit, with the 5-minute breaks.
        tasks, gym_left = [], 3 if "gym" in caps else 0
        for index, day in enumerate(context.get("daySlots") or []):
            lengths = day["minutes"]
            for j, length in enumerate(lengths):
                evening = j >= len(lengths) / 2
                if evening and gym_left and index % 2 == 0 and j == len(lengths) // 2:
                    pid, gym_left = "gym", gym_left - 1
                else:
                    pid = ("toeic" if evening else "study") if "toeic" in caps else "study"
                if pid not in caps:
                    continue
                cap = caps[pid]
                minutes = min(cap, length)
                for k in range(max(1, (length + 5) // (minutes + 5))):
                    review = minutes < cap or k > 0
                    tasks.append(self._task(pid, len(tasks), minutes, review))
        while tasks and sum(t["minutes"] for t in tasks) > context["budgetMinutes"]:
            tasks.pop()
        return {"tasks": tasks}

    @staticmethod
    def _task(pid, index, minutes, review=False):
        options = TEMPLATES[pid]
        title, done = options[-1] if review and len(options) > 1 else options[index % max(1, len(options) - 1)]
        return {"title": title, "minutes": minutes, "doneWhen": done, "dueDate": None, "projectId": pid}


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, dtime(hour, minute), KST)


class Demo:
    def __init__(self, client):
        self.client, self.revision = client, None

    def call(self, path, method="post", **body):
        payload = {"revision": self.revision, **body} if self.revision is not None else body
        response = getattr(self.client, method)(path, json=payload)
        if response.status_code != 200:
            raise SystemExit(f"{path} {response.status_code}: {response.text}")
        data = response.json()
        if isinstance(data, dict) and "revision" in data:
            self.revision = data["revision"]
        return data

    def state(self):
        data = self.client.get("/api/execution").json()
        self.revision = data["revision"]
        return data


def project(pid, monday):
    return {"id": pid, "title": TITLES[pid], "goal": GOALS[pid], "startDate": (monday - timedelta(days=14)).isoformat(),
            "dueDate": (monday + timedelta(days={"study": 20, "toeic": 41, "gym": 27}[pid])).isoformat(),
            "priority": "high" if pid == "study" else "medium", "status": "active"}


def context(p):
    return {k: p[k] for k in ("id", "title", "goal", "startDate", "dueDate")}


def plan_week(demo, start, projects):
    demo.call("/api/execution/settings", method="put", settings={"slots": SLOTS, "view": "timeline"})
    lead = projects[0]
    draft = demo.call("/api/execution/plan", goal=lead["goal"], startDate=start.isoformat(), consent=True,
                      project=context(lead), projects=[context(p) for p in projects], merge=True,
                      events=[], existingTasks=[], memories=[])["planDraft"]
    return demo.call("/api/execution/plan/confirm", planId=draft["id"], project=draft["project"], events=[])["plan"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(ROOT / "data" / "demo.sqlite3"))
    args = parser.parse_args()
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()

    today = datetime.now(KST).date()
    history_start = today - timedelta(days=7)
    monday = today - timedelta(days=today.weekday())
    projects = [project(pid, monday) for pid in ("study", "toeic", "gym")]
    app = create_app(execution_llm=DemoLLM(), auth=True, db_path=db)

    with time_machine.travel(at(history_start, 8), tick=False) as clock, TestClient(app) as client:
        demo = Demo(client)
        demo.call("/api/auth/signup", email=EMAIL, password=PASSWORD, displayName=NAME)
        demo.call("/api/workspace", method="put", projects=projects, milestones=[], events=[], memories=[])
        demo.state()
        demo.call("/api/execution/profile", answers=SURVEY)
        demo.call("/api/execution/profile/confirm")

        # Last week: one shared plan for the three projects, then a check-in every evening.
        plan = plan_week(demo, history_start, projects)
        done = {"study": 0, "toeic": 0}
        keep = {"study": 2, "toeic": 0}  # sessions that went fine before the misses
        for offset in range(7):
            day = history_start + timedelta(days=offset)
            clock.move_to(at(day, 22))
            for entry in sorted((e for e in plan["entries"] if e["kind"] == "task" and e["start"][:10] == day.isoformat()),
                                key=lambda e: e["start"]):
                owner = entry.get("projectId")
                if owner == "gym" or done.get(owner, 9) < keep.get(owner, 0):
                    demo.call("/api/execution/task", planId=plan["id"], taskId=entry["id"], completed=True)
                    if owner in done:
                        done[owner] += 1
                    continue
                if owner == "toeic" and entry["minutes"] < 60:
                    continue  # short TOEIC reviews: no check-in that evening
                # Study stops at half its hour for lack of time; TOEIC sessions turn out too big.
                worked = max(5, round(entry["minutes"] * (0.5 if owner == "study" else 0.6) / 5) * 5)
                demo.call("/api/execution/records", planId=plan["id"], taskId=entry["id"], result="partial",
                          actualMinutes=worked, remainingMinutes=entry["minutes"] - worked,
                          reasonCode="time_shortage" if owner == "study" else "task_too_large", consent=False)

        # Sunday evening: the user approves the study change; the TOEIC one waits for the exhibition.
        clock.move_to(at(today - timedelta(days=1), 21))
        pending = [p for p in demo.state()["profileUpdateProposals"] if p["status"] == "pending"]
        study = next((p for p in pending if p.get("projectId") == "study"), None)
        if study is None:
            raise SystemExit(f"study proposal missing; pending: {[(p.get('projectId'), p['proposedChanges']) for p in pending]}")
        demo.call(f"/api/execution/proposals/{study['id']}/approve")

        # This morning: this week's plan, made with the approved value.
        clock.move_to(at(today, 7, 30))
        plan = plan_week(demo, today, projects)

    state_tasks = [e for e in plan["entries"] if e["kind"] == "task"]
    waiting = [p for p in pending if p["status"] == "pending" and p.get("projectId") != "study"]
    print(f"demo DB: {db}")
    print(f"account: {EMAIL} / {PASSWORD}")
    print(f"this week: {len(state_tasks)} tasks, by project:",
          {pid: sorted({e['minutes'] for e in state_tasks if e.get('projectId') == pid}) for pid in TITLES})
    print("waiting proposals:", [(p.get("projectId"), p["proposedChanges"]) for p in waiting])


if __name__ == "__main__":
    main()
