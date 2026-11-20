"""The arm table: every arm differs from its comparison arm only where it says it does."""

import json
from dataclasses import replace

import pytest

from app.services.agent.tools import REGISTRY
from app.services.retrieval.config import (
    CLASSIC,
    DEEP_AGENT,
    DEEP_AGENT_WORKERS,
    HYBRID,
    HYBRID_RERANK,
    STRUCTURAL,
    AgentConfig,
    QueryConfig,
    RerankConfig,
)
from app.services.retrieval.single_shot import is_classic_shaped
from evals.arms import (
    ARMS,
    EVAL_AGENT_MAX_INPUT_TOKENS,
    EVAL_INSTRUCTION,
    STARTER_ARMS,
    TEXT_TOOLS,
    ArmDiffError,
    assert_arm_diffs,
    describe_arms,
    generated_arms,
    get_arm,
    question_with_instruction,
)

pytestmark = pytest.mark.unit


def _table(**extra):
    """The arms a comparison needs, plus the ones under test."""
    base = {name: get_arm(name) for name in ("classic", "hybrid", "structural")}
    return {**base, **extra}


def _kinds(name):
    return {channel.kind for channel in get_arm(name).config.channels}


class TestArmDiffs:
    def test_every_arm_in_the_table_passes(self):
        assert_arm_diffs()

    def test_an_undeclared_arm_changing_two_fields_is_caught(self):
        sneaky = replace(
            get_arm("hybrid_rerank"),
            name="sneaky",
            config=get_arm("hybrid").config.model_copy(
                update={
                    "rerank": RerankConfig(kind="cohere"),
                    "query": QueryConfig(transform="hyde", condense=True),
                }
            ),
            comparison="hybrid",
            changes=("rerank",),
        )
        with pytest.raises(ArmDiffError, match="undeclared differences in query"):
            assert_arm_diffs(_table(sneaky=sneaky))

    def test_a_declared_multi_field_arm_is_accepted(self):
        declared = replace(
            get_arm("hybrid_rerank"),
            name="declared",
            config=get_arm("hybrid").config.model_copy(
                update={
                    "rerank": RerankConfig(kind="cohere"),
                    "query": QueryConfig(transform="hyde", condense=True),
                }
            ),
            comparison="hybrid",
            changes=("rerank", "query"),
        )
        assert_arm_diffs(_table(declared=declared))

    def test_a_declared_field_that_does_not_differ_is_caught(self):
        stale = replace(
            get_arm("hybrid_rerank"), name="stale", comparison="hybrid", changes=("rerank", "query")
        )
        with pytest.raises(ArmDiffError, match="declares query but they are equal"):
            assert_arm_diffs(_table(stale=stale))

    def test_a_channel_change_counts_as_the_channels_field(self):
        extra = replace(
            get_arm("structural"),
            name="extra",
            config=get_arm("structural").config.model_copy(
                update={"channels": get_arm("hybrid").config.channels}
            ),
            comparison="structural",
            changes=(),
        )
        with pytest.raises(ArmDiffError, match=r"undeclared differences in channels.*removed"):
            assert_arm_diffs(_table(extra=extra))

    def test_an_unknown_comparison_arm_is_reported(self):
        orphan = replace(get_arm("hybrid"), name="orphan", comparison="nope")
        with pytest.raises(ArmDiffError, match="'nope'"):
            assert_arm_diffs(_table(orphan=orphan))


class TestTable:
    def test_structural_has_no_reranker_and_its_rerank_arm_has_cohere(self):
        assert get_arm("structural").config.rerank.kind == "none"
        assert get_arm("structural_rerank").config.rerank.kind == "cohere"

    def test_the_starter_arm_list_is_the_plans(self):
        assert STARTER_ARMS == (
            "classic",
            "hybrid",
            "hybrid_rerank",
            "hybrid_hyde",
            "hybrid_multiquery",
            "structural",
            "structural_-cochange",
            "structural_rerank",
            "agent",
            "auto",
        )
        assert all(name in ARMS for name in STARTER_ARMS)
        assert "agent_workers" not in STARTER_ARMS and "hybrid_jev" not in STARTER_ARMS

    @pytest.mark.parametrize("kind", ["graph", "cochange", "history", "grep"])
    def test_a_structural_ablation_removes_exactly_one_channel(self, kind):
        arm = get_arm(f"structural_-{kind}")
        assert arm.comparison == "structural"
        assert _kinds("structural") - _kinds(arm.name) == {kind}
        assert _kinds(arm.name) - _kinds("structural") == set()

    def test_hybrid_adds_lexical_and_symbol_to_classic(self):
        assert _kinds("classic") == {"dense"}
        assert _kinds("hybrid") == {"dense", "lexical", "symbol"}
        assert get_arm("hybrid").changes == ("channels", "fusion", "query", "diversify")

    def test_the_transform_arms_change_only_the_query(self):
        assert get_arm("hybrid_hyde").config.query.transform == "hyde"
        assert get_arm("hybrid_multiquery").config.query.transform == "multi_query"
        assert get_arm("hybrid_jev").config.rerank.kind == "jev"

    def test_the_agent_arms(self):
        agent = get_arm("agent").config
        assert agent.agent.max_input_tokens == EVAL_AGENT_MAX_INPUT_TOKENS == 300_000
        assert agent.execution == "agent"

        text = get_arm("agent_text_tools")
        assert text.config.agent.tools == TEXT_TOOLS
        assert set(TEXT_TOOLS) <= set(REGISTRY.names())
        assert _kinds("agent_text_tools") == {"dense", "lexical", "symbol"}
        assert text.changes == ("agent", "channels")

        workers = get_arm("agent_workers")
        assert workers.config.execution == "planner"
        assert workers.config.agent.max_input_tokens == EVAL_AGENT_MAX_INPUT_TOKENS
        assert workers.changes == ("execution", "planner")

    def test_arms_reproduce_the_products_presets(self):
        capped = AgentConfig(max_input_tokens=EVAL_AGENT_MAX_INPUT_TOKENS)
        expected = {
            "classic": CLASSIC,
            "hybrid": HYBRID,
            "hybrid_rerank": HYBRID_RERANK,
            "structural_rerank": STRUCTURAL,
            "agent": DEEP_AGENT.model_copy(update={"agent": capped}),
            "agent_workers": DEEP_AGENT_WORKERS.model_copy(update={"agent": capped}),
        }
        for name, preset in expected.items():
            assert get_arm(name).config.config_hash() == preset.config_hash(), name
        assert is_classic_shaped(get_arm("classic").config)

    def test_no_two_arms_behave_the_same(self):
        hashes = [arm.config_hash() for arm in ARMS.values()]
        assert len(set(hashes)) == len(hashes)

    def test_auto_is_composed_and_the_rest_are_generated(self):
        assert get_arm("auto").composed and get_arm("auto").config is None
        assert "auto" not in [arm.name for arm in generated_arms()]
        assert [arm.name for arm in generated_arms(["auto", "classic"])] == ["classic"]

    def test_an_unknown_arm_lists_the_known_ones(self):
        with pytest.raises(KeyError, match="classic"):
            get_arm("nope")


def test_the_instruction_is_appended_after_a_blank_line():
    assert question_with_instruction("Why?") == f"Why?\n\n{EVAL_INSTRUCTION}"
    assert EVAL_INSTRUCTION.startswith("End your answer with a list headed `Files:`")


def test_the_manifest_description_is_json():
    described = json.loads(json.dumps(describe_arms()))
    assert described["instruction"] == EVAL_INSTRUCTION
    assert described["reranker_kind"] == "cohere" and described["decider"] == "jev"
    assert described["arms"]["auto"]["composed"] is True
    assert described["arms"]["agent"]["config_hash"] == get_arm("agent").config_hash()
