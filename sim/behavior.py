"""How a virtual user really gets through a planned day, and what they say about it.

A day is played on the clock: a task starts when the one before it ended (an
overrun pushes the rest back), and stops when it is done, when the person's
focus runs out, when the stretch of planned time ends, or when they are spent
for the day.  The words follow the outcome so the check-in AI has something to
read; durations are written as "N분" once per sentence so a quote holds one.
"""
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

BREAK = 5
STRETCH_GAP = 10  # tasks closer than this belong to one stretch of planned time


def part_of_day(hour):
    return "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"


@dataclass
class Outcome:
    task_id: str
    title: str
    start: str
    planned: int
    result: str          # completed | partial | not_started
    actual: int
    reason: str | None   # REASON code the person would pick, None when done
    why: str             # what limited them (for the report): done/focus/off_time/time/spent/pace/interrupted
    sentence: str
    said_minutes: int | None = None  # the minutes their words state (None: they did not say a number)
    said_reason: str | None = None   # the reason their words state


def _round5(minutes):
    return max(5, int(round(minutes / 5.0)) * 5)


def _stretch_ends(tasks):
    """When the time the person set aside runs out for each task: the end of the chosen hours it sits in.

    The person keeps going into free time they chose (a plan that leaves time free
    is using that), but not past the chosen hours, or past a later task's start
    when tasks were planned outside the chosen hours.
    """
    from .personas import SLOTS
    chosen = {(s["day"], s["hour"]) for s in SLOTS}
    ends = {}
    for task in tasks:
        start = datetime.fromisoformat(task["start"])
        day, hour = start.weekday(), start.hour
        if (day, hour) in chosen:
            while (day, hour + 1) in chosen:
                hour += 1
            ends[task["id"]] = start.replace(hour=hour, minute=0) + timedelta(hours=1)
        else:
            ends[task["id"]] = datetime.fromisoformat(task["end"])
    return ends


def play_day(persona, tasks, rng: random.Random):
    """Outcomes of one day's tasks, in the order they were planned."""
    tasks = sorted(tasks, key=lambda t: t["start"])
    ends = _stretch_ends(tasks)
    cursor, used, outcomes = None, 0, []
    today = rng.uniform(1 - persona.day_noise, 1 + persona.day_noise)  # some days go better than others
    for task in tasks:
        planned = task["minutes"]
        start = datetime.fromisoformat(task["start"])
        pushed = bool(cursor and cursor > start)
        if pushed:
            start = cursor
        left_in_stretch = max(0, int((ends[task["id"]] - start).total_seconds() // 60))
        period = part_of_day(start.hour)
        focus = persona.focus * today * (1.0 if persona.best in (None, period) else persona.off_focus)
        spent_left = None if persona.capacity is None else max(0, persona.capacity - used)
        need = planned * persona.pace
        limits = {"focus" if persona.best in (None, period) else "off_time": focus, "time": left_in_stretch}
        if spent_left is not None:
            limits["spent"] = spent_left
        why, room = min(limits.items(), key=lambda kv: kv[1])
        if rng.random() < persona.noise and need <= room:
            worked, result, why = _round5(planned / 2), "partial", "interrupted"
        elif need <= room:
            # Exact minutes: rounding up here would push the next task late and fake a shortage.
            worked, result = int(round(need)), "completed"
            why = "pace" if persona.pace > 1 else "done"
        elif room < 5:
            worked, result = 0, "not_started"
        else:
            worked, result = _round5(min(room, need)), "partial"
            # Started on time and the planned time was there: the work itself took longer.
            if persona.pace > 1 and ((why == "focus" and planned <= persona.focus) or (why == "time" and not pushed)):
                why = "pace"
        reason = None if result == "completed" else {
            "focus": "task_too_large", "off_time": "fatigue", "time": "time_shortage",
            "spent": "fatigue", "pace": "underestimated", "interrupted": "interruption"}[why]
        if persona.phrasing == "casual":
            text, said_minutes, said_reason = casual_sentence(task["title"], result, worked, why, reason, rng)
        else:
            text = sentence(task["title"], result, worked, why, planned)
            said_minutes, said_reason = (worked if result != "not_started" else None), reason
        outcomes.append(Outcome(task["id"], task["title"], task["start"], planned, result, worked, reason, why,
                                text, said_minutes, said_reason))
        used += worked
        cursor = start + timedelta(minutes=worked + BREAK)
    return outcomes


def sentence(title, result, worked, why, planned):
    name = f"‘{title}’"
    if result == "completed":
        if worked > planned:
            return f"{name}은 계획보다 길게 {worked}분 걸려서 겨우 끝냈어요."
        return f"{name}은 {worked}분 동안 해서 끝냈어요."
    if result == "not_started":
        return {"spent": f"{name}은 이미 지쳐서 시작도 못 했어요.",
                "time": f"{name}은 앞 작업이 길어져서 시작도 못 했어요."}.get(why, f"{name}은 시작도 못 했어요.")
    return {
        "focus": f"{name}은 {worked}분쯤 하다가 집중이 끊겼어요. 한 번에 하기엔 작업이 너무 컸어요.",
        "off_time": f"{name}은 {worked}분 했는데 피곤해서 더는 못 하겠더라고요.",
        "time": f"{name}은 앞 작업이 길어져서 {worked}분밖에 못 했어요. 시간이 모자랐어요.",
        "spent": f"{name}은 {worked}분 하다가 지쳐서 그만뒀어요.",
        "pace": f"{name}은 {worked}분 했는데 생각보다 오래 걸려서 다 못 끝냈어요.",
        "interrupted": f"{name}은 {worked}분 하다가 갑자기 다른 일이 생겨서 멈췄어요.",
    }[why]


def casual_sentence(title, result, worked, why, reason, rng):
    """Short, loose words; some leave the minutes or the reason out (then the truth is None)."""
    name = f"‘{title}’"
    if result == "completed":
        options = [(f"{name} {worked}분 걸려서 끝", worked, None), (f"{name} 끝!", None, None)]
    elif result == "not_started":
        options = [(f"{name} 못 함", None, None), (f"{name} 지쳐서 못 함", None, "fatigue")] if why == "spent" \
            else [(f"{name} 못 함", None, None), (f"{name} 시간 없어서 못 함", None, "time_shortage")]
    else:
        options = {
            "focus": [(f"{name} 한 {worked}분? 하다가 집중 끊김. 너무 길었음", worked, "task_too_large"),
                      (f"{name} 하다 말았음. 너무 커서", None, "task_too_large"),
                      (f"{name} {worked}분 하고 그만", worked, None)],
            "time": [(f"{name} 시간 모자라서 {worked}분만", worked, "time_shortage")],
            "off_time": [(f"{name} {worked}분 하다 피곤해서 그만", worked, "fatigue"), (f"{name} 피곤해서 조금만 함", None, "fatigue")],
            "spent": [(f"{name} {worked}분 하다 지쳐서 그만", worked, "fatigue"), (f"{name} 지쳐서 조금만 함", None, "fatigue")],
            "pace": [(f"{name} {worked}분 했는데 생각보다 오래 걸려서 못 끝냄", worked, "underestimated")],
            "interrupted": [(f"{name} {worked}분 하다가 일 생겨서 멈춤", worked, "interruption")],
        }[why]
    return options[rng.randrange(len(options))]


FOCUS_CASUAL = {"good": "집중 잘 됨", "ok": "집중 그럭저럭", "poor": "집중 별로"}
CONDITION_CASUAL = {"good": "컨디션 좋음", "ok": "컨디션 보통", "poor": "컨디션 별로"}

FOCUS_WORDS = {"good": "잘 됐어요", "ok": "그럭저럭이었어요", "poor": "잘 안 됐어요"}
CONDITION_WORDS = {"good": "좋았어요", "ok": "보통이었어요", "poor": "별로였어요"}


def day_session(persona, outcomes):
    done = sum(o.result == "completed" for o in outcomes) / len(outcomes)
    focus = "good" if done == 1 else "ok" if done >= 0.5 else "poor"
    tired = any(o.why in ("spent", "off_time") for o in outcomes)
    condition = "poor" if tired else "good" if done == 1 else "ok"
    place = persona.answers.get("place", "").replace("주로 ", "").replace("에서 해요.", "") or "집"
    return {"place": place, "focus": focus, "condition": condition}


def check_in_text(persona, outcomes, session, asked, remark, rng=None):
    """One answer, as a person would type it after tapping how each task went.

    Returns the text and what it says about the day (None where it says nothing).
    """
    parts = [o.sentence for o in outcomes]
    said = {"focus": session["focus"], "condition": session["condition"]}
    if persona.phrasing == "casual":
        if rng is not None and rng.random() < 0.3:
            said = {"focus": None, "condition": None}
        else:
            parts.append(f"{session['place']}에서 함. {FOCUS_CASUAL[session['focus']]}, {CONDITION_CASUAL[session['condition']]}")
    else:
        parts.append(f"오늘은 {session['place']}에서 했어요. 집중은 {FOCUS_WORDS[session['focus']]}, "
                     f"컨디션은 {CONDITION_WORDS[session['condition']]}.")
    parts += [persona.answers[key] for key in asked if key in persona.answers]
    if remark:
        parts.append(remark)
    return " ".join(parts), said
