"""Criticality scoring.

`_score_file` is pure with respect to the database -- it reads attributes off a `File`
instance and returns a level -- so files are constructed in memory rather than inserted.
Fan-in boundaries and the score-to-level thresholds are the parts worth pinning: an
off-by-one there silently reclassifies every file in every repository.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.models import File
from app.services.criticality import _score_file

pytestmark = pytest.mark.unit

RECENT = datetime.now(tz=UTC) - timedelta(days=1)
STALE = datetime.now(tz=UTC) - timedelta(days=200)


def make_file(
    *,
    path: str = "src/app.py",
    fan_in: int | None = 0,
    has_tests: bool = True,
    git_last_modified: datetime | None = RECENT,
) -> File:
    """An unsaved File carrying only the fields the scorer reads."""
    return File(
        path=path,
        fan_in=fan_in,
        has_tests=has_tests,
        git_last_modified=git_last_modified,
    )


class TestBaseline:
    def test_a_quiet_tested_file_is_safe(self):
        level, reasons = _score_file(make_file())

        assert level == "safe"
        assert reasons == []

    def test_no_tests_adds_a_reason(self):
        level, reasons = _score_file(make_file(has_tests=False))

        assert level == "safe"
        assert "no test coverage" in reasons

    def test_a_none_fan_in_is_treated_as_zero(self):
        """The column is nullable; the scorer must not raise on a missing value."""
        level, reasons = _score_file(make_file(fan_in=None))

        assert level == "safe"
        assert reasons == []


class TestFanInBoundaries:
    @pytest.mark.parametrize("fan_in", [0, 4, 5, 9, 10, 50])
    def test_scores_without_raising_at_any_boundary(self, fan_in):
        level, _ = _score_file(make_file(fan_in=fan_in))

        assert level in {"safe", "caution", "critical"}

    def test_just_below_the_high_threshold_scores_the_lower_band(self):
        """
        fan_in 9 sits in the 5-9 band and scores 1 -- a reason without a level change.
        A lone point is not enough to leave `safe`.
        """
        level, reasons = _score_file(make_file(fan_in=9))

        assert level == "safe"
        assert "imported by 9 files" in reasons

    def test_crossing_the_high_threshold_changes_the_band(self):
        """9 and 10 differ by two points, so the pair is the threshold worth pinning."""
        _, below = _score_file(make_file(fan_in=9))
        _, at = _score_file(make_file(fan_in=10))

        assert below == ["imported by 9 files"]
        assert at == ["imported by 10 files"]

    def test_the_high_threshold_alone_is_caution_not_critical(self):
        """fan_in 10 scores 3, one short of the critical threshold of 4."""
        level, reasons = _score_file(make_file(fan_in=10))

        assert level == "caution"
        assert "imported by 10 files" in reasons

    def test_high_fan_in_plus_untested_reaches_critical(self):
        """3 (fan-in) + 1 (no tests) == 4."""
        level, reasons = _score_file(make_file(fan_in=10, has_tests=False))

        assert level == "critical"
        assert "imported by 10 files" in reasons
        assert "no test coverage" in reasons

    def test_below_the_high_threshold_scores_less(self):
        """5 is the lower threshold; 4 should not register at all."""
        _, at_five = _score_file(make_file(fan_in=5))
        _, at_four = _score_file(make_file(fan_in=4))

        assert "imported by 5 files" in at_five
        assert at_four == []


class TestPathPatterns:
    @pytest.mark.parametrize(
        "path",
        [
            "app/core/config.py",
            "app/core/database.py",
            "app/middleware/auth.py",
            "alembic/versions/migrations/0001.py",
            "app/auth.py",
            "app/core/security.py",
            "app/core/celery.py",
            "app/main.py",
        ],
        ids=[
            "config",
            "database",
            "middleware-dir",
            "migrations",
            "auth",
            "security",
            "celery",
            "main",
        ],
    )
    def test_core_infrastructure_paths_are_flagged(self, path):
        level, reasons = _score_file(make_file(path=path))

        assert "core infrastructure file" in reasons
        assert level == "caution"  # 2 points on its own

    @pytest.mark.parametrize(
        "path",
        ["src/utils/strings.py", "README.md", "src/components/Button.tsx"],
    )
    def test_ordinary_paths_are_not_flagged(self, path):
        _, reasons = _score_file(make_file(path=path))

        assert reasons == []

    def test_patterns_match_anywhere_in_the_path(self):
        """The regexes are unanchored, so a nested match still counts."""
        _, reasons = _score_file(make_file(path="deeply/nested/vendor/database.py"))

        assert "core infrastructure file" in reasons


class TestStaleness:
    def test_recently_modified_scores_nothing(self):
        _, reasons = _score_file(make_file(git_last_modified=RECENT))

        assert reasons == []

    def test_untouched_for_over_six_months_scores_one(self):
        _, reasons = _score_file(make_file(git_last_modified=STALE))

        assert "untouched for 6+ months" in reasons

    def test_boundary_is_181_days_not_180(self):
        """The check is `> 180`, so exactly 180 days must not count."""
        exactly_180 = datetime.now(tz=UTC) - timedelta(days=180)
        _, at_boundary = _score_file(make_file(git_last_modified=exactly_180))
        _, past_boundary = _score_file(
            make_file(git_last_modified=datetime.now(tz=UTC) - timedelta(days=181))
        )

        assert at_boundary == []
        assert "untouched for 6+ months" in past_boundary

    def test_unknown_modification_time_scores_nothing(self):
        _, reasons = _score_file(make_file(git_last_modified=None))

        assert reasons == []

    def test_naive_timestamps_are_normalized(self):
        """
        Postgres returns aware datetimes, but a naive one (from a fixture or a
        non-timezone column) would raise on subtraction unless normalized first.
        """
        naive_stale = datetime.now() - timedelta(days=200)
        assert naive_stale.tzinfo is None

        _, reasons = _score_file(make_file(git_last_modified=naive_stale))

        assert "untouched for 6+ months" in reasons


class TestLevelThresholds:
    """Score 4+ is critical, 2-3 is caution, 1 or less is safe."""

    @pytest.mark.parametrize(
        ("fan_in", "path", "has_tests", "expected"),
        [
            # 0 points
            (0, "src/app.py", True, "safe"),
            # 1 point
            (5, "src/app.py", True, "safe"),
            (0, "src/app.py", False, "safe"),
            # 2 points
            (5, "src/app.py", False, "caution"),
            (0, "app/core/database.py", True, "caution"),
            # 3 points
            (10, "src/app.py", True, "caution"),
            # 4 points
            (10, "src/app.py", False, "critical"),
            (5, "app/core/database.py", False, "critical"),
            # 5 points
            (10, "app/core/database.py", True, "critical"),
        ],
    )
    def test_score_maps_to_the_documented_level(self, fan_in, path, has_tests, expected):
        level, _ = _score_file(make_file(fan_in=fan_in, path=path, has_tests=has_tests))

        assert level == expected
