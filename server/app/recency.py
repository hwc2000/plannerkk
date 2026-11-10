"""How much a past record counts: the more recent, the more (recency-v1).

Before this, every rule read its records as a step: everything inside a window (14, 28
or 30 days) counted the same, and everything older counted nothing.  Now a record's
weight halves every ``HALF_LIFE_DAYS`` and reaches zero only past ``HORIZON_DAYS``:

    weight = 0.5 ** (age_days / HALF_LIFE_DAYS)      0 <= age_days < HORIZON_DAYS

so yesterday counts about twice as much as two weeks ago, and a long-time user's older
records still say something instead of being thrown away.

Age is in whole calendar days in Korea (Asia/Seoul), so records of the same day weigh
exactly the same, and a record dated in the future counts as today.

What is weighted and what is not:

- *values* decided from records (a share of finished tasks, a median of minutes) are
  weighted, so a change in the user's habits shows up sooner;
- *how much evidence* is needed (at least 3 records, at least 3 days) stays a real count:
  a few heavily weighted records are still only a few records.
"""
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
HALF_LIFE_DAYS = 14
HORIZON_DAYS = 90
RULE_VERSION = "recency-v1"


def kst_day(value):
    """The Korean calendar day of a date or timestamp; naive timestamps already mean KST."""
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date):
        return value
    else:
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return (moment if moment.tzinfo is None else moment.astimezone(KST)).date()


def today(now=None):
    now = now or datetime.now(KST)
    return now.date() if now.tzinfo is None else now.astimezone(KST).date()


def age_days(value, now=None):
    """Whole days since ``value`` (0 for today or a future day); None without a readable date."""
    day = kst_day(value)
    if day is None:
        return None
    return max(0, (today(now) - day).days)


def in_horizon(value, now=None, horizon=HORIZON_DAYS):
    age = age_days(value, now)
    return age is not None and age < horizon


def weight(value, now=None, half_life=HALF_LIFE_DAYS, horizon=HORIZON_DAYS):
    """How much a record of that day counts: 1 today, 0.5 a half-life ago, 0 past the horizon or undated."""
    age = age_days(value, now)
    if age is None or age >= horizon:
        return 0.0
    return 0.5 ** (age / half_life)


def weighted_share(pairs):
    """Weighted share of true flags in ``(flag, weight)`` pairs; None when nothing weighs."""
    total = sum(w for _, w in pairs)
    if total <= 0:
        return None
    return sum(w for flag, w in pairs if flag) / total


def weighted_median(pairs):
    """The value where half of the weight lies on either side, from ``(value, weight)`` pairs.

    With equal weights it is the same value ``execution_learning.median`` picks
    (the upper middle one), so old behaviour holds when every record is from the same day.
    """
    items = sorted(((v, w) for v, w in pairs if w > 0), key=lambda item: item[0])
    if not items:
        return None
    half = sum(w for _, w in items) / 2
    seen = 0.0
    for value, w in items:
        seen += w
        if seen > half:
            return value
    return items[-1][0]


def policy():
    """What the AI and the screen are told about how records are weighed."""
    return {"rule": RULE_VERSION, "halfLifeDays": HALF_LIFE_DAYS, "horizonDays": HORIZON_DAYS,
            "unit": "calendar_day", "calendarTimezone": "Asia/Seoul",
            "weighted": "shares and medians", "notWeighted": "minimum record and day counts"}
