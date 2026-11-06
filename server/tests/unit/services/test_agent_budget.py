"""The run budget: one lock, every limit, one announcement per limit."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from app.services.agent.budgets import BudgetLimit, RunBudget, context_window_for
from app.services.retrieval.config import (
    DEFAULT_CONTEXT_WINDOW,
    MAX_CONTEXT_WINDOW,
    MIN_CONTEXT_WINDOW,
    AgentConfig,
)
from tests.fixtures.agent_run import FakeClock
from tests.fixtures.retrieval import RecordingEmit

pytestmark = pytest.mark.unit


def budget(clock: FakeClock | None = None, emit: RecordingEmit | None = None, **limits):
    return RunBudget(
        AgentConfig(**limits), emit=emit or RecordingEmit(), clock=clock or FakeClock()
    )


class TestDefaults:
    def test_the_context_window_defaults_to_250000(self):
        assert AgentConfig().context_window == DEFAULT_CONTEXT_WINDOW == 250_000

    def test_the_run_total_is_a_runaway_guard_well_above_one_window(self):
        assert AgentConfig().max_input_tokens == 1_500_000

    def test_a_user_without_a_window_gets_the_default(self):
        assert context_window_for(None) == 250_000

    def test_a_user_window_wins(self):
        assert context_window_for(400_000) == 400_000

    def test_the_window_range_is_32k_to_1m(self):
        for window in (MIN_CONTEXT_WINDOW, MAX_CONTEXT_WINDOW):
            assert AgentConfig(context_window=window).context_window == window
        for window in (MIN_CONTEXT_WINDOW - 1, MAX_CONTEXT_WINDOW + 1):
            with pytest.raises(ValidationError):
                AgentConfig(context_window=window)


class TestToolCalls:
    async def test_calls_are_granted_up_to_the_limit(self):
        shared = budget(max_tool_calls=5)

        assert await shared.reserve_tool_calls(3) == 3
        assert await shared.reserve_tool_calls(4) == 2
        assert await shared.reserve_tool_calls(1) == 0

    async def test_reaching_the_limit_counts_as_exceeding_it(self):
        shared = budget(max_tool_calls=2)

        assert await shared.exceeded() is None
        await shared.reserve_tool_calls(2)

        assert await shared.exceeded() == "max_tool_calls"

    async def test_concurrent_claims_never_grant_more_than_the_limit(self):
        shared = budget(max_tool_calls=60)

        granted = await asyncio.gather(*(shared.reserve_tool_calls(1) for _ in range(200)))

        assert sum(granted) == 60
        assert (await shared.snapshot()).tool_calls == 60

    async def test_a_claim_for_nothing_grants_nothing(self):
        assert await budget().reserve_tool_calls(0) == 0


class TestTokens:
    async def test_input_tokens_add_up_and_trip_the_limit(self):
        shared = budget(max_input_tokens=10_000)

        await shared.add_usage(6_000, 300)
        assert await shared.exceeded() is None
        await shared.add_usage(4_000, 200)

        assert await shared.exceeded() == "max_input_tokens"
        snapshot = await shared.snapshot()
        assert (snapshot.input_tokens, snapshot.output_tokens) == (10_000, 500)

    async def test_concurrent_charges_are_all_counted(self):
        shared = budget()

        await asyncio.gather(*(shared.add_usage(10, 1) for _ in range(300)))

        snapshot = await shared.snapshot()
        assert (snapshot.input_tokens, snapshot.output_tokens) == (3000, 300)

    async def test_a_negative_report_cannot_lower_the_count(self):
        shared = budget()
        await shared.add_usage(500)

        await shared.add_usage(-400, -5)

        assert (await shared.snapshot()).input_tokens == 500


class TestWallClock:
    async def test_the_limit_trips_when_the_time_is_up(self):
        clock = FakeClock()
        shared = budget(clock, max_seconds=30)

        clock.advance(29.9)
        assert await shared.exceeded() is None
        clock.advance(0.2)

        assert await shared.exceeded() == "max_seconds"
        assert shared.elapsed() == pytest.approx(30.1)


class TestAnnouncements:
    async def test_each_limit_is_announced_once_with_what_was_used(self):
        events = RecordingEmit()
        shared = budget(emit=events, max_input_tokens=1_000)
        await shared.add_usage(1_500)

        for _ in range(3):
            await shared.exceeded()

        assert events.items == [
            (
                "degraded",
                {"stage": "budget", "limit": "max_input_tokens", "used": 1500, "allowed": 1000},
            )
        ]

    async def test_the_limit_reported_is_the_first_of_those_reached(self):
        events = RecordingEmit()
        shared = budget(emit=events, max_input_tokens=1_000, max_tool_calls=1)
        await shared.reserve_tool_calls(1)

        assert await shared.exceeded() == "max_tool_calls"
        await shared.add_usage(2_000)

        assert await shared.exceeded() == "max_input_tokens"
        assert [p["limit"] for p in events.degraded] == ["max_tool_calls", "max_input_tokens"]

    async def test_a_limit_counted_by_the_caller_is_announced_once(self):
        events = RecordingEmit()
        shared = budget(emit=events)

        await shared.note_reached(BudgetLimit.ITERATIONS, 12, 12)
        await shared.note_reached(BudgetLimit.ITERATIONS, 12, 12)

        assert events.degraded == [
            {"stage": "budget", "limit": "max_iterations", "used": 12, "allowed": 12}
        ]
        assert (await shared.snapshot()).reached == ("max_iterations",)

    async def test_a_listener_that_raises_does_not_break_the_budget(self):
        async def broken(event, payload):
            raise RuntimeError("closed")

        shared = RunBudget(AgentConfig(max_input_tokens=1_000), emit=broken)
        await shared.add_usage(5_000)

        assert await shared.exceeded() == "max_input_tokens"
