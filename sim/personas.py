"""Virtual users: the same survey and project, a different hidden truth.

The truth (how the person really works) lives only in this package.  The app
sees what a real user would give it: survey answers, taps on how each task
went, and the words of a check-in.  ``expect`` is what a good planner should
end up doing for the person; the report compares it with what happened.

``holdout`` users are kept out of rule design: look only at the others while
changing the app, then check the holdout users did not get worse.
"""
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

FIRST_MONDAY = date(2026, 11, 9)
WEEKS_MAX = 4

# Everyone answers the survey the same way (onboarding as it is today).
SURVEY = {
    "roles": ["student"], "regularity": "regular", "barriers": ["none"],
    "focusMinutes": 60, "dailyMinutes": None, "energy": "unknown", "recovery": "replan",
    "constraints": "", "context": "", "scheduleStyle": "time_blocks",
}

PROJECT = {
    "id": "sim-project",
    "title": "정보처리기사 실기 준비",
    "goal": "정보처리기사 실기 시험 대비: 이론 정리와 문제 풀이",
    "startDate": FIRST_MONDAY.isoformat(),
    "dueDate": (FIRST_MONDAY + timedelta(days=7 * WEEKS_MAX - 1)).isoformat(),
}

# Hours chosen every week: weekdays 10-12 and 19-21 (two parts of the day, 4 hours a day).
SLOTS = [{"day": d, "hour": h} for d in range(5) for h in (10, 11, 19, 20)]


@dataclass(frozen=True)
class Persona:
    id: str
    label: str
    expect: str
    focus: int                    # minutes of real focus in a part of the day that suits them
    best: str | None = None       # "morning" or "evening"; None: any part of the day
    off_focus: float = 1.0        # focus multiplier outside ``best``
    pace: float = 1.0             # real time / planned time of a task
    capacity: int | None = None   # minutes of work a day before they are spent
    noise: float = 0.08           # chance a task is cut short by something else
    day_noise: float = 0.1        # focus varies this much from day to day (±)
    skip: float = 0.0             # chance they skip a day's check-in (the app never hears about that day)
    phrasing: str = "plain"       # "casual": short, loose words; some leave the minutes or the reason out
    changes: tuple = ()           # ((from_week, {field: value}), ...): how they change during the project
    holdout: bool = False
    # How they answer when a check-in asks about them (user_insights slots).
    answers: dict = field(default_factory=dict)
    # Things they say that fit no field: the catch-all channel.
    remarks: tuple = ()
    # What their answers mean in the check-in's fixed choices, for the reading test (place: a word it must keep).
    told: dict = field(default_factory=dict)


def at_week(p, week):
    """The person as they are in that week (a change applies from its week on)."""
    for start, values in p.changes:
        if week >= start:
            p = replace(p, **values)
    return p


COMMON_ANSWERS = {
    "tone": "존댓말이 편해요.",
    "focus_aids": "보통 휴대폰을 멀리 두면 집중이 잘 돼요.",
    "condition": "평소에 잠을 못 자면 컨디션이 확 떨어져요.",
    "rest": "쉴 때는 보통 잠깐 산책하는 게 잘 맞아요.",
}

PERSONAS = [
    Persona("steady", "대조군: 설문 그대로인 사람", "아무것도 바꾸지 않는다 (잘못 배우지 않는다)",
            focus=60, answers={**COMMON_ANSWERS, "place": "주로 집에서 해요.", "atmosphere": "조용한 곳이 좋아요.",
                               "distractions": "보통 알림 때문에 집중이 깨져요.", "task_order": "보통 쉬운 것부터 해요."},
            remarks=("요즘 특별히 힘든 건 없어요.",), told={"tone": "polite", "atmosphere": "quiet", "task_order": "easy_first", "place": "집"}),
    Persona("short_focus", "집중이 30분밖에 안 가는 사람", "작업 길이를 30분 근처로 줄인다",
            focus=30, answers={**COMMON_ANSWERS, "place": "주로 카페에서 해요.", "atmosphere": "적당히 소리 있는 카페 같은 곳이 잘 돼요.",
                               "distractions": "오래 앉아 있으면 딴생각이 나요.", "task_order": "보통 쉬운 것부터 해요."},
            remarks=("저는 한 번에 오래 앉아 있으면 집중이 금방 흐트러져요.",), told={"tone": "polite", "atmosphere": "lively", "task_order": "easy_first", "place": "카페"}),
    Persona("long_focus", "한 번에 2시간 가까이 몰입하는 사람", "작업 길이를 100분 이상으로 늘린다",
            focus=110, answers={**COMMON_ANSWERS, "place": "주로 도서관에서 해요.", "atmosphere": "조용한 곳이 좋아요.",
                                "distractions": "중간에 끊기면 흐름이 깨져요.", "task_order": "보통 어려운 것부터 해요."},
            remarks=("한번 시작하면 오래 하는 게 편해요. 중간에 끊기면 오히려 흐름이 깨져요.",), told={"tone": "polite", "atmosphere": "quiet", "task_order": "hard_first", "place": "도서관"}),
    Persona("morning", "오전엔 잘 되고 저녁엔 반밖에 못 하는 사람", "저녁보다 오전에 일을 몰고, 저녁 작업은 짧게 한다",
            focus=60, best="morning", off_focus=0.5,
            answers={**COMMON_ANSWERS, "place": "주로 도서관에서 해요.", "atmosphere": "조용한 곳이 좋아요.",
                     "distractions": "저녁엔 피곤해서 자꾸 멍해져요.", "task_order": "보통 어려운 것부터 해요."},
            remarks=("저녁엔 머리가 잘 안 돌아가요. 아침이 훨씬 잘 돼요.",), told={"tone": "polite", "atmosphere": "quiet", "task_order": "hard_first", "place": "도서관"}),
    Persona("slow", "뭐든 계획보다 1.4배 걸리는 사람", "작업 사이에 여유를 두거나 하루에 넣는 양을 줄인다",
            focus=120, pace=1.4,
            answers={**COMMON_ANSWERS, "place": "주로 집에서 해요.", "atmosphere": "상관없어요.",
                     "distractions": "꼼꼼히 하다 보면 시간이 훌쩍 가요.", "task_order": "보통 쉬운 것부터 해요."},
            remarks=("저는 뭐든 예상보다 오래 걸리는 편이에요.",), told={"tone": "polite", "atmosphere": "any", "task_order": "easy_first", "place": "집"}),
    Persona("low_capacity", "하루 2시간 하면 지치는 사람", "하루 계획량을 2시간 근처로 줄인다",
            focus=60, capacity=120,
            answers={**COMMON_ANSWERS, "place": "주로 집에서 해요.", "atmosphere": "조용한 곳이 좋아요.",
                     "distractions": "지치면 아무것도 손에 안 잡혀요.", "task_order": "보통 쉬운 것부터 해요."},
            remarks=("하루에 너무 많이 하면 금방 지쳐요.",), told={"tone": "polite", "atmosphere": "quiet", "task_order": "easy_first", "place": "집"}),
    Persona("mixed", "검증용: 짧은 집중 + 저녁형 + 하루 3시간", "작업 40분 근처, 저녁 위주, 하루 3시간 근처",
            focus=40, best="evening", off_focus=0.6, capacity=180, holdout=True,
            answers={**COMMON_ANSWERS, "place": "주로 스터디카페에서 해요.", "atmosphere": "조용한 곳이 좋아요.",
                     "distractions": "아침엔 잠이 덜 깨서 멍해요.", "task_order": "보통 어려운 것부터 해요."},
            remarks=("저녁에 하는 게 좀 더 잘 맞는 것 같아요.",), told={"tone": "polite", "atmosphere": "quiet", "task_order": "hard_first", "place": "스터디카페"}),
]

# Harder cases: the same truth as one above, worse data.  Each pairs with the user it copies,
# so the gap between the two is what the data quality costs.
SHORT_ANSWERS = {**COMMON_ANSWERS, "place": "주로 카페에서 해요.", "atmosphere": "적당히 소리 있는 카페 같은 곳이 잘 돼요.",
                 "distractions": "오래 앉아 있으면 딴생각이 나요.", "task_order": "보통 쉬운 것부터 해요."}
SHORT_TOLD = {"tone": "polite", "atmosphere": "lively", "task_order": "easy_first", "place": "카페"}
PERSONAS += [
    Persona("sparse", "체크인을 자주 빼먹는 30분형", "띄엄띄엄 기록해도 작업 길이를 30분 근처로 줄인다",
            focus=30, skip=0.4, answers=SHORT_ANSWERS, told=SHORT_TOLD,
            remarks=("저는 한 번에 오래 앉아 있으면 집중이 금방 흐트러져요.",)),
    Persona("casual", "짧고 대충 말하는 30분형", "말이 애매해도 30분으로 줄이고, 말하지 않은 숫자는 지어내지 않는다",
            focus=30, phrasing="casual", answers=SHORT_ANSWERS, told=SHORT_TOLD,
            remarks=("오래 앉아 있으면 집중 금방 깨짐",)),
    Persona("changing", "3주차부터 시험 기간으로 하루 2시간이면 지치는 사람", "1·2주차는 그대로, 3주차부터 하루 분량을 2시간 근처로 줄인다",
            focus=60, changes=((3, {"capacity": 120, "remarks": ("요즘 시험 기간이라 너무 피곤해요.",)}),),
            answers={**COMMON_ANSWERS, "place": "주로 집에서 해요.", "atmosphere": "조용한 곳이 좋아요.",
                     "distractions": "보통 알림 때문에 집중이 깨져요.", "task_order": "보통 쉬운 것부터 해요."},
            told={"tone": "polite", "atmosphere": "quiet", "task_order": "easy_first", "place": "집"},
            remarks=("요즘은 괜찮아요.",)),
]

BY_ID = {p.id: p for p in PERSONAS}

# Fresh users: drawn at random for every run, so no rule is ever shaped around them.
PLACES = ["집", "카페", "도서관", "스터디카페", "학교 열람실"]
ATMOSPHERES = {"quiet": "조용한 곳이 좋아요.", "lively": "적당히 소리 있는 곳이 잘 돼요.", "any": "상관없어요."}
ORDERS = {"hard_first": "보통 어려운 것부터 해요.", "easy_first": "보통 쉬운 것부터 해요.", "any": "순서는 상관없어요."}
STYLES = ["평범한 존댓말, 두세 문장", "짧은 반말", "대충 몇 마디, 숫자를 자주 빼먹음", "길게 설명하는 존댓말", "이모티콘을 가끔 쓰는 편한 말투"]


def make_fresh(count, seed):
    import random
    rng = random.Random(f"fresh-{seed}")
    people = []
    for n in range(count):
        focus = rng.choice([25, 30, 40, 45, 50, 60, 75, 90, 110])
        best = rng.choice([None, None, "morning", "evening"])
        off = round(rng.uniform(0.4, 0.8), 1) if best else 1.0
        pace = rng.choice([1.0, 1.0, 1.0, 1.2, 1.3, 1.5])
        capacity = rng.choice([None, None, 90, 120, 150, 180])
        changes = ()
        if rng.random() < 0.25:
            changes = ((3, {"capacity": rng.choice([90, 120])}),) if rng.random() < 0.5 else ((3, {"focus": max(20, focus - 20)}),)
        place = rng.choice(PLACES)
        atmosphere, order = rng.choice(list(ATMOSPHERES)), rng.choice(list(ORDERS))
        remarks = []
        if focus <= 40:
            remarks.append("오래 앉아 있으면 집중이 금방 깨져요.")
        if capacity:
            remarks.append("하루에 많이 하면 금방 지쳐요.")
        if pace > 1:
            remarks.append("생각보다 늘 오래 걸려요.")
        if best:
            remarks.append("아침이 훨씬 잘 돼요." if best == "morning" else "저녁에 더 잘 되는 편이에요.")
        p = Persona(
            f"fresh{n + 1:02d}", "", "", focus=focus, best=best, off_focus=off, pace=pace, capacity=capacity,
            skip=rng.choice([0.0, 0.0, 0.2, 0.4]), phrasing=rng.choice(STYLES), changes=changes, holdout=True,
            answers={**COMMON_ANSWERS, "place": f"주로 {place}에서 해요.", "atmosphere": ATMOSPHERES[atmosphere],
                     "distractions": rng.choice(["보통 알림 때문에 집중이 깨져요.", "옆에서 말 걸면 흐름이 끊겨요.", "배고프면 집중이 안 돼요."]),
                     "task_order": ORDERS[order]},
            told={"tone": "polite", "atmosphere": atmosphere, "task_order": order, "place": place},
            remarks=tuple(remarks) or ("요즘은 무난해요.",))
        people.append(replace(p, label=f"새 사용자 {n + 1}", expect=expect_for(p)))
    return people


def expect_for(p):
    """What a good planner does for this person, in words, from the truth (same rules as the tests)."""
    bits = [f"작업 {min(p.focus, 120) / p.pace:.0f}분 이하"]
    if p.best:
        bits.append(f"{'오전' if p.best == 'morning' else '저녁'} 위주, 다른 때 {min(p.focus * p.off_focus, 120) / p.pace:.0f}분 이하")
    if p.capacity:
        bits.append(f"하루 {p.capacity}분 근처")
    for start, values in p.changes:
        bits.append(f"{start}주차부터 " + ", ".join(f"하루 {v}분" if k == "capacity" else f"집중 {v}분" for k, v in values.items()))
    return " · ".join(bits)


def register(spec):
    """Add a user saved in a run's run.json (fresh users) so reports can read that run."""
    p = Persona(**{**spec, "changes": tuple((s, dict(v)) for s, v in spec.get("changes") or ()),
                   "remarks": tuple(spec.get("remarks") or ())})
    BY_ID[p.id] = p
    return p
