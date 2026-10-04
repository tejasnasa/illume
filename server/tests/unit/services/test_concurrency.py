"""The bounded streaming gather.

:func:`iter_gather_in_order` exists so a caller can persist each result as it
arrives instead of holding every response until the last one lands. That makes
it a *stream*, and a stream has one property the list-returning
:func:`gather_in_order` cannot have: it only does the work the caller actually
asks for.

Everything else -- submission order, the bound on in-flight work, and where a
worker exception surfaces -- is supposed to be identical to
:func:`gather_in_order`, and that is what these tests pin. They use plain
counters and threads rather than the OpenAI stub because nothing here touches
the network layer.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import pytest

from app.services._concurrency import iter_gather_in_order

pytestmark = pytest.mark.unit


def _tracking_calls(
    count: int, *, sleep_s: float = 0.02
) -> tuple[list[Callable[[], int]], dict[str, int]]:
    """Build ``count`` callables that record their peak concurrency.

    Returns the callables plus a shared ``state`` dict holding ``current`` and
    ``peak``. The sleep is what makes the bound observable: without it each
    call is over before the next starts and the peak is always 1.
    """
    lock = threading.Lock()
    state = {"current": 0, "peak": 0}

    def make(value: int) -> Callable[[], int]:
        def call() -> int:
            with lock:
                state["current"] += 1
                state["peak"] = max(state["peak"], state["current"])
            try:
                time.sleep(sleep_s)
                return value
            finally:
                with lock:
                    state["current"] -= 1

        return call

    return [make(i) for i in range(count)], state


class TestOrdering:
    """Results arrive in submission order, like ``gather_in_order``."""

    def test_yields_in_submission_order(self):
        callables, _state = _tracking_calls(6, sleep_s=0.0)

        assert list(iter_gather_in_order(callables, max_workers=2)) == [0, 1, 2, 3, 4, 5]

    def test_empty_input_yields_nothing(self):
        assert list(iter_gather_in_order([], max_workers=4)) == []

    def test_a_single_callable_runs_inline(self):
        """One call skips the pool, matching ``gather_in_order``'s inline path."""
        seen: list[str] = []

        def only() -> str:
            seen.append(threading.current_thread().name)
            return "value"

        assert list(iter_gather_in_order([only], max_workers=4)) == ["value"]
        assert seen == [threading.current_thread().name]


class TestBoundedWindow:
    """At most ``max_workers`` callables are ever in flight."""

    def test_never_exceeds_the_window_and_actually_uses_it(self):
        callables, state = _tracking_calls(6)

        results = list(iter_gather_in_order(callables, max_workers=2))

        assert results == [0, 1, 2, 3, 4, 5]
        assert state["peak"] <= 2, "the in-flight window was exceeded"
        assert state["peak"] > 1, "the window was never used; the pool is serial"


class TestLaziness:
    """The tail is never submitted when the caller stops early."""

    def test_only_the_primed_window_is_submitted_when_the_caller_stops(self):
        started: list[int] = []

        def make(value: int) -> Callable[[], int]:
            def call() -> int:
                started.append(value)
                return value

            return call

        stream = iter_gather_in_order([make(i) for i in range(10)], max_workers=2)

        # Take one result, then abandon the stream. Only the primed window
        # (indices 0 and 1) should have been submitted -- a list-returning
        # gather would have run all ten.
        assert next(stream) == 0
        stream.close()

        assert max(started) <= 1, f"submitted beyond the window: {sorted(started)}"


class TestFailurePropagation:
    """A worker exception surfaces on the caller thread, as a list gather's would."""

    def test_worker_exception_is_reraised_to_the_caller(self):
        def boom() -> int:
            raise ValueError("worker exploded")

        stream = iter_gather_in_order([boom, boom, boom], max_workers=2)

        with pytest.raises(ValueError, match="worker exploded"):
            list(stream)
