"""Daily-life cases: one person, several projects in the same week.

The single-project experiment (personas.py) has one project, the 정처기 실기
4 weeks.  Here a case (``Scenario``) is a set of projects that run at the same
time, the hours chosen every week and the fixed things on the calendar (a
part-time job).  A person's hidden truth has two layers, like the app's data:

- the person (shared by every project): focus, the part of the day that suits
  them, how much they can do in a whole day, a lower limit on days with a job;
- the person in one kind of work (``Habit``): how much longer it takes than
  planned, a different part of the day (exercise in the evening), its own focus.

What the goal itself says (``주 3회``) is a fact about the project, not the
person: the person does it that many times a week and skips extra sessions.

Nothing here may shape app code (server/tests/test_sim_separation.py).
"""
from dataclasses import dataclass, field
from datetime import date, timedelta

from .personas import COMMON_ANSWERS, FIRST_MONDAY, SURVEY

STRETCH = 120   # a task never runs past the chosen hours it sits in; the shortest chosen stretch here is 2 hours


@dataclass(frozen=True)
class Project:
    id: str
    kind: str                    # study | exercise | reading | tidy | writing: which Habit of the person applies
    title: str
    goal: str
    weeks: int                   # from the first Monday; the due date is that week's Sunday
    per_week: int | None = None  # sessions a week the goal says (the person skips the extra ones)
    per_day: int | None = None   # sessions a day the goal allows
    hours: tuple = ()            # ((day, hour), ...) the person does it at, told on the new-project form; () = "딱히 없어요"

    def due(self):
        return FIRST_MONDAY + timedelta(days=7 * self.weeks - 1)

    def context(self):
        """The project as the screens send it."""
        return {"id": self.id, "title": self.title, "goal": self.goal,
                "startDate": FIRST_MONDAY.isoformat(), "dueDate": self.due().isoformat()}


@dataclass(frozen=True)
class Event:
    """A fixed weekly thing on the calendar (sent as a busy event, like the calendar screen does)."""
    day: int        # 0 = Monday
    start: str      # "17:00"
    end: str
    title: str


@dataclass(frozen=True)
class Scenario:
    id: str
    label: str
    purpose: str
    survey: dict
    slots: tuple                 # ((day, hour), ...) chosen every week
    projects: tuple              # in the order the person plans them (one project chat after another)
    events: tuple = ()

    def project(self, project_id):
        return next(p for p in self.projects if p.id == project_id)

    def events_for(self, monday: date):
        return [{"date": (monday + timedelta(days=e.day)).isoformat(), "startTime": e.start, "endTime": e.end}
                for e in self.events]


@dataclass(frozen=True)
class Habit:
    """How the person does one kind of work (None: as the person does everything)."""
    pace: float = 1.0
    focus: int | None = None
    best: str | None = None       # "morning" | "evening"; None: the person's own
    off_focus: float | None = None
    place: str | None = None


@dataclass(frozen=True)
class LifePerson:
    id: str
    label: str
    focus: int = 60
    best: str | None = None
    off_focus: float = 1.0
    capacity: int | None = None       # minutes a whole day holds, every project together
    busy_capacity: int | None = None  # minutes a day holds when the calendar has a fixed thing that day (job)
    noise: float = 0.08
    day_noise: float = 0.1
    skip: float = 0.0
    phrasing: str = "plain"
    habits: dict = field(default_factory=dict)  # kind -> Habit
    answers: dict = field(default_factory=dict)
    remarks: tuple = ()
    told: dict = field(default_factory=dict)

    def habit(self, kind):
        return self.habits.get(kind) or Habit()

    def at(self, kind, period):
        """(focus minutes, pace) for this kind of work in this part of the day."""
        h = self.habit(kind)
        best = h.best or self.best
        off = h.off_focus if h.off_focus is not None else self.off_focus
        focus = h.focus or self.focus
        return focus * (1.0 if best in (None, period) else off), h.pace

    def ideal(self, kind, period=None):
        """Planned minutes they can finish in one go: at the best time, or at ``period``."""
        h = self.habit(kind)
        if period is None:
            focus = h.focus or self.focus
        else:
            focus = self.at(kind, period)[0]
        return min(focus, STRETCH) / h.pace

    def best_for(self, kind):
        return self.habit(kind).best or self.best


def hours(days, hs):
    return tuple((d, h) for d in days for h in hs)


WEEKDAYS = range(5)

STUDY = Project("life-study", "study", "정보처리기사 실기 준비", "정보처리기사 실기 시험 대비: 이론 정리와 문제 풀이", weeks=4)
# The gym hours are the person's own (told when making the project): a student goes on Mon/Wed/Fri evenings,
# a worker on Tue/Thu after work and Saturday morning.
GYM = Project("life-gym", "exercise", "운동 습관", "체력 관리: 4주 동안 주 3회 운동하기", weeks=4, per_week=3, per_day=1,
              hours=((0, 19), (2, 19), (4, 19)))
GYM_AFTER_WORK = Project("life-gym", "exercise", "운동 습관", "체력 관리: 4주 동안 주 3회 운동하기", weeks=4, per_week=3, per_day=1,
                         hours=((1, 21), (3, 21), (5, 10)))
TOEIC = Project("life-toeic", "study", "토익 800점", "8주 안에 토익 800점: LC·RC 공부와 문제 풀이", weeks=8)
LETTERS = Project("life-letters", "writing", "자기소개서 3곳", "2주 안에 자기소개서 3곳 써서 제출하기", weeks=2)
READING = Project("life-reading", "reading", "독서", "한 달 동안 책 2권 읽기", weeks=4)
MOVE = Project("life-move", "tidy", "이사 준비", "2주 뒤 이사: 방 정리하고 짐 싸기", weeks=2)

SCENARIOS = [
    Scenario("study_gym", "공부 + 운동 주 3회 (공부 먼저 계획)",
             "매일 하지 않는 일(운동 주 3회)이 공부와 한 주를 나눌 때. 먼저 계획한 프로젝트가 시간을 다 가져가는지",
             SURVEY, hours(WEEKDAYS, (10, 11, 19, 20)), (STUDY, GYM)),
    Scenario("gym_study", "공부 + 운동 주 3회 (운동 먼저 계획)",
             "위와 같은 사람·같은 프로젝트에 계획 순서만 바꿈. 결과가 순서에 따라 달라지면 앱이 순서에 기대는 것",
             SURVEY, hours(WEEKDAYS, (10, 11, 19, 20)), (GYM, STUDY)),
    Scenario("job_study", "알바하면서 토익 8주 + 자소서 2주",
             "다른 일정(알바 화·목 저녁, 토 오후) 사이에 끼워 하는 일, 마감이 가까운 프로젝트를 나중에 계획할 때, 2주 뒤 프로젝트 끝내기",
             {**SURVEY, "roles": ["job_seeker"]}, hours(WEEKDAYS, (10, 11, 19, 20, 21)) + hours((5,), (10, 11, 12)),
             (TOEIC, LETTERS),
             events=(Event(1, "17:00", "21:00", "알바"), Event(3, "17:00", "21:00", "알바"), Event(5, "14:00", "18:00", "알바"))),
    Scenario("worker_life", "직장인: 독서 + 운동 주 3회 + 이사 준비 2주",
             "프로젝트 셋, 끝이 흐릿한 일(독서·정리), 평일 저녁 2시간과 주말 오전뿐인 시간, 마감 있는 일을 마지막에 계획할 때",
             {**SURVEY, "roles": ["employee"]}, hours(WEEKDAYS, (20, 21)) + hours((5, 6), (10, 11, 12)),
             (READING, GYM_AFTER_WORK, MOVE)),
]
SCENARIO_BY_ID = {s.id: s for s in SCENARIOS}

HOME = {**COMMON_ANSWERS, "place": "주로 집에서 해요.", "atmosphere": "조용한 곳이 좋아요.",
        "distractions": "보통 알림 때문에 집중이 깨져요.", "task_order": "보통 쉬운 것부터 해요."}
HOME_TOLD = {"tone": "polite", "atmosphere": "quiet", "task_order": "easy_first", "place": "집"}
GYM_HABIT = {"exercise": Habit(place="헬스장")}

PEOPLE = [
    LifePerson("ctl", "대조군: 설문 그대로인 사람", habits=GYM_HABIT, answers=HOME, told=HOME_TOLD,
               remarks=("요즘 특별히 힘든 건 없어요.",)),
    LifePerson("cap", "하루에 모든 일 합쳐 150분이면 지치는 사람", capacity=150, habits=GYM_HABIT, answers=HOME, told=HOME_TOLD,
               remarks=("하루에 이것저것 많이 하면 금방 지쳐요.",)),
    LifePerson("pace", "공부만 계획보다 1.4배 걸리는 사람 (다른 일은 그대로)", habits={**GYM_HABIT, "study": Habit(pace=1.4)},
               answers=HOME, told=HOME_TOLD, remarks=("공부는 생각보다 늘 오래 걸려요.",)),
    LifePerson("split", "머리 쓰는 일은 오전, 운동은 저녁이 잘 되는 사람",
               habits={"study": Habit(best="morning", off_focus=0.5), "reading": Habit(best="morning", off_focus=0.5),
                       "writing": Habit(best="morning", off_focus=0.5),
                       "exercise": Habit(best="evening", off_focus=0.5, place="헬스장")},
               answers=HOME, told=HOME_TOLD, remarks=("공부는 아침이 잘 되고 운동은 저녁이 편해요.",)),
    LifePerson("job", "알바 있는 날엔 60분밖에 못 하는 사람", busy_capacity=60, answers=HOME, told=HOME_TOLD,
               remarks=("알바 있는 날은 집에 오면 너무 피곤해요.",)),
]
PERSON_BY_ID = {p.id: p for p in PEOPLE}

# Who plays which case: the control and the three shared-truth types everywhere, the job type where there is a job.
CAST = {
    "study_gym": ("ctl", "cap", "pace", "split"),
    "gym_study": ("ctl", "cap", "pace", "split"),
    "job_study": ("ctl", "cap", "pace", "job"),
    "worker_life": ("ctl", "cap", "pace", "split"),
}


def players(only=""):
    """(scenario, person) pairs, as "scenario.person" ids; ``only`` filters by scenario or full id."""
    keep = [x for x in only.split(",") if x]
    out = []
    for scenario in SCENARIOS:
        for pid in CAST[scenario.id]:
            uid = f"{scenario.id}.{pid}"
            if not keep or scenario.id in keep or uid in keep:
                out.append(uid)
    return out


def resolve(uid):
    sid, pid = uid.split(".")
    return SCENARIO_BY_ID[sid], PERSON_BY_ID[pid]


def expect_for(person, scenario):
    """What a good planner does for this person in this case, from the truth, one formula for everyone."""
    bits = []
    kinds = list(dict.fromkeys(p.kind for p in scenario.projects))
    lengths = {k: round(person.ideal(k)) for k in kinds}
    if len(set(lengths.values())) == 1:
        bits.append(f"작업 {next(iter(lengths.values()))}분 이하")
    else:
        bits.append("작업 길이 " + ", ".join(f"{scenario_title(scenario, k)} {v}분" for k, v in lengths.items()))
    bests = {k: person.best_for(k) for k in kinds}
    if any(bests.values()):
        bits.append(", ".join(f"{scenario_title(scenario, k)} {PART.get(b, '아무 때나')}" for k, b in bests.items()))
    if person.capacity:
        bits.append(f"모든 프로젝트 합쳐 하루 {person.capacity}분 근처")
    if person.busy_capacity:
        bits.append(f"알바 있는 날은 합쳐서 {person.busy_capacity}분 근처")
    for p in scenario.projects:
        if p.per_week:
            bits.append(f"{p.title} 주 {p.per_week}회·하루 {p.per_day or '여러'}번까지")
    return " · ".join(bits)


PART = {"morning": "오전", "evening": "저녁", "afternoon": "오후"}


def scenario_title(scenario, kind):
    return next(p.title for p in scenario.projects if p.kind == kind)

