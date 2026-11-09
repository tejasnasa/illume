"""What a request may change on a preset.

The allowlist is closed and the context window stays in the range an account may
set. On the free tier a request may only make a run cheaper; with the caller's
own key the drawer's switches are open, but budgets stop at the most generous
preset's.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.agent.overrides import (
    SERVER_AGENT_CEILINGS,
    OverrideError,
    Overrides,
    apply_overrides,
)
from app.services.retrieval.config import (
    CLASSIC,
    DEEP_AGENT,
    DEEP_AGENT_WORKERS,
    HYBRID,
    MAX_CONTEXT_WINDOW,
    MIN_CONTEXT_WINDOW,
)

pytestmark = pytest.mark.unit


def overrides(**fields) -> Overrides:
    return Overrides.model_validate(fields)


class TestAllowlist:
    @pytest.mark.parametrize(
        "fields",
        [
            {"channels": []},
            {"channels": ["web"]},
            {"rerank": {"top_n": 5}},
            {"rerank": {"kind": "magic"}},
            {"execution": "agent"},
            {"decider": "llm"},
            {"agent": {"tools": ["finish"]}},
            {"agent": {"compact_at": 0.5}},
            {"agent": {"keep_recent_turns": 1}},
            {"planner": {"plan_threshold": 0.0}},
            {"query": {"n_variants": 5}},
            {"diversify": {"symbol": 50}},
            {"unknown": 1},
        ],
    )
    def test_fields_outside_the_allowlist_are_rejected(self, fields):
        with pytest.raises(ValidationError):
            overrides(**fields)

    def test_the_allowed_fields_are_accepted(self):
        parsed = overrides(
            agent={"max_iterations": 5, "context_window": MIN_CONTEXT_WINDOW, "effort": "high"},
            planner={"max_workers": 3},
            query={"history_messages": 2},
            diversify={"total": 8},
        )

        assert parsed.agent.max_iterations == 5

    @pytest.mark.parametrize("window", [MIN_CONTEXT_WINDOW - 1, MAX_CONTEXT_WINDOW + 1])
    def test_a_context_window_outside_the_range_is_rejected(self, window):
        with pytest.raises(ValidationError):
            overrides(agent={"context_window": window})

    def test_the_bounds_of_the_context_window_are_accepted(self):
        for window in (MIN_CONTEXT_WINDOW, MAX_CONTEXT_WINDOW):
            assert overrides(agent={"context_window": window}).agent.context_window == window


class TestCeilings:
    @pytest.mark.parametrize(
        "field",
        [
            "max_iterations",
            "max_tool_calls",
            "max_seconds",
            "hard_cancel_seconds",
            "max_input_tokens",
        ],
    )
    def test_a_budget_above_the_presets_is_rejected(self, field):
        assert DEEP_AGENT.agent is not None
        too_much = getattr(DEEP_AGENT.agent, field) + 1

        with pytest.raises(OverrideError, match=field):
            apply_overrides(DEEP_AGENT, overrides(agent={field: too_much}))

    @pytest.mark.parametrize("field", ["max_workers", "worker_iterations"])
    def test_a_worker_budget_above_the_presets_is_rejected(self, field):
        assert DEEP_AGENT_WORKERS.planner is not None
        too_much = getattr(DEEP_AGENT_WORKERS.planner, field) + 1

        with pytest.raises(OverrideError, match=field):
            apply_overrides(DEEP_AGENT_WORKERS, overrides(planner={field: too_much}))

    def test_a_budget_at_or_below_the_presets_is_applied(self):
        assert DEEP_AGENT.agent is not None

        tightened = apply_overrides(
            DEEP_AGENT,
            overrides(
                agent={"max_iterations": 3, "max_tool_calls": DEEP_AGENT.agent.max_tool_calls}
            ),
        )

        assert tightened.agent is not None
        assert tightened.agent.max_iterations == 3
        assert tightened.agent.max_tool_calls == DEEP_AGENT.agent.max_tool_calls
        assert tightened.config_hash() != DEEP_AGENT.config_hash()

    def test_seed_cannot_be_switched_on_when_the_preset_has_it_off(self):
        no_seed = DEEP_AGENT.model_copy(
            update={"agent": DEEP_AGENT.agent.model_copy(update={"seed": False})}
        )

        with pytest.raises(OverrideError, match="agent.seed"):
            apply_overrides(no_seed, overrides(agent={"seed": True}))

    def test_the_context_window_may_be_set_in_range(self):
        applied = apply_overrides(DEEP_AGENT, overrides(agent={"context_window": 64_000}))

        assert applied.agent is not None and applied.agent.context_window == 64_000

    def test_an_inconsistent_result_is_rejected(self):
        with pytest.raises(OverrideError):
            apply_overrides(
                DEEP_AGENT, overrides(agent={"max_seconds": 140, "hard_cancel_seconds": 30})
            )


class TestFit:
    def test_agent_settings_on_a_single_shot_preset_are_rejected(self):
        with pytest.raises(OverrideError, match="no agent settings"):
            apply_overrides(HYBRID, overrides(agent={"max_iterations": 2}))

    def test_planner_settings_on_an_agent_preset_are_rejected(self):
        with pytest.raises(OverrideError, match="no planner settings"):
            apply_overrides(DEEP_AGENT, overrides(planner={"max_workers": 2}))

    def test_no_overrides_return_the_preset_itself(self):
        assert apply_overrides(DEEP_AGENT, None) is DEEP_AGENT

    def test_query_and_diversify_overrides_apply(self):
        applied = apply_overrides(
            HYBRID, overrides(query={"history_messages": 1}, diversify={"total": 7})
        )

        assert applied.query.history_messages == 1
        assert applied.diversify.total == 7
        assert applied.name == HYBRID.name

    def test_applying_never_mutates_the_preset(self):
        before = DEEP_AGENT.config_hash()

        apply_overrides(DEEP_AGENT, overrides(agent={"max_iterations": 2}))

        assert DEEP_AGENT.config_hash() == before


class TestFreeTier:
    @pytest.mark.parametrize(
        "fields",
        [
            {"rerank": {"kind": "jev"}},
            {"query": {"transform": "hyde"}},
            {"query": {"transform": "multi_query"}},
            {"channels": ["dense", "grep"]},
        ],
        ids=["reranker", "hyde", "multi-query", "added-channel"],
    )
    def test_nothing_that_costs_more_can_be_switched_on(self, fields):
        with pytest.raises(OverrideError, match="free tier"):
            apply_overrides(HYBRID, overrides(**fields))

    def test_channels_can_be_narrowed_and_extras_turned_off(self):
        applied = apply_overrides(
            HYBRID,
            overrides(
                channels=["dense", "lexical"],
                rerank={"kind": "none"},
                query={"transform": "identity"},
            ),
        )

        assert [channel.kind for channel in applied.channels] == ["dense", "lexical"]
        assert applied.rerank.kind == "none"


class TestOwnKey:
    def test_the_seed_can_be_switched_on(self):
        no_seed = DEEP_AGENT.model_copy(
            update={"agent": DEEP_AGENT.agent.model_copy(update={"seed": False})}
        )

        seeded = apply_overrides(no_seed, overrides(agent={"seed": True}), own_key=True)

        assert seeded.agent is not None and seeded.agent.seed is True

    def test_the_reranker_and_query_rewriting_can_be_chosen(self):
        applied = apply_overrides(
            HYBRID,
            overrides(rerank={"kind": "jev"}, query={"transform": "hyde"}),
            own_key=True,
        )

        assert applied.rerank.kind == "jev"
        assert applied.query.transform == "hyde"

    def test_channels_can_be_added_and_a_single_channel_preset_is_fused(self):
        applied = apply_overrides(CLASSIC, overrides(channels=["dense", "grep"]), own_key=True)

        assert sorted(channel.kind for channel in applied.channels) == ["dense", "grep"]
        assert applied.fusion == "rrf"
        # The preset's own channel keeps its settings.
        [dense] = [channel for channel in applied.channels if channel.kind == "dense"]
        assert dense == CLASSIC.channels[0]

    def test_a_budget_stops_at_the_server_maximum(self):
        ceiling = SERVER_AGENT_CEILINGS["max_iterations"]

        at = apply_overrides(DEEP_AGENT, overrides(agent={"max_iterations": ceiling}), own_key=True)
        assert at.agent is not None and at.agent.max_iterations == ceiling
        with pytest.raises(OverrideError, match="server's maximum"):
            apply_overrides(
                DEEP_AGENT, overrides(agent={"max_iterations": ceiling + 1}), own_key=True
            )

    def test_the_server_maximum_is_the_most_generous_presets(self):
        assert SERVER_AGENT_CEILINGS["max_iterations"] >= DEEP_AGENT.agent.max_iterations
        assert SERVER_AGENT_CEILINGS["max_tool_calls"] >= DEEP_AGENT.agent.max_tool_calls

    def test_a_gate_on_a_single_shot_preset_is_refused_with_the_reason(self):
        with pytest.raises(OverrideError, match="needs agent or planner") as raised:
            apply_overrides(HYBRID, overrides(checks={"gate": True}), own_key=True)

        assert not str(raised.value).startswith(":")
