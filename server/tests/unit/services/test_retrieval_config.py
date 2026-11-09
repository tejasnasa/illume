"""``PipelineConfig``: what it accepts, what it refuses, and what its hash means.

The hash is how an evaluation result is traced back to the configuration that
produced it, so its stability is pinned as carefully as the validation rules.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.services.retrieval.config import (
    CLASSIC,
    PRESETS,
    AgentConfig,
    CochangeChannel,
    DenseChannel,
    GraphChannel,
    LexicalChannel,
    PipelineConfig,
    PlannerConfig,
    QueryConfig,
    RerankConfig,
    SymbolChannel,
    get_preset,
)

pytestmark = pytest.mark.unit


def _config(**overrides) -> PipelineConfig:
    fields: dict[str, Any] = {
        "name": "custom",
        "channels": (DenseChannel(), LexicalChannel()),
    }
    fields.update(overrides)
    return PipelineConfig(**fields)


class TestPresets:
    def test_every_preset_is_valid_and_keyed_by_its_own_name(self):
        assert set(PRESETS) == {
            "classic",
            "hybrid",
            "hybrid_rerank",
            "structural",
            "deep_agent",
            "deep_agent_workers",
        }
        for name, preset in PRESETS.items():
            assert preset.name == name
            assert get_preset(name) is preset

    def test_presets_hash_differently(self):
        hashes = {preset.config_hash() for preset in PRESETS.values()}
        assert len(hashes) == len(PRESETS)

    def test_classic_is_the_chat_endpoint(self):
        """The baseline arm has to be today's system, or comparing against it means nothing."""
        dense = CLASSIC.channel("dense")
        assert isinstance(dense, DenseChannel)
        assert [channel.kind for channel in CLASSIC.channels] == ["dense"]
        assert dense.k == 50
        assert dense.max_distance == 0.7
        assert CLASSIC.fusion == "none"
        assert CLASSIC.rerank.kind == "none"
        assert CLASSIC.query.transform == "identity"
        assert CLASSIC.query.condense is False
        assert CLASSIC.query.history_messages == 5
        assert CLASSIC.diversify.total == 10
        assert CLASSIC.diversify.caps() == {
            "symbol": 5,
            "commit": 2,
            "pull_request": 1,
            "document": 1,
            "file": 2,
        }
        assert CLASSIC.diversify.other == 2
        assert CLASSIC.execution == "single_shot"

    def test_unknown_preset_raises(self):
        with pytest.raises(KeyError):
            get_preset("nope")


class TestDecisionThresholds:
    def test_the_plan_threshold_is_a_field_with_the_documented_default(self):
        assert PlannerConfig().plan_threshold == 0.5

    def test_a_threshold_outside_zero_to_one_is_refused(self):
        with pytest.raises(ValidationError):
            PlannerConfig(plan_threshold=1.5)

    def test_a_threshold_changes_the_config_hash(self):
        def planned(threshold: float) -> PipelineConfig:
            return _config(
                execution="planner",
                agent=AgentConfig(),
                planner=PlannerConfig(plan_threshold=threshold),
            )

        assert planned(0.9).config_hash() != planned(0.5).config_hash()


class TestValidation:
    def test_unknown_channel_kind_fails_at_parse_time(self):
        with pytest.raises(ValidationError, match="kind"):
            PipelineConfig.model_validate({"name": "x", "channels": [{"kind": "telepathy"}]})

    def test_unknown_field_fails_at_parse_time(self):
        with pytest.raises(ValidationError):
            PipelineConfig.model_validate(
                {"name": "x", "channels": [{"kind": "dense", "max_distanse": 0.5}]}
            )

    def test_a_channel_may_appear_only_once(self):
        with pytest.raises(ValidationError, match="repeated: dense"):
            _config(channels=(DenseChannel(), DenseChannel(k=10)))

    def test_fusion_none_needs_exactly_one_channel(self):
        with pytest.raises(ValidationError, match="exactly one channel"):
            _config(fusion="none")
        assert _config(fusion="none", channels=(DenseChannel(),)).fusion == "none"

    @pytest.mark.parametrize("transform", ["multi_query", "hyde"])
    def test_fusion_none_rejects_transforms_that_make_several_lists(self, transform):
        with pytest.raises(ValidationError, match="single query variant"):
            _config(
                fusion="none",
                channels=(DenseChannel(),),
                query=QueryConfig(transform=transform),
            )

    def test_fusion_none_allows_condense_because_it_yields_one_variant(self):
        config = _config(
            fusion="none", channels=(DenseChannel(),), query=QueryConfig(condense=True)
        )
        assert config.query.transform == "identity"

    def test_expansion_channels_need_a_searching_channel(self):
        with pytest.raises(ValidationError, match="expand what other channels find"):
            _config(channels=(GraphChannel(), CochangeChannel()))
        _config(channels=(SymbolChannel(), GraphChannel()))

    def test_hyde_needs_the_dense_channel(self):
        with pytest.raises(ValidationError, match="hyde"):
            _config(channels=(LexicalChannel(),), query=QueryConfig(transform="hyde"))

    def test_agent_execution_needs_agent_settings(self):
        with pytest.raises(ValidationError, match="requires agent settings"):
            _config(execution="agent")
        assert _config(execution="agent", agent=AgentConfig()).agent is not None

    def test_planner_execution_needs_both(self):
        with pytest.raises(ValidationError, match="requires agent settings"):
            _config(execution="planner", planner=PlannerConfig())
        with pytest.raises(ValidationError, match="requires planner settings"):
            _config(execution="planner", agent=AgentConfig())

    def test_single_shot_takes_no_agent_settings(self):
        with pytest.raises(ValidationError, match="no agent or planner"):
            _config(agent=AgentConfig())

    def test_planner_settings_only_with_planner_execution(self):
        with pytest.raises(ValidationError, match="only apply to planner"):
            _config(execution="agent", agent=AgentConfig(), planner=PlannerConfig())

    @pytest.mark.parametrize(
        "build",
        [
            lambda: RerankConfig(top_n=61, candidate_pool=60),
            lambda: AgentConfig(max_seconds=200, hard_cancel_seconds=150),
            lambda: PlannerConfig(max_workers=2, min_subquestions=3),
            lambda: DenseChannel(k=0),
            lambda: DenseChannel(weight=0),
            lambda: QueryConfig(n_variants=9),
        ],
    )
    def test_out_of_range_values_are_refused(self, build):
        with pytest.raises(ValidationError):
            build()

    def test_the_config_is_frozen(self):
        config = _config()
        with pytest.raises(ValidationError):
            config.fusion = "none"


class TestConfigHash:
    def test_equal_configs_hash_equal(self):
        assert _config().config_hash() == _config().config_hash()

    def test_channel_order_does_not_change_the_hash(self):
        forward = _config(channels=(DenseChannel(), LexicalChannel(), SymbolChannel()))
        backward = _config(channels=(SymbolChannel(), LexicalChannel(), DenseChannel()))
        assert forward.channels == backward.channels
        assert forward.config_hash() == backward.config_hash()

    def test_the_name_is_not_part_of_the_hash(self):
        assert _config(name="a").config_hash() == _config(name="b").config_hash()

    @pytest.mark.parametrize(
        "change",
        [
            {"rrf_k": 61},
            {"channels": (DenseChannel(k=49), LexicalChannel())},
            {"channels": (DenseChannel(weight=2), LexicalChannel())},
            {"rerank": RerankConfig(kind="llm")},
            {"decider": "llm"},
            {"query": QueryConfig(condense=True)},
        ],
    )
    def test_any_behavioural_change_changes_the_hash(self, change):
        assert _config(**change).config_hash() != _config().config_hash()

    def test_the_hash_round_trips_through_json(self):
        """A config read back from a stored run must hash to what was stored."""
        config = get_preset("deep_agent_workers")
        restored = PipelineConfig.model_validate_json(config.model_dump_json())
        assert restored == config
        assert restored.config_hash() == config.config_hash()

    def test_the_hash_is_a_sha256_hex_digest(self):
        digest = _config().config_hash()
        assert len(digest) == 64
        int(digest, 16)
