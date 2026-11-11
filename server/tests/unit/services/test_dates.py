"""Resolving date phrases in a question into a range.

``now`` is Wednesday 2026-11-11 12:00 UTC unless a test says otherwise, held by
freezegun so the resolver is also checked against the real clock it will be
given in production.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from app.services.retrieval.dates import DateRange, parse_day, resolve_date_range

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
END_OF_DAY = timedelta(days=1) - timedelta(microseconds=1)


def at(year, month, day, hour=0, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def day_span(start: datetime, days: int = 1) -> tuple[datetime, datetime]:
    return start, start + timedelta(days=days) - timedelta(microseconds=1)


def resolve(question: str, now: datetime = NOW) -> tuple[datetime | None, datetime | None] | None:
    with freeze_time(now):
        found = resolve_date_range(question, datetime.now(UTC))
    return None if found is None else (found.since, found.until)


class TestRolling:
    @pytest.mark.parametrize(
        ("phrase", "since"),
        [
            ("last 2 days", at(2026, 11, 9, 12)),
            ("last two weeks", at(2026, 10, 28, 12)),
            ("past 3 months", at(2026, 8, 11, 12)),
            ("last 1 year", at(2025, 11, 11, 12)),
            ("past two years", at(2024, 11, 11, 12)),
            ("last ten days", at(2026, 11, 1, 12)),
            ("last twelve months", at(2025, 11, 11, 12)),
            ("last thirty days", at(2026, 10, 12, 12)),
            ("Past 14 Days", at(2026, 10, 28, 12)),
            ("past week", at(2026, 11, 4, 12)),
            ("past month", at(2026, 10, 11, 12)),
            ("past year", at(2025, 11, 11, 12)),
        ],
    )
    def test_a_window_ending_now(self, phrase, since):
        assert resolve(f"What changed in auth over the {phrase}?") == (since, NOW)

    def test_the_spec_example(self):
        found = resolve_date_range("What changed in auth over the last two weeks?", NOW)

        assert found is not None
        assert found.phrase == "last two weeks"
        assert found.describe(NOW) == "from 2026-10-28 to 2026-11-11"

    def test_a_month_back_from_the_end_of_a_month_is_clamped(self):
        now = at(2026, 3, 31, 12)

        assert resolve("the past month", now) == (at(2026, 2, 28, 12), now)

    def test_a_leap_day_a_year_back_is_clamped(self):
        now = at(2028, 2, 29, 9)

        assert resolve("past year", now) == (at(2027, 2, 28, 9), now)

    @pytest.mark.parametrize("question", ["last 0 days", "last 2000 days", "last zero weeks"])
    def test_an_unusable_count_resolves_to_nothing(self, question):
        assert resolve(question) is None


class TestCalendar:
    def test_today(self):
        assert resolve("what changed today") == day_span(at(2026, 11, 11))

    def test_yesterday(self):
        assert resolve("who touched this yesterday?") == day_span(at(2026, 11, 10))

    def test_this_week_runs_from_monday(self):
        assert resolve("changes this week") == day_span(at(2026, 11, 9), 7)

    def test_this_week_on_a_monday_starts_that_day(self):
        assert resolve("this week", at(2026, 1, 5, 8)) == day_span(at(2026, 1, 5), 7)

    def test_this_week_can_start_in_the_previous_year(self):
        assert resolve("this week", at(2026, 1, 1, 8)) == day_span(at(2025, 12, 29), 7)

    def test_this_month(self):
        assert resolve("this month") == day_span(at(2026, 11, 1), 30)

    def test_this_year(self):
        assert resolve("this year") == day_span(at(2026, 1, 1), 365)

    def test_last_week_is_the_previous_calendar_week(self):
        assert resolve("last week") == day_span(at(2026, 11, 2), 7)

    def test_last_month_is_the_previous_calendar_month(self):
        assert resolve("last month") == day_span(at(2026, 10, 1), 31)

    def test_last_month_in_january_is_december(self):
        assert resolve("last month", at(2026, 1, 15)) == day_span(at(2025, 12, 1), 31)

    def test_last_year_is_the_previous_calendar_year(self):
        assert resolve("last year") == day_span(at(2025, 1, 1), 365)

    def test_the_first_and_last_instants_of_a_day_are_inside_it(self):
        found = resolve_date_range("yesterday", NOW)

        assert found is not None
        assert found.contains(at(2026, 11, 10))
        assert found.contains(at(2026, 11, 10, 23, 59))
        assert not found.contains(at(2026, 11, 11))
        assert not found.contains(at(2026, 11, 9, 23, 59))


class TestSince:
    def test_since_a_month_this_year(self):
        assert resolve("since March") == (at(2026, 3, 1), NOW)

    def test_since_a_month_later_in_the_year_means_last_year(self):
        assert resolve("since December") == (at(2025, 12, 1), NOW)

    def test_since_the_current_month_starts_this_month(self):
        assert resolve("since November") == (at(2026, 11, 1), NOW)

    def test_since_a_month_and_year(self):
        assert resolve("changes since March 2024") == (at(2024, 3, 1), NOW)

    def test_an_abbreviated_month(self):
        assert resolve("since Sept 2025") == (at(2025, 9, 1), NOW)
        assert resolve("since oct") == (at(2026, 10, 1), NOW)

    def test_since_a_date(self):
        assert resolve("what changed since 2026-09-15?") == (at(2026, 9, 15), NOW)

    def test_an_impossible_date_resolves_to_nothing(self):
        assert resolve("since 2026-13-45") is None
        assert resolve("before 2026-02-30") is None


class TestInAMonth:
    def test_a_month_this_year(self):
        assert resolve("what changed in October?") == day_span(at(2026, 10, 1), 31)

    def test_the_current_month(self):
        assert resolve("changes in November") == day_span(at(2026, 11, 1), 30)

    def test_a_later_month_means_last_year(self):
        assert resolve("what changed in December?") == day_span(at(2025, 12, 1), 31)

    def test_a_month_and_year(self):
        assert resolve("in February 2024") == day_span(at(2024, 2, 1), 29)

    def test_may_is_a_month_only_when_written_like_one(self):
        assert resolve("in May") == day_span(at(2026, 5, 1), 31)
        assert resolve("in may 2025") == day_span(at(2025, 5, 1), 31)
        assert resolve("what changes in may happen?") is None


class TestBeforeAndAfter:
    def test_before_a_date_ends_the_day_before(self):
        since, until = resolve("before 2026-10-01")

        assert since is None
        assert until == at(2026, 10, 1) - timedelta(microseconds=1)

    def test_after_a_date_starts_the_day_after(self):
        assert resolve("after 2026-10-01") == (at(2026, 10, 2), None)

    def test_the_named_day_is_on_neither_side(self):
        before = resolve_date_range("before 2026-10-01", NOW)
        after = resolve_date_range("after 2026-10-01", NOW)

        assert before is not None and after is not None
        assert not before.contains(at(2026, 10, 1))
        assert not after.contains(at(2026, 10, 1, 23, 59))
        assert before.contains(at(2026, 9, 30, 23, 59))
        assert after.contains(at(2026, 10, 2))


class TestNoMatch:
    @pytest.mark.parametrize(
        "question",
        [
            "",
            "Where is verify_password defined?",
            "what changed recently",
            "how did the project look a while ago",
            "last",
            "since",
            "in the auth module",
        ],
    )
    def test_nothing_to_resolve(self, question):
        assert resolve(question) is None

    def test_the_first_matching_form_wins(self):
        # An explicit date is more precise than the relative phrase beside it.
        assert resolve("since 2026-09-15, not just today") == (at(2026, 9, 15), NOW)


class TestTheRangeItself:
    def test_a_naive_now_is_read_as_utc(self):
        found = resolve_date_range("last 2 days", datetime(2026, 11, 11, 12, 0))

        assert found is not None and found.since == at(2026, 11, 9, 12)

    def test_an_open_range_describes_itself(self):
        assert DateRange(at(2026, 1, 1), None).describe() == "since 2026-01-01"
        assert DateRange(None, at(2026, 1, 1)).describe() == "until 2026-01-01"
        assert DateRange(None, None).describe() == "all time"

    def test_an_end_in_the_future_is_shown_as_today(self):
        found = resolve_date_range("this month", NOW)

        assert found is not None
        assert found.describe(NOW) == "from 2026-11-01 to 2026-11-11"

    def test_parse_day(self):
        assert parse_day("2026-02-28") == at(2026, 2, 28)
        assert parse_day("2026-02-30") is None
        assert parse_day("not a date") is None
