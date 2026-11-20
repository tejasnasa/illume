"""The arms: every way of answering a question that the evaluation compares.

An arm is an explicit :class:`~app.services.retrieval.config.PipelineConfig`, built here from the
product's channel and config classes rather than looked up by name in ``PRESETS``. The product's
presets change several things at once between them (``structural`` carries a reranker that
``hybrid`` does not), so reading "structural versus hybrid" off the presets would be two changes
at once. Each arm instead names the arm it is compared with and the top-level config fields it
changes, and :func:`assert_arm_diffs` fails when the two configs differ anywhere else.

``auto`` is the one arm that is not generated. It is composed afterwards from a routing decision
per question and the generations of the arm the product would have run.

Library code here takes nothing from ``evals.settings``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.services.retrieval.config import (
    AgentConfig,
    CochangeChannel,
    DenseChannel,
    DiversifyConfig,
    GraphChannel,
    GrepChannel,
    HistoryChannel,
    LexicalChannel,
    PipelineConfig,
    PlannerConfig,
    QueryConfig,
    RerankConfig,
    SymbolChannel,
)
from evals.models import GENERATOR_MODEL

EVAL_INSTRUCTION = "End your answer with a list headed `Files:` naming every file that must change."
"""Appended to every question for every arm; the only prompt difference from production."""

EVAL_AGENT_MAX_INPUT_TOKENS = 300_000
"""The agent's input token cap in the evaluation; the product default is 1.5M."""

RERANKER_KIND = "cohere"
"""The reranker every reranking arm except ``hybrid_jev`` uses, fixed for the whole run."""

DECIDER = "jev"
"""Who makes the routing and planning decisions, fixed for the whole run."""

AUTO = "auto"

# Tools the text-only agent keeps, as the registry names them. ``finish`` is always offered.
TEXT_TOOLS = ("search_code", "grep_code", "read_file")

_HYBRID_CHANNELS = (DenseChannel(), LexicalChannel(), SymbolChannel())

_STRUCTURAL_CHANNELS = (
    *_HYBRID_CHANNELS,
    GrepChannel(weight=0.7),
    GraphChannel(),
    CochangeChannel(),
    HistoryChannel(),
)


class ArmDiffError(ValueError):
    """An arm differs from its comparison arm in fields it did not declare."""


@dataclass(frozen=True)
class Arm:
    """One way of answering, and how it differs from the arm it is compared with.

    Attributes:
        name: The arm's name; ``structural_-graph`` style names carry a removed channel.
        config: The full pipeline configuration, or ``None`` for the composed ``auto`` arm.
        model: The generator model id.
        comparison: The arm this one is compared with, or ``None`` for a baseline.
        changes: The top-level config fields that deliberately differ from the comparison arm.
        description: One line on what the arm is.
    """

    name: str
    config: PipelineConfig | None
    model: str = GENERATOR_MODEL
    comparison: str | None = None
    changes: tuple[str, ...] = ()
    description: str = ""

    @property
    def composed(self) -> bool:
        """Whether the arm is built from other arms' results rather than generated."""
        return self.config is None

    @property
    def is_agent(self) -> bool:
        """Whether the arm runs the tool-calling agent (alone or with workers)."""
        return self.config is not None and self.config.execution != "single_shot"

    def config_hash(self) -> str:
        """The behaviour hash of the arm.

        For a generated arm this is :meth:`PipelineConfig.config_hash`. The composed arm has no
        configuration, so its hash is derived from its name alone.
        """
        if self.config is not None:
            return self.config.config_hash()
        return hashlib.sha256(f"composed:{self.name}".encode()).hexdigest()


def question_with_instruction(question: str) -> str:
    """The question as every arm receives it: the question, a blank line, the instruction."""
    return f"{question}\n\n{EVAL_INSTRUCTION}"


# --- the table -------------------------------------------------------------


def _structural_without(kind: str) -> tuple[Any, ...]:
    return tuple(channel for channel in _STRUCTURAL_CHANNELS if channel.kind != kind)


def _agent_config(name: str, *, planner: bool = False, **overrides: Any) -> PipelineConfig:
    fields: dict[str, Any] = {
        "name": name,
        "query": QueryConfig(condense=True, history_messages=10),
        "channels": _STRUCTURAL_CHANNELS,
        "rerank": RerankConfig(kind="cohere"),
        "diversify": DiversifyConfig(total=20),
        "execution": "planner" if planner else "agent",
        "agent": AgentConfig(max_input_tokens=EVAL_AGENT_MAX_INPUT_TOKENS),
        "planner": PlannerConfig() if planner else None,
    }
    fields.update(overrides)
    return PipelineConfig(**fields)


def _single_shot(name: str, channels: tuple[Any, ...], **fields: Any) -> PipelineConfig:
    fields.setdefault("query", QueryConfig(condense=True))
    fields.setdefault("diversify", DiversifyConfig(total=20))
    return PipelineConfig(name=name, channels=channels, **fields)


def _build_arms() -> dict[str, Arm]:
    classic = PipelineConfig(
        name="classic",
        query=QueryConfig(transform="identity", condense=False, history_messages=5),
        channels=(DenseChannel(k=50, max_distance=0.7),),
        fusion="none",
        rerank=RerankConfig(kind="none"),
        diversify=DiversifyConfig(total=10),
    )
    hybrid = _single_shot("hybrid", _HYBRID_CHANNELS)
    structural = _single_shot("structural", _STRUCTURAL_CHANNELS)
    cohere = RerankConfig(kind="cohere")
    agent = _agent_config("agent")

    arms = [
        Arm("classic", classic, description="Dense search only; the product's Classic preset."),
        Arm(
            "hybrid",
            hybrid,
            comparison="classic",
            changes=("channels", "fusion", "query", "diversify"),
            description="Adds lexical and symbol search and reciprocal rank fusion.",
        ),
        Arm(
            "hybrid_rerank",
            _single_shot("hybrid_rerank", _HYBRID_CHANNELS, rerank=cohere),
            comparison="hybrid",
            changes=("rerank",),
            description="Hybrid with the Cohere reranker.",
        ),
        Arm(
            "hybrid_jev",
            _single_shot("hybrid_jev", _HYBRID_CHANNELS, rerank=RerankConfig(kind="jev")),
            comparison="hybrid_rerank",
            changes=("rerank",),
            description="Hybrid with the Jev reranker instead of Cohere.",
        ),
        Arm(
            "hybrid_multiquery",
            _single_shot(
                "hybrid_multiquery",
                _HYBRID_CHANNELS,
                query=QueryConfig(transform="multi_query", condense=True),
            ),
            comparison="hybrid",
            changes=("query",),
            description="The question rewritten into several variants.",
        ),
        Arm(
            "hybrid_hyde",
            _single_shot(
                "hybrid_hyde",
                _HYBRID_CHANNELS,
                query=QueryConfig(transform="hyde", condense=True),
            ),
            comparison="hybrid",
            changes=("query",),
            description="Dense search also runs a hypothetical code snippet.",
        ),
        Arm(
            "structural",
            structural,
            comparison="hybrid",
            changes=("channels",),
            description="Adds grep, graph, co-change and history channels; no reranker.",
        ),
        *(
            Arm(
                f"structural_-{kind}",
                _single_shot(f"structural_-{kind}", _structural_without(kind)),
                comparison="structural",
                changes=("channels",),
                description=f"Structural without the {kind} channel.",
            )
            for kind in ("graph", "cochange", "history", "grep")
        ),
        Arm(
            "structural_rerank",
            _single_shot("structural_rerank", _STRUCTURAL_CHANNELS, rerank=cohere),
            comparison="structural",
            changes=("rerank",),
            description="Structural with the Cohere reranker; the product's Structural preset.",
        ),
        Arm("agent", agent, description="The product's deep agent, with the input token cap."),
        Arm(
            "agent_text_tools",
            _agent_config(
                "agent_text_tools",
                channels=_HYBRID_CHANNELS,
                agent=AgentConfig(max_input_tokens=EVAL_AGENT_MAX_INPUT_TOKENS, tools=TEXT_TOOLS),
            ),
            comparison="agent",
            changes=("agent", "channels"),
            description=(
                "Only search, grep and read tools, with the Hybrid channels behind the seed "
                "and search_code."
            ),
        ),
        Arm(
            "agent_workers",
            _agent_config("agent_workers", planner=True),
            comparison="agent",
            changes=("execution", "planner"),
            description="A planner fans the question out to parallel workers.",
        ),
        Arm(
            AUTO,
            None,
            description=(
                "Composed: one routing decision per question, then the generation of the arm "
                "the product would have run."
            ),
        ),
    ]
    return {arm.name: arm for arm in arms}


ARMS: dict[str, Arm] = _build_arms()

STARTER_ARMS: tuple[str, ...] = (
    "classic",
    "hybrid",
    "hybrid_rerank",
    "hybrid_hyde",
    "hybrid_multiquery",
    "structural",
    "structural_-cochange",
    "structural_rerank",
    "agent",
    AUTO,
)
"""The arms of the starter run, every one on every question."""


def get_arm(name: str) -> Arm:
    """The arm called ``name``.

    Raises:
        KeyError: When there is none, listing the arms that exist.
    """
    try:
        return ARMS[name]
    except KeyError:
        raise KeyError(f"no arm named {name!r}; arms: {', '.join(ARMS)}") from None


def generated_arms(names: tuple[str, ...] | list[str] | None = None) -> list[Arm]:
    """The arms that are generated rather than composed, in the order given.

    Args:
        names: Arm names to keep; every arm in the table when omitted.
    """
    chosen = [get_arm(name) for name in names] if names is not None else list(ARMS.values())
    return [arm for arm in chosen if not arm.composed]


# --- the diff assertion ------------------------------------------------------


def differing_fields(a: PipelineConfig, b: PipelineConfig) -> set[str]:
    """The top-level fields in which two configs differ, ignoring the name.

    A channel added or removed, or one whose settings changed, counts as the ``channels`` field.
    """
    left, right = a.model_dump(mode="json"), b.model_dump(mode="json")
    return {field for field in left if field != "name" and left[field] != right[field]}


def channel_changes(a: PipelineConfig, b: PipelineConfig) -> dict[str, list[str]]:
    """Which channel kinds ``b`` adds to and removes from ``a``, for readable messages."""
    kinds_a = {channel.kind for channel in a.channels}
    kinds_b = {channel.kind for channel in b.channels}
    return {"added": sorted(kinds_b - kinds_a), "removed": sorted(kinds_a - kinds_b)}


def assert_arm_diffs(arms: Mapping[str, Arm] | None = None) -> None:
    """Checks every arm differs from its comparison arm in exactly the declared fields.

    Args:
        arms: The arms to check; the table when omitted. Composed arms are skipped.

    Raises:
        ArmDiffError: When an arm's comparison is unknown, when a field differs that the arm
            did not declare, or when a declared field does not differ.
    """
    table = ARMS if arms is None else arms
    problems: list[str] = []
    for arm in table.values():
        if arm.config is None or arm.comparison is None:
            continue
        other = table.get(arm.comparison)
        if other is None or other.config is None:
            problems.append(f"{arm.name}: comparison arm {arm.comparison!r} is not a generated arm")
            continue
        differing = differing_fields(arm.config, other.config)
        undeclared = sorted(differing - set(arm.changes))
        unused = sorted(set(arm.changes) - differing)
        if undeclared:
            detail = ""
            if "channels" in undeclared:
                detail = f" (channels {json.dumps(channel_changes(other.config, arm.config))})"
            problems.append(
                f"{arm.name} vs {arm.comparison}: undeclared differences in "
                f"{', '.join(undeclared)}{detail}"
            )
        if unused:
            problems.append(
                f"{arm.name} vs {arm.comparison}: declares {', '.join(unused)} but they are equal"
            )
    if problems:
        raise ArmDiffError("; ".join(problems))


def describe_arms() -> dict[str, Any]:
    """The arm definitions as the run manifest records them."""
    return {
        "instruction": EVAL_INSTRUCTION,
        "agent_max_input_tokens": EVAL_AGENT_MAX_INPUT_TOKENS,
        "reranker_kind": RERANKER_KIND,
        "decider": DECIDER,
        "arms": {
            arm.name: {
                "model": arm.model,
                "comparison": arm.comparison,
                "changes": list(arm.changes),
                "composed": arm.composed,
                "config_hash": arm.config_hash(),
                "config": arm.config.model_dump(mode="json") if arm.config else None,
            }
            for arm in ARMS.values()
        },
    }


__all__ = [
    "ARMS",
    "AUTO",
    "DECIDER",
    "EVAL_AGENT_MAX_INPUT_TOKENS",
    "EVAL_INSTRUCTION",
    "RERANKER_KIND",
    "STARTER_ARMS",
    "TEXT_TOOLS",
    "Arm",
    "ArmDiffError",
    "assert_arm_diffs",
    "describe_arms",
    "differing_fields",
    "generated_arms",
    "get_arm",
    "question_with_instruction",
]
