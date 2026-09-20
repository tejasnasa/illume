"""Per-stage instrumentation.

`_stage_timer` is the only thing that makes "the ingest got faster" or "this stage's
peak is growing with input size" checkable rather than assertable, so the shape of its
log line is a contract, not a detail.

The load-bearing case is `measure_memory=False`. Both counters it reads --
`tracemalloc` and `/proc/self/status`'s `VmHWM` -- are *process-global*, so a memory
delta measured across a stage that ran concurrently with another thread covers both
threads' allocations and attributes them to whichever read first. Such a stage must
log wall-clock only, and must say so: the absent `tracemalloc_peak` field would
otherwise read as a platform limitation (VmHWM is Linux-only) or a dropped
measurement rather than a deliberate omission.
"""

import logging

import pytest

from app.services._stage_timer import StageTimer, stage

pytestmark = pytest.mark.unit

LOGGER = "app.services._stage_timer"


def messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Every rendered log line this module emitted."""
    return [r.getMessage() for r in caplog.records if r.name == LOGGER]


class TestMeasuredStage:
    """The default shape carries wall-clock and both memory numbers."""

    def test_logs_wall_clock_and_tracemalloc_peak(self, caplog):
        with caplog.at_level(logging.INFO, logger=LOGGER):
            with stage("parse"):
                pass

        lines = messages(caplog)
        assert len(lines) == 1
        assert "stage=parse" in lines[0]
        assert "wall=" in lines[0]
        assert "tracemalloc_peak=" in lines[0]
        # `mem=not_measured` is the concurrent-stage marker; a measured stage
        # must never emit it, or the two shapes become indistinguishable and
        # the flag stops carrying information.
        assert "mem=not_measured" not in lines[0]

    def test_vmhwm_is_reported_only_where_the_kernel_exposes_it(self, caplog):
        """`VmHWM` is Linux-only; its absence elsewhere is not a failure."""
        from app.services._stage_timer import _read_vmhwm_kb

        with caplog.at_level(logging.INFO, logger=LOGGER):
            with stage("parse"):
                pass

        line = messages(caplog)[0]
        # Tie the assertion to the platform probe rather than the platform, so
        # the test states the same thing on a Linux CI runner and on Windows.
        if _read_vmhwm_kb() is None:
            assert "vmhwm_delta_kb=" not in line
        else:
            assert "vmhwm_delta_kb=" in line


class TestConcurrentStage:
    """`measure_memory=False` reports wall-clock and declares the omission."""

    def test_omits_memory_and_says_so(self, caplog):
        with caplog.at_level(logging.INFO, logger=LOGGER):
            with stage("glossary", measure_memory=False):
                pass

        lines = messages(caplog)
        assert len(lines) == 1
        line = lines[0]
        assert "stage=glossary" in line
        # Wall-clock is per-thread correct even under concurrency, which is
        # exactly why it survives here and the memory fields do not.
        assert "wall=" in line
        assert "mem=not_measured" in line
        assert "tracemalloc_peak=" not in line
        assert "vmhwm_delta_kb=" not in line

    def test_still_logs_one_line_per_stage(self, caplog):
        """The omission must not turn into a silent stage."""
        with caplog.at_level(logging.INFO, logger=LOGGER):
            with stage("embed_and_brief_join", measure_memory=False):
                pass

        assert len(messages(caplog)) == 1


class TestFailurePath:
    """A stage that raises is still reported, which is when it matters most."""

    def test_a_raising_body_still_logs_the_stage(self, caplog):
        with caplog.at_level(logging.INFO, logger=LOGGER):
            with pytest.raises(RuntimeError, match="boom"):
                with stage("git_history"):
                    raise RuntimeError("boom")

        # The `finally` in the context manager is what guarantees this; an
        # except-only implementation would drop the timing exactly when a
        # debugging session needs it.
        assert len(messages(caplog)) == 1
        assert "stage=git_history" in messages(caplog)[0]

    def test_a_raising_body_still_logs_when_memory_is_off(self, caplog):
        with caplog.at_level(logging.INFO, logger=LOGGER):
            with pytest.raises(RuntimeError):
                with stage("brief", measure_memory=False):
                    raise RuntimeError("boom")

        assert "mem=not_measured" in messages(caplog)[0]


class TestLifecycle:
    def test_stop_before_start_warns_instead_of_raising(self, caplog):
        """Signalling misuse must not take the ingest down with it."""
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            StageTimer("never_started").stop_and_log()

        assert any("before start()" in r.getMessage() for r in caplog.records)

    def test_a_timer_can_be_reused(self, caplog):
        timer = StageTimer("reused")
        with caplog.at_level(logging.INFO, logger=LOGGER):
            timer.start()
            timer.stop_and_log()
            timer.start()
            timer.stop_and_log()

        assert len(messages(caplog)) == 2
