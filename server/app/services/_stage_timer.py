"""Per-stage wall-clock and peak-RSS instrumentation.

Records the start time and the current ``tracemalloc`` peak for each named stage,
and emits a single log line on exit with both numbers. ``tracemalloc`` is the
cross-platform attribution source -- it answers "where did the memory go" -- but
it does not see memory the runtime allocated before ``tracemalloc.start()`` ran
and it does not report process RSS.

For the actual peak resident-set size the Linux ``/proc/self/status`` ``VmHWM``
line is the authoritative number (it is what ``time -v`` reports under "Maximum
resident set size"). It is gated by ``os.path.exists`` because every other
platform would otherwise raise.

The instrumentation is stdlib-only and does not introduce ``psutil``; that
dependency is deliberately not added because the rest of the suite never needed
it and the two numbers above are enough to answer "is this stage's peak growing
with input size?".

Usage::

    timer = StageTimer("scanner")
    timer.start()
    ... # do the work
    timer.stop_and_log()

Each timer can be reused, and the same logger is used as the rest of the
ingestion pipeline so the per-stage numbers appear alongside the other logs.
"""

import logging
import os
import time
import tracemalloc
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)

# ``/proc/self/status`` only exists on Linux. Windows and macOS use other
# interfaces (``psutil`` or platform-specific syscalls). Skip silently on the
# platforms that do not expose it; the tracemalloc number is still useful.
_VMHWM_PATH = "/proc/self/status"


def _read_vmhwm_kb() -> int | None:
    """Return the VmHWM value from ``/proc/self/status`` in KiB, or None if absent."""
    if not os.path.exists(_VMHWM_PATH):
        return None
    try:
        with open(_VMHWM_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1])
    except OSError:
        return None
    return None


def _ensure_tracemalloc_started() -> None:
    """Start ``tracemalloc`` if it has not been started yet.

    A second ``start()`` is a no-op, so this is safe to call from every stage
    timer. Calling it once per stage instead of once per process keeps the
    start-call site next to the work it is timing, which is what makes it
    obvious when one stage's peak dwarfs the others.
    """
    if not tracemalloc.is_tracing():
        tracemalloc.start()


class StageTimer:
    """Wall-clock and peak-RSS tracking for a single named stage.

    Args:
        name: Stage label, used as the key in the log message.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._start_time: float | None = None
        self._start_tracemalloc: tuple[int, int] | None = None
        self._start_vmhwm_kb: int | None = None

    def start(self) -> None:
        """Mark the stage as begun."""
        _ensure_tracemalloc_started()
        self._start_time = time.monotonic()
        self._start_tracemalloc = tracemalloc.get_traced_memory()
        self._start_vmhwm_kb = _read_vmhwm_kb()

    def stop_and_log(self) -> None:
        """Log a single line summarizing the stage's wall time and peak RSS."""
        if self._start_time is None:
            logger.warning("StageTimer(%s).stop_and_log() called before start()", self.name)
            return

        elapsed = time.monotonic() - self._start_time
        current_traced, peak_traced = tracemalloc.get_traced_memory()
        delta_peak_traced = peak_traced - (
            self._start_tracemalloc[1] if self._start_tracemalloc else 0
        )
        current_vmhwm_kb = _read_vmhwm_kb()
        delta_vmhwm_kb = (
            current_vmhwm_kb - self._start_vmhwm_kb
            if current_vmhwm_kb is not None and self._start_vmhwm_kb is not None
            else None
        )

        parts = [
            f"stage={self.name}",
            f"wall={elapsed:.2f}s",
            f"tracemalloc_peak={delta_peak_traced}",
        ]
        if delta_vmhwm_kb is not None:
            parts.append(f"vmhwm_delta_kb={delta_vmhwm_kb}")
        logger.info("stage_timer " + " ".join(parts))


@contextmanager
def stage(name: str) -> Iterator[StageTimer]:
    """Context manager that times a stage and logs on exit.

    Example::

        with stage("parse") as t:
            t.start()
            ...

    ``start()`` is called on enter; the surrounding ``with`` block is the
    measured region. Calling ``start()`` manually is not needed but is supported
    so callers can opt out of the context-manager shape.
    """
    timer = StageTimer(name)
    timer.start()
    try:
        yield timer
    finally:
        timer.stop_and_log()
