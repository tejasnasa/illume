"""Turning a date phrase in a question into a real range, without a model.

"What changed in auth over the last two weeks?" should look at two weeks of
commits, not at whichever commits happen to sound similar. :func:`resolve_date_range`
finds one date phrase in the question and resolves it against ``now``; the history
channel and the ``search_history`` tool then filter on the result.

The recognised phrases, all case-insensitive, with times in UTC:

* ``today``, ``yesterday``
* ``this week`` (from Monday), ``this month``, ``this year``
* ``last N days|weeks|months|years`` and ``past N ...``, where ``N`` is digits or
  a number word up to twenty, or ``thirty``, ``sixty``, ``ninety``: a rolling window
  ending now
* ``past week|month|year``: a rolling window of one unit ending now
* ``last week|month|year``: the previous calendar period
* ``since <Month> [year]``, ``since YYYY-MM-DD``: from then until now
* ``in <Month> [year]``: that calendar month
* ``before YYYY-MM-DD``, ``after YYYY-MM-DD``: everything up to the day before,
  or from the day after

A month with no year means its most recent occurrence not in the future. A
question with no phrase, or with a phrase that cannot be resolved (a zero count,
an impossible date), resolves to ``None``. Only the first phrase found counts,
in the order of the list above.

Both ends of a :class:`DateRange` are inclusive, and either may be open.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

_MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sept", "sep"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ),
        start=1,
    )
    for name in names
}

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "sixty": 60,
    "ninety": 90,
}

MAX_COUNT = 1000
"""The largest ``N`` accepted in ``last N <units>``."""

_MONTH_NAMES = "|".join(sorted(_MONTHS, key=len, reverse=True))
_NUMBER = "|".join(["\\d{1,4}", *_NUMBER_WORDS])
_ISO = r"(?P<iso>\d{4}-\d{2}-\d{2})"

_SINCE_ISO = re.compile(rf"\bsince\s+{_ISO}\b", re.IGNORECASE)
_SINCE_MONTH = re.compile(
    rf"\bsince\s+(?P<month>{_MONTH_NAMES})\b\.?(?:\s+(?P<year>\d{{4}})\b)?", re.IGNORECASE
)
_BEFORE_AFTER = re.compile(rf"\b(?P<which>before|after)\s+{_ISO}\b", re.IGNORECASE)
_IN_MONTH = re.compile(
    rf"\bin\s+(?P<month>{_MONTH_NAMES})\b\.?(?:\s+(?P<year>\d{{4}})\b)?", re.IGNORECASE
)
_LAST_N = re.compile(
    rf"\b(?P<lead>last|past)\s+(?P<count>{_NUMBER})\s+(?P<unit>day|week|month|year)s?\b",
    re.IGNORECASE,
)
_LAST_UNIT = re.compile(r"\b(?P<lead>last|past)\s+(?P<unit>week|month|year)\b", re.IGNORECASE)
_THIS_UNIT = re.compile(r"\bthis\s+(?P<unit>week|month|year)\b", re.IGNORECASE)
_YESTERDAY = re.compile(r"\byesterday\b", re.IGNORECASE)
_TODAY = re.compile(r"\btoday\b", re.IGNORECASE)

_MICROSECOND = timedelta(microseconds=1)


@dataclass(frozen=True)
class DateRange:
    """A span of time resolved from a phrase.

    Attributes:
        since: The earliest moment included, or ``None`` when open.
        until: The latest moment included, or ``None`` when open.
        phrase: The words of the question that were matched.
    """

    since: datetime | None
    until: datetime | None
    phrase: str = ""

    def contains(self, moment: datetime) -> bool:
        """Whether ``moment`` falls inside the range. A naive moment is read as UTC."""
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        if self.since is not None and moment < self.since:
            return False
        return self.until is None or moment <= self.until

    def describe(self, now: datetime | None = None) -> str:
        """The range in words, such as ``from 2026-10-28 to 2026-11-11``.

        An end later than ``now`` is shown as ``now``'s date, since nothing in
        the future can have been committed.
        """
        until = self.until
        if until is not None and now is not None and until > now:
            until = now
        if self.since is not None and until is not None:
            return f"from {self.since.date().isoformat()} to {until.date().isoformat()}"
        if self.since is not None:
            return f"since {self.since.date().isoformat()}"
        if until is not None:
            return f"until {until.date().isoformat()}"
        return "all time"

    def to_dict(self, now: datetime | None = None) -> dict[str, str | None]:
        """A JSON-serialisable form for traces."""
        return {
            "since": self.since.isoformat() if self.since else None,
            "until": self.until.isoformat() if self.until else None,
            "phrase": self.phrase or None,
            "description": self.describe(now),
        }


def parse_day(value: str) -> datetime | None:
    """The UTC midnight starting ``YYYY-MM-DD``, or ``None`` when it is not a date."""
    try:
        day = date.fromisoformat(value)
    except ValueError:
        return None
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _start_of_day(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(year: int, month: int) -> datetime:
    return datetime(year, month, 1, tzinfo=UTC)


def _add_months(moment: datetime, months: int) -> datetime:
    """``moment`` shifted by whole months, the day clamped to the target month's length."""
    index = moment.year * 12 + (moment.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def _calendar_month(year: int, month: int, phrase: str) -> DateRange:
    start = _month_start(year, month)
    return DateRange(start, _add_months(start, 1) - _MICROSECOND, phrase)


def _month_year(now: datetime, month: int, year: int | None) -> int:
    """The year a month refers to: the given one, else the latest not in the future."""
    if year is not None:
        return year
    return now.year if month <= now.month else now.year - 1


def _count(token: str) -> int | None:
    value = int(token) if token.isdigit() else _NUMBER_WORDS.get(token.lower())
    return value if value is not None and 1 <= value <= MAX_COUNT else None


def _window(now: datetime, count: int, unit: str, phrase: str) -> DateRange | None:
    """The ``count`` units before ``now``."""
    try:
        if unit == "day":
            since = now - timedelta(days=count)
        elif unit == "week":
            since = now - timedelta(weeks=count)
        elif unit == "month":
            since = _add_months(now, -count)
        else:
            since = _add_months(now, -12 * count)
    except OverflowError, ValueError:
        return None
    return DateRange(since, now, phrase)


def _last_calendar(now: datetime, unit: str, phrase: str) -> DateRange:
    """The calendar week, month or year before the current one."""
    today = _start_of_day(now)
    if unit == "week":
        this_monday = today - timedelta(days=today.weekday())
        return DateRange(this_monday - timedelta(weeks=1), this_monday - _MICROSECOND, phrase)
    if unit == "month":
        return _previous_month(now, phrase)
    start = _month_start(now.year - 1, 1)
    return DateRange(start, _month_start(now.year, 1) - _MICROSECOND, phrase)


def _previous_month(now: datetime, phrase: str) -> DateRange:
    year, month = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    return _calendar_month(year, month, phrase)


def _this_period(now: datetime, unit: str, phrase: str) -> DateRange:
    """The current calendar week (from Monday), month or year, in full."""
    today = _start_of_day(now)
    if unit == "week":
        monday = today - timedelta(days=today.weekday())
        return DateRange(monday, monday + timedelta(weeks=1) - _MICROSECOND, phrase)
    if unit == "month":
        return _calendar_month(now.year, now.month, phrase)
    start = _month_start(now.year, 1)
    return DateRange(start, _month_start(now.year + 1, 1) - _MICROSECOND, phrase)


def resolve_date_range(question: str, now: datetime) -> DateRange | None:
    """The date range a question asks about, or ``None``.

    Args:
        question: The question as asked.
        now: The current moment. A naive value is read as UTC.

    Returns:
        The range for the first recognised phrase, or ``None`` when there is
        none or it cannot be resolved.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    now = now.astimezone(UTC)

    if match := _SINCE_ISO.search(question):
        start = parse_day(match["iso"])
        return DateRange(start, now, match.group(0)) if start else None

    if match := _SINCE_MONTH.search(question):
        month = _MONTHS[match["month"].lower()]
        year = int(match["year"]) if match["year"] else _month_year(now, month, None)
        return DateRange(_month_start(year, month), now, match.group(0))

    if match := _BEFORE_AFTER.search(question):
        day = parse_day(match["iso"])
        if day is None:
            return None
        if match["which"].lower() == "before":
            return DateRange(None, day - _MICROSECOND, match.group(0))
        return DateRange(day + timedelta(days=1), None, match.group(0))

    for match in _IN_MONTH.finditer(question):
        name = match["month"]
        # "may" is a common verb: take it as a month only when written as one.
        if name.lower() == "may" and not (name[0].isupper() or match["year"]):
            continue
        month = _MONTHS[name.lower()]
        year = _month_year(now, month, int(match["year"]) if match["year"] else None)
        return _calendar_month(year, month, match.group(0))

    if match := _LAST_N.search(question):
        count = _count(match["count"])
        if count is None:
            return None
        return _window(now, count, match["unit"].lower(), match.group(0))

    if match := _LAST_UNIT.search(question):
        unit = match["unit"].lower()
        if match["lead"].lower() == "past":
            return _window(now, 1, unit, match.group(0))
        return _last_calendar(now, unit, match.group(0))

    if match := _THIS_UNIT.search(question):
        return _this_period(now, match["unit"].lower(), match.group(0))

    if match := _YESTERDAY.search(question):
        today = _start_of_day(now)
        return DateRange(today - timedelta(days=1), today - _MICROSECOND, match.group(0))

    if match := _TODAY.search(question):
        today = _start_of_day(now)
        return DateRange(today, today + timedelta(days=1) - _MICROSECOND, match.group(0))

    return None
