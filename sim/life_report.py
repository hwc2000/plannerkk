"""Checks for the daily-life cases (several projects at once) and their report page.

Every check uses one formula for every person, from the hidden truth in life.py:

| check            | question                                                                  |
| ---------------- | ------------------------------------------------------------------------- |
| plan_failed      | could each project be planned at all in its week?                         |
| starved          | did an active project get no task in a week?                              |
| quota_week/day   | a goal of "주 n회": more sessions in the week than n, or two in one day?   |
| over_capacity    | every project together: more planned in a day than the person can do?     |
| event_overlap    | a task on top of a fixed thing in the calendar (job)?                      |
| learned          | each approved change: right value, and learned in the right layer?        |
| carried          | ending a project: does what moved to the user profile fit the others?     |
| place_mismatch   | a place suggestion that belongs to another project                        |
| depth            | task titles with made-up detail (chapters, pages, sets)                   |
| reading          | did the check-in AI read the words right (minutes, reasons)?              |
| errors           | check-ins, approvals or replans that the app refused                      |
"""
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from .life import PART, resolve
from .life import expect_for
from .review import CSS, chip, esc

LOAD_TOLERANCE = 1.15
TOLERANCE = 0.25
PACE_FROM = 1.15     # work whose real pace is under this has no pace to learn
# "운동 2회차" is a count of sessions, not made-up content, so 회차 is not here (unlike review.py).
DEPTH = re.compile(r"\d+\s*(장|쪽|페이지|세트|km|킬로|챕터)|챕터|기출|모의고사|교재|단원|\d+\s*p\b")

ISSUES = {
    "plan_failed": "프로젝트 계획이 안 만들어짐",
    "starved": "진행 중인 프로젝트가 한 주 동안 작업 0개",
    "quota_week": "‘주 n회’ 목표인데 한 주에 n번보다 많이 계획",
    "quota_day": "‘주 n회’ 목표인데 하루에 두 번 이상 계획",
    "quota_bunched": "‘주 n회’ 목표인데 n번을 더 적은 날에 몰아서 계획",
    "over_capacity": "모든 프로젝트를 합친 하루량이 그 사람 한계를 넘음",
    "event_overlap": "달력의 고정 일정(알바)과 겹친 작업",
    "learned_wrong": "승인된 변경이 틀린 값",
    "learned_scope": "승인된 변경이 다른 층에서 배움 (사람 값↔프로젝트 값)",
    "carried_wrong": "프로젝트를 끝낼 때 다른 프로젝트엔 안 맞는 값이 기본 프로필로",
    "own_hours_left": "정한 요일·시간 밖에 놓인 작업",
    "own_hours_taken": "다른 프로젝트가 정한 요일·시간을 쓴 작업",
    "place_mismatch": "다른 프로젝트의 장소를 제안",
    "depth": "작업 이름에 지어낸 세부(장·쪽·세트 등)",
    "checkin_error": "체크인이 거절됨",
    "approve_failed": "변경 카드 승인이 거절됨",
    "replan_failed": "승인 뒤 재계획 실패",
    "unowned": "어느 프로젝트에도 속하지 않은 작업",
}


def project_ideal(person, kind):
    """(shortest, longest) planned minutes that fit one go: at their weakest and best part of the day."""
    best = person.ideal(kind)
    weak = min(person.ideal(kind, period) for period in ("morning", "evening"))
    return weak, best


def within(value, low, high):
    return low * (1 - TOLERANCE) <= value <= high * (1 + TOLERANCE)


def judge_change(scenario, person, x):
    """(verdict, why) for one approved change: ok | wrong | scope | None (no rule to judge)."""
    project = next((p for p in scenario.projects if p.id == x.get("projectId")), None)
    kinds = list(dict.fromkeys(p.kind for p in scenario.projects))
    several = len(scenario.projects) > 1
    for key, change in x["changes"].items():
        before, after = change.get("from"), change.get("to")
        if key == "dailyPlannedMinutes":
            if person.capacity is None and person.busy_capacity is None:
                return "wrong", f"하루 한계가 없는 사람에게 하루 {after}분 상한"
            if person.capacity is None:
                return "wrong", f"알바 있는 날만 {person.busy_capacity}분인데 모든 날에 {after}분 상한 (요일 차이를 모름)"
            if project and several:
                return "scope", (f"하루 한계 {person.capacity}분은 모든 프로젝트를 합친 값인데, ‘{project.title}’ 기록만 보고 "
                                 f"그 프로젝트에만 {after}분 상한")
            ok = isinstance(after, int) and abs(after - person.capacity) <= person.capacity * TOLERANCE
            return ("ok" if ok else "wrong"), f"진짜 하루 한계 {person.capacity}분, 정한 값 {after}분"
        if key == "pacePercent":
            paces = {p.kind: person.habit(p.kind).pace for p in scenario.projects}
            if project:
                truth = paces[project.kind]
                if truth < PACE_FROM:
                    return "wrong", f"‘{project.title}’은 계획대로 걸리는데(×{truth}) 배율 {after}%"
                ok = abs(after / 100 - truth) <= truth * TOLERANCE
                return ("ok" if ok else "wrong"), f"‘{project.title}’ 진짜 배율 ×{truth}, 정한 값 {after}%"
            if len(set(paces.values())) > 1:
                return "scope", f"배율이 프로젝트마다 다른데({paces}) 기본 프로필에 {after}%"
            truth = next(iter(paces.values()))
            return ("ok" if truth >= PACE_FROM and abs(after / 100 - truth) <= truth * TOLERANCE else "wrong"), f"진짜 배율 ×{truth}"
        if key == "blockMinutes" and isinstance(after, int):
            if project:
                low, high = project_ideal(person, project.kind)
                if within(after, low, high) or (isinstance(before, int) and abs(after - high) < abs(before - high)):
                    return "ok", f"‘{project.title}’ 한 번에 할 수 있는 길이 {low:.0f}~{high:.0f}분 쪽"
                return "wrong", f"‘{project.title}’ 한 번에 할 수 있는 길이 {low:.0f}~{high:.0f}분에서 멀어짐 ({before}→{after})"
            ranges = {k: project_ideal(person, k) for k in kinds}
            bad = [k for k, (low, high) in ranges.items() if not within(after, low, high)]
            if bad:
                return "scope", f"기본 프로필 {after}분이 맞지 않는 일: " + ", ".join(f"{k} {ranges[k][0]:.0f}~{ranges[k][1]:.0f}분" for k in bad)
            return "ok", "모든 프로젝트에 맞는 길이"
        if key == "periodMinutes" and isinstance(after, dict):
            targets = [project] if project else list(scenario.projects)
            for period, minutes in after.items():
                if (before or {}).get(period) == minutes:
                    continue
                for p in targets:
                    best = person.best_for(p.kind)
                    if best is None or best == period:
                        return ("wrong" if project else "scope"), \
                            f"‘{p.title}’은 {PART.get(period, period)}에 약하지 않은데 그 시간대만 {minutes}분"
            return "ok", "약한 시간대를 짧게"
        if key == "focusTime":
            bests = {p.title: person.best_for(p.kind) for p in scenario.projects}
            if len(set(bests.values())) > 1:
                return "scope", ("잘 되는 시간대가 프로젝트마다 다른데 하나로 정함: "
                                 + ", ".join(f"{t} {PART.get(b, '아무 때나')}" for t, b in bests.items()) + f" → {PART.get(after, after)}")
            truth = next(iter(bests.values()))
            if truth is None:
                return "wrong", f"시간대 성향이 없는 사람에게 {PART.get(after, after)}"
            return ("ok" if after == truth else "wrong"), f"진짜 {PART.get(truth)}"
    return None, "판단 기준 없음"


def judge_carry(scenario, person, closed_id, item, still_open):
    """A value moved to the user profile when a project ended: it will drive every other project."""
    if item.get("key") != "blockMinutes":
        return None, "판단 기준 없음"
    value = int(str(item["to"]).rstrip("분"))
    others = [p for p in scenario.projects if p.id in still_open]
    if not others:
        return None, "남은 프로젝트 없음"
    bad = [p for p in others if not within(value, *project_ideal(person, p.kind))]
    if bad:
        return "wrong", "남은 프로젝트에 안 맞음: " + ", ".join(
            f"{p.title} {project_ideal(person, p.kind)[0]:.0f}~{project_ideal(person, p.kind)[1]:.0f}분" for p in bad)
    return "ok", "남은 프로젝트에도 맞음"


def overlaps(o, busy):
    start = datetime.fromisoformat(o["start"])
    end = start.timestamp() + o["planned"] * 60
    return any(b0.timestamp() < end and b1.timestamp() > start.timestamp() for b0, b1 in busy)


def busy_of(scenario, day):
    from .life_play import busy_on
    return busy_on(scenario, datetime.fromisoformat(day).date())


def chosen_minutes(scenario, monday):
    """Minutes of the hours the person chose that week, less the fixed things on the calendar."""
    from datetime import date, timedelta
    total = 0
    for day, hour in scenario.slots:
        when = date.fromisoformat(monday) + timedelta(days=day)
        begin, end = datetime.fromisoformat(f"{when}T{hour:02d}:00"), datetime.fromisoformat(f"{when}T{hour:02d}:00") + timedelta(hours=1)
        busy = sum(max(0, (min(end, b1) - max(begin, b0)).total_seconds() / 60) for b0, b1 in busy_of(scenario, when.isoformat()))
        total += 60 - busy
    return total


def analyse(uid, result):
    scenario, person = resolve(uid)
    projects = {p.id: p for p in scenario.projects}
    home = person.answers.get("place", "").replace("주로 ", "").replace("에서 해요.", "") or "집"
    issues = defaultdict(list)
    weeks, titles, places = [], defaultdict(set), {}
    reading = {"checks": 0, "hits": 0, "misses": [], "quotaReasons": Counter()}

    for w in result["weeks"]:
        outs = [o for d in w["days"] for o in d["outcomes"]]
        total = sum(o["planned"] for o in outs) or 1
        row = {"week": w["week"], "projects": {}, "days": [], "plans": w["plans"], "proposals": [], "feedback": w.get("feedback"),
               "closed": w.get("closed") or {}, "end": w.get("end"),
               "fill": round(sum(o["planned"] for o in outs) / chosen_minutes(scenario, w["monday"]), 2)}
        for plan in w["plans"]:
            for t in plan["tasks"]:
                if t["projectId"] in projects:
                    titles[t["projectId"]].add(t["title"])
                    if t.get("place"):
                        places[t["id"]] = (t["projectId"], t["title"], t["place"], w["week"])
            if plan.get("failed"):
                what = (plan["errors"] or ["?"])[-1]
                if plan["label"].startswith("승인"):
                    # No time left in the week: the screen says the change applies from the next plan.
                    if "사용 가능한 시간이 없습니다" in what or "다음 계획부터" in what:
                        continue
                    issues["replan_failed"].append({"week": w["week"], "project": plan["project"], "what": what})
                else:
                    issues["plan_failed"].append({"week": w["week"], "project": plan["project"], "what": what})
        for pid in w["active"]:
            p = projects[pid]
            mine = [o for o in outs if o["project_id"] == pid]
            played = [o for o in mine if o["why"] != "quota"]
            info = {"tasks": len(mine), "minutes": sum(o["planned"] for o in mine),
                    "share": round(sum(o["planned"] for o in mine) / total, 2),
                    "completion": round(sum(o["result"] == "completed" for o in played) / len(played), 2) if played else None,
                    "finished": sum(o["planned"] for o in played if o["result"] == "completed"),
                    "avgTask": round(sum(o["planned"] for o in mine) / len(mine)) if mine else None}
            if not mine:
                issues["starved"].append({"week": w["week"], "project": pid, "what": "작업 0개"})
            if p.per_week:
                per_day = sessions_by_day(mine)
                count = sum(per_day.values())
                info.update(sessions=count, parts=len(mine), maxPerDay=max(per_day.values()) if mine else 0,
                            skipped=len(mine) - len(played), sessionDays=len(per_day))
                if count > p.per_week:
                    issues["quota_week"].append({"week": w["week"], "project": pid,
                                                 "what": f"{count}번 계획 (목표 주 {p.per_week}회), {len(mine) - len(played)}개는 안 함"})
                over = {d: c for d, c in per_day.items() if c > (p.per_day or 99)}
                if over:
                    issues["quota_day"].append({"week": w["week"], "project": pid,
                                                "what": ", ".join(f"{d[5:]} {c}번" for d, c in sorted(over.items()))})
                if count and len(per_day) < min(count, p.per_week):
                    issues["quota_bunched"].append({"week": w["week"], "project": pid,
                                                    "what": f"{count}번을 {len(per_day)}일에 ("
                                                            + ", ".join(f"{d[5:]} {c}번" for d, c in sorted(per_day.items())) + ")"})
            row["projects"][pid] = info
        for d in w["days"]:
            limit = person.busy_capacity if d["busy"] and person.busy_capacity else person.capacity
            by_project = Counter()
            for o in d["outcomes"]:
                by_project[o["project_id"]] += o["planned"]
            planned = sum(by_project.values())
            done = sum(o["actual"] for o in d["outcomes"])
            day = {"date": d["date"], "busy": d["busy"], "planned": planned, "worked": done, "limit": limit,
                   "byProject": dict(by_project), "outcomes": d["outcomes"], "checkIns": d["checkIns"]}
            row["days"].append(day)
            if limit and planned > limit * LOAD_TOLERANCE:
                issues["over_capacity"].append({"week": w["week"], "project": None,
                                                "what": f"{d['date'][5:]} 계획 {planned}분 (한계 {limit}분): "
                                                        + ", ".join(f"{projects[k].title} {v}분" for k, v in by_project.items())})
            busy = busy_of(scenario, d["date"])
            for o in d["outcomes"]:
                start = datetime.fromisoformat(o["start"])
                slot = (start.weekday(), start.hour)
                mine = projects[o["project_id"]].hours
                if mine and slot not in mine:
                    issues["own_hours_left"].append({"week": w["week"], "project": o["project_id"], "what": f"{o['start'][5:16]} {o['title']}"})
                if not mine and any(slot in p.hours for p in projects.values() if p.id != o["project_id"]):
                    issues["own_hours_taken"].append({"week": w["week"], "project": o["project_id"], "what": f"{o['start'][5:16]} {o['title']}"})
                if busy and overlaps(o, busy):
                    issues["event_overlap"].append({"week": w["week"], "project": o["project_id"], "what": f"{o['start'][5:16]} {o['title']}"})
            for t in d.get("unowned") or []:
                issues["unowned"].append({"week": w["week"], "project": None, "what": f"{t['start'][5:16]} {t['title']}"})
            for c in d["checkIns"]:
                if c.get("error"):
                    issues["checkin_error"].append({"week": w["week"], "project": c["project"], "what": c["error"]})
                if "extracted" not in c:
                    continue
                records = {r["taskId"]: r for r in c["extracted"]["records"]}
                for o in c["outcomes"]:
                    r = records.get(o["task_id"])
                    if r is None:
                        continue
                    if o["why"] == "quota":
                        reading["quotaReasons"][r.get("reasonCode") or "없음"] += 1
                    pairs = []
                    if o["result"] != "not_started":
                        pairs.append(("분", o.get("said_minutes"), r.get("actualMinutes"), o["actual"]))
                    if o["result"] != "completed":
                        pairs.append(("이유", o.get("said_reason"), r.get("reasonCode"), o["reason"]))
                    for field, said, got, real in pairs:
                        ok = said == got or (said is None and got == real)
                        reading["checks"] += 1
                        reading["hits"] += ok
                        if not ok:
                            reading["misses"].append({"date": d["date"], "task": o["title"], "field": field, "said": said, "got": got,
                                                      "words": (c.get("text") or "")[:200]})
        for x in w["proposals"]:
            if not x.get("approved"):
                if "이미 처리한" not in (x.get("error") or ""):
                    issues["approve_failed"].append({"week": w["week"], "project": x.get("projectId"), "what": x.get("error")})
                continue
            verdict, why = judge_change(scenario, person, x)
            judged = {**x, "verdict": verdict, "why": why}
            row["proposals"].append(judged)
            if verdict in ("wrong", "scope"):
                issues["learned_wrong" if verdict == "wrong" else "learned_scope"].append(
                    {"week": w["week"], "project": x.get("projectId"), "what": f"{x['rule']}: {change_words(x['changes'])} — {why}"})
        for pid, closed in (w.get("closed") or {}).items():
            still_open = [p for p in (w.get("end") or {}).get("projects", {}) if p not in ((w.get("end") or {}).get("closed") or [])]
            for item in (closed.get("result") or {}).get("carried") or []:
                verdict, why = judge_carry(scenario, person, pid, item, still_open)
                item["verdict"], item["why"] = verdict, why
                if verdict == "wrong":
                    issues["carried_wrong"].append({"week": w["week"], "project": pid, "what": f"{item['label']} {item['from']}→{item['to']} — {why}"})
        weeks.append(row)

    for task_id, (pid, title, place, week) in places.items():
        truth = person.habit(projects[pid].kind).place or home
        if place != truth:
            issues["place_mismatch"].append({"week": week, "project": pid, "what": f"‘{title}’에 {place} (그 일은 보통 {truth})"})
    for pid, names in titles.items():
        for name in sorted(names):
            if DEPTH.search(name):
                issues["depth"].append({"week": None, "project": pid, "what": name})
    reading["rate"] = round(reading["hits"] / reading["checks"], 2) if reading["checks"] else None
    reading["quotaReasons"] = dict(reading["quotaReasons"])
    return {"uid": uid, "scenario": scenario.id, "person": person.id, "label": person.label,
            "expect": expect_for(person, scenario), "weeks": weeks, "issues": dict(issues),
            "titles": {pid: sorted(v) for pid, v in titles.items()}, "reading": reading,
            "start": result.get("start"), "llm": Counter(c.get("name") for c in result.get("llm", []))}


def sessions_by_day(outcomes, gap=10):
    """Sessions per day of one project: tasks planned back to back (within ``gap`` minutes) are one session."""
    from datetime import timedelta
    days = Counter()
    by_day = defaultdict(list)
    for o in outcomes:
        by_day[o["start"][:10]].append(o)
    for day, items in by_day.items():
        end = None
        for o in sorted(items, key=lambda o: o["start"]):
            start = datetime.fromisoformat(o["start"])
            if end is None or start - end > timedelta(minutes=gap):
                days[day] += 1
            end = start + timedelta(minutes=o["planned"])
    return days


def change_words(changes):
    parts = []
    for key, c in changes.items():
        name = {"blockMinutes": "작업 길이", "dailyPlannedMinutes": "하루량", "pacePercent": "배율", "periodMinutes": "시간대별 길이",
                "focusTime": "시간대", "recoveryPreference": "복구 방식"}.get(key, key)
        frm, to = c.get("from"), c.get("to")
        if key == "focusTime":
            frm, to = PART.get(frm, frm or "모름"), PART.get(to, to)
        if key == "periodMinutes":
            to = ", ".join(f"{PART.get(k, k)} {v}분" for k, v in (to or {}).items())
            frm = ", ".join(f"{PART.get(k, k)} {v}분" for k, v in (frm or {}).items()) or "없음"
        parts.append(f"{name} {frm}→{to}")
    return ", ".join(parts)


def order_effect(people):
    """The same person and projects planned in the opposite order (study_gym vs gym_study)."""
    rows = []
    by = {(a["scenario"], a["person"]): a for a in people}
    for (sid, pid), a in by.items():
        if sid != "study_gym" or ("gym_study", pid) not in by:
            continue
        b = by[("gym_study", pid)]
        line = {"person": pid, "label": a["label"], "weeks": []}
        for wa, wb in zip(a["weeks"], b["weeks"]):
            pa, pb = wa["projects"], wb["projects"]
            line["weeks"].append({
                "week": wa["week"],
                "studyFirst": {"study": pa.get("life-study", {}).get("minutes"), "gym": pa.get("life-gym", {}).get("sessions")},
                "gymFirst": {"study": pb.get("life-study", {}).get("minutes"), "gym": pb.get("life-gym", {}).get("sessions")},
            })
        rows.append(line)
    return rows


# ---------------------------------------------------------------- page

def chips_for(a):
    out = []
    for kind, label in ISSUES.items():
        n = len(a["issues"].get(kind) or [])
        if n:
            out.append(chip("fail", label, n))
    return "".join(out) or chip("pass", "자동 점검에서 걸린 것 없음")


def issue_table(people):
    rows = []
    for kind, label in ISSUES.items():
        hit = [(a, i) for a in people for i in a["issues"].get(kind) or []]
        if not hit:
            continue
        who = Counter(a["uid"] for a, _ in hit)
        examples = "".join(f"<li><span class='muted'>{esc(a['uid'])}{' · ' + str(i['week']) + '주' if i['week'] else ''}</span> "
                           f"{esc(i['what'])}</li>" for a, i in hit[:4])
        rows.append(f"<tr><th>{esc(label)}</th><td class='num'>{len(hit)}</td><td class='num'>{len(who)}/{len(people)}</td>"
                    f"<td><ul class='plain'>{examples}</ul></td></tr>")
    return ("<div class='scroll'><table><thead><tr><th>문제</th><th>건수</th><th>사람</th><th>예 (최대 4개)</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table></div>") if rows else "<p>자동 점검에 걸린 것이 없습니다.</p>"


def grid(people, scenario_id):
    """Week × project for every person in one case: tasks, minutes, finished share."""
    from .life import SCENARIO_BY_ID
    scenario = SCENARIO_BY_ID[scenario_id]
    head = "".join(f"<th>{w}주</th>" for w in range(1, max(len(a["weeks"]) for a in people) + 1))
    body = []
    for a in people:
        cells = "".join(f"<td class='num'>{w['fill']:.0%}</td>" for w in a["weeks"])
        body.append(f"<tr><th>{esc(a['person'])}<br><small class='muted'>고른 시간 중 계획한 비율</small></th>{cells}</tr>")
        for p in scenario.projects:
            cells = []
            for w in a["weeks"]:
                info = w["projects"].get(p.id)
                if info is None:
                    cells.append("<td class='muted'>끝남</td>")
                    continue
                failed = any(x.get("failed") and x["project"] == p.id and not x["label"].startswith("승인") for x in w["plans"])
                done = "—" if info["completion"] is None else f"{info['completion']:.0%}"
                extra = f" · {info['sessions']}회/{info['sessionDays']}일" if "sessions" in info else ""
                mark = chip("fail", "계획 실패") if failed else ""
                cells.append(f"<td class='num'>{mark}{info['tasks']}개 {info['minutes']}분{extra}<br><small class='muted'>"
                             f"비중 {info['share']:.0%} · 완료 {done}</small></td>")
            body.append(f"<tr><th>{esc(a['person'])}<br><small class='muted'>{esc(p.title)}</small></th>{''.join(cells)}</tr>")
    return f"<div class='scroll'><table class='grid'><thead><tr><th>사람 · 프로젝트</th>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"


def day_rows(a):
    from .life import SCENARIO_BY_ID
    scenario = SCENARIO_BY_ID[a["scenario"]]
    titles = {p.id: p.title for p in scenario.projects}
    rows = []
    for w in a["weeks"]:
        for d in w["days"]:
            tags = []
            for o in sorted(d["outcomes"], key=lambda o: o["start"]):
                cls = {"completed": "done", "partial": "part", "not_started": "miss"}[o["result"]]
                why = " 목표 채움" if o["why"] == "quota" else ""
                tags.append(f"<span class='t {cls}' title='{esc(o['title'])}'>{esc(o['start'][11:16])} "
                            f"<b>{esc(titles.get(o['project_id'], '?')[:4])}</b> {o['planned']}→{o['actual']}{why}</span>")
            over = d["limit"] and d["planned"] > d["limit"] * LOAD_TOLERANCE
            limit = f" / 한계 {d['limit']}" if d["limit"] else ""
            rows.append(f"<tr><th class='num'>{esc(d['date'][5:])}{' 알바' if d['busy'] else ''}</th>"
                        f"<td class='num'>{'<b class="miss">' if over else ''}{d['planned']}분{'</b>' if over else ''}{limit}</td>"
                        f"<td>{''.join(tags)}</td></tr>")
    return ("<div class='scroll'><table class='grid'><thead><tr><th>날</th><th>합친 계획</th><th>작업 (시각 · 프로젝트 · 계획→실제분)</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>")


def person_block(a):
    from .life import SCENARIO_BY_ID
    scenario = SCENARIO_BY_ID[a["scenario"]]
    titles = {p.id: p.title for p in scenario.projects}
    changes = []
    for w in a["weeks"]:
        for x in w["proposals"]:
            kind = {"ok": "pass", "wrong": "fail", "scope": "warn"}.get(x["verdict"], "na")
            where = titles.get(x.get("projectId"), "기본 프로필")
            changes.append(f"<li>{chip(kind, {'ok': '맞음', 'wrong': '틀림', 'scope': '층 다름'}.get(x['verdict'], '판단 없음'))} "
                           f"<span class='num muted'>{esc(x['at'][5:16])}</span> <b>{esc(where)}</b> {esc(change_words(x['changes']))}"
                           f"<br><small class='muted'>{esc(x['rule'])} · {esc(x['why'])}</small></li>")
        for pid, c in w["closed"].items():
            carried = (c.get("result") or {}).get("carried") or []
            text = ", ".join(f"{i['label']} {i['from']}→{i['to']}" + (f" ({i.get('why')})" if i.get("why") else "") for i in carried) or "넘긴 값 없음"
            changes.append(f"<li>{chip('na', '프로젝트 끝냄')} <b>{esc(titles.get(pid))}</b> {esc(text)}"
                           + (f" <span class='miss'>{esc(c['error'])}</span>" if c.get("error") else "") + "</li>")
    end = a["weeks"][-1]["end"] if a["weeks"] else {}
    final = [f"기본 프로필: {esc(json.dumps({k: v for k, v in (end.get('profile') or {}).items() if v is not None}, ensure_ascii=False))}"]
    for pid, values in (end.get("projects") or {}).items():
        if values:
            final.append(f"{esc(titles.get(pid))}: {esc(json.dumps(values, ensure_ascii=False))}")
    names = "".join(f"<li><b>{esc(titles.get(pid))}</b> {esc(' / '.join(v))}</li>" for pid, v in a["titles"].items())
    issues = "".join(f"<li><b>{esc(ISSUES[k])}</b>: " + esc("; ".join(i["what"] for i in v[:6])) + (" …" if len(v) > 6 else "") + "</li>"
                     for k, v in a["issues"].items())
    r = a["reading"]
    return f"""<details class="person"><summary><b>{esc(a['uid'])}</b><span>{esc(a['label'])}</span>
<span class="chips">{chips_for(a)}</span></summary><div>
<p class="muted">좋은 계획이라면: {esc(a['expect'])}</p>
<section><h3>걸린 것</h3><ul class="plain">{issues or '<li>없음</li>'}</ul></section>
<section><h3>배운 것 (승인된 변경)</h3><ul class="plain">{''.join(changes) or '<li>없음</li>'}</ul>
<p class="mins">4주 끝: {' · '.join(final)}</p></section>
<section><h3>날마다</h3>{day_rows(a)}</section>
<section><h3>작업 이름 (전체)</h3><ul class="plain">{names}</ul></section>
<p class="mins">체크인 읽기 {r['rate'] if r['rate'] is not None else '—'} ({r['hits']}/{r['checks']}) · 목표 채워 안 한 날 기록된 이유 {esc(json.dumps(r['quotaReasons'], ensure_ascii=False))}</p>
</div></details>"""


def findings_html(findings):
    """What the person reviewing the run concluded (findings.json beside the run), shown first."""
    if not findings:
        return ""
    items = []
    for f in findings:
        evidence = "".join(f"<li>{esc(e)}</li>" for e in f.get("evidence") or [])
        kind = {"bad": "fail", "known": "warn", "good": "pass"}.get(f.get("kind"), "na")
        label = {"bad": "문제", "known": "알던 문제", "good": "잘 됨"}.get(f.get("kind"), "참고")
        items.append(f"<div class='sheet' style='display:grid;gap:6px'><div class='chips'>{chip(kind, label)}</div>"
                     f"<h3>{esc(f['title'])}</h3><p>{esc(f['detail'])}</p>"
                     + (f"<ul class='plain mins'>{evidence}</ul>" if evidence else "")
                     + (f"<p class='mins'>코드: {esc(f['code'])}</p>" if f.get("code") else "") + "</div>")
    return f"<section><h2>찾은 것</h2>{''.join(items)}</section>"


def seeds_table(people, others, label=None):
    """Issue counts in this run beside other runs of the same cases (other seeds): does it repeat?"""
    if not others:
        return ""
    runs = [("이 실험" + (f" ({label})" if label else ""), people), *others]
    rows = []
    for kind, label in ISSUES.items():
        counts = [sum(len(a["issues"].get(kind) or []) for a in group) for _, group in runs]
        whom = [sum(1 for a in group if a["issues"].get(kind)) for _, group in runs]
        if not any(counts):
            continue
        rows.append(f"<tr><th>{esc(label)}</th>" + "".join(f"<td class='num'>{c}건 · {w}명</td>" for c, w in zip(counts, whom)) + "</tr>")
    head = "".join(f"<th>{esc(name)}</th>" for name, _ in runs)
    return (f"<section><h2>다른 실험과 나란히</h2><p class='muted'>같은 상황·같은 사람으로 돌린 다른 실험(다른 씨앗, 또는 앱을 고치기 전)입니다. "
            f"씨앗이 같으면 사람·하루 컨디션이 같고, AI 답만 다릅니다.</p>"
            f"<div class='scroll'><table><thead><tr><th>문제</th>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>")


def render(run, people, order, findings=None, others=()):
    from .life import SCENARIOS
    cases = []
    for s in SCENARIOS:
        mine = [a for a in people if a["scenario"] == s.id]
        if not mine:
            continue
        events = ", ".join(f"{'월화수목금토일'[e.day]} {e.start}–{e.end} {e.title}" for e in s.events) or "없음"
        slots = Counter(d for d, _ in s.slots)
        hours_text = ", ".join(f"{'월화수목금토일'[d]} {n}시간" for d, n in sorted(slots.items()))
        cases.append(f"""<section class="sheet"><div class="eyebrow">{esc(s.id)}</div><h2>{esc(s.label)}</h2>
<p class="muted">{esc(s.purpose)}</p>
<div class="facts"><span>계획 순서 <b>{esc(' → '.join(p.title for p in s.projects))}</b></span><span>고른 시간 <b>{esc(hours_text)}</b></span>
<span>고정 일정 <b>{esc(events)}</b></span></div>
<div class="facts">{''.join(f"<span>{esc(p.title)}: <b>{esc(p.goal)}</b> ({p.weeks}주)</span>" for p in s.projects)}</div>
{grid(mine, s.id)}
{''.join(person_block(a) for a in mine)}</section>""")
    order_rows = "".join(
        f"<tr><th>{esc(o['person'])}<br><small class='muted'>{esc(o['label'])}</small></th>"
        + "".join(f"<td class='num'>공부 {w['studyFirst']['study'] or 0}분 · 운동 {w['studyFirst']['gym'] or 0}회<br>"
                  f"<small class='muted'>운동 먼저: 공부 {w['gymFirst']['study'] or 0}분 · 운동 {w['gymFirst']['gym'] or 0}회</small></td>"
                  for w in o["weeks"]) + "</tr>" for o in order)
    order_html = (f"<section class='sheet'><h2>계획 순서만 바꾸면</h2><p class='muted'>같은 사람·같은 두 프로젝트. 위 줄은 공부를 먼저, 아래 줄은 운동을 먼저 계획했을 때입니다.</p>"
                  f"<div class='scroll'><table class='grid'><thead><tr><th>사람</th>{''.join(f'<th>{i}주</th>' for i in range(1, run['weeks'] + 1))}</tr></thead>"
                  f"<tbody>{order_rows}</tbody></table></div></section>") if order else ""
    calls = Counter()
    for a in people:
        calls.update(a["llm"])
    return f"""<title>{esc(run.get("title") or "여러 프로젝트 병행 실험")}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+KR:wght@400;600;700&display=swap">
<style>{CSS}</style>
<div class="wrap">
<header style="display:grid;gap:8px"><div class="eyebrow">Re:plan 체크인 실험 · {esc(run['name'])}</div>
<h1>여러 프로젝트를 같이 할 때</h1>
<p>한 사람이 프로젝트 2~3개를 같은 주에 진행합니다. 매주 프로젝트 대화방마다 차례로 계획을 만들고, 저녁마다 프로젝트별로 체크인하고, 앱이 내미는 변경 카드를 모두 승인합니다.
가상 사용자의 진짜 성향은 앱이 모르고, 아래 점검은 모두 같은 공식으로 그 진짜 성향과 비교합니다.</p>
<div class="facts"><span>상황 <b>{len(cases)}개</b></span><span>사람 <b>{len(people)}명</b></span><span>기간 <b>{run['weeks']}주</b></span>
<span>계획·체크인 AI <b>{esc(run['model'])}</b></span><span>체크인 글 <b>{esc(run['writer'])}</b></span>
<span>AI 호출 <b>{sum(calls.values())}회</b></span><span>시작 <b>{esc(run['started'])}</b></span></div></header>
{findings_html(findings)}
<section><h2>자동 점검에서 걸린 것</h2>{issue_table(people)}</section>
{seeds_table(people, others, run.get("label"))}
{order_html}
{''.join(cases)}
</div>"""


def collect(out_dir):
    out_dir = Path(out_dir)
    run = json.loads((out_dir / "run.json").read_text())
    run["name"] = out_dir.name
    people, errors = [], {}
    for uid in run["players"]:
        path = out_dir / f"{uid}.json"
        if not path.exists():
            error = out_dir / f"{uid}.error.txt"
            errors[uid] = error.read_text()[-3000:] if error.exists() else "결과 파일 없음"
            continue
        people.append(analyse(uid, json.loads(path.read_text())))
    return run, people, errors


def build(out_dir, others=()):
    """The run's life.json and report.html; ``others``: runs of the same cases with other seeds, to compare."""
    out_dir = Path(out_dir)
    run, people, errors = collect(out_dir)
    order = order_effect(people)
    (out_dir / "life.json").write_text(json.dumps({"run": run, "errors": errors, "people": people, "order": order},
                                                  ensure_ascii=False, indent=1, default=str))
    compared = []
    for other in others:
        other_run, other_people, _ = collect(other)
        label = (other_run.get("label") or "") + f" {other_run['name']} (씨앗 {other_run['seed']})"
        compared.append((label.strip(), other_people))
    notes = out_dir / "findings.json"
    findings = json.loads(notes.read_text()) if notes.exists() else None
    page = out_dir / "report.html"
    page.write_text(render(run, people, order, findings, compared))
    return page


if __name__ == "__main__":
    # .venv/bin/python -m sim.life_report sim/out/<run> [sim/out/<other seed run> ...]
    print(build(sys.argv[1], sys.argv[2:]))
