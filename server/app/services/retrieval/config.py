"""The configuration object that fully describes one way of answering.

A :class:`PipelineConfig` names one choice for every slot of the pipeline: how
the question is rewritten, which channels search, how their lists are merged
and reranked, how the result is narrowed, how the answer is produced, and which
checks run. A user-facing preset is one of these, and so is an evaluation arm,
which is what lets a result be traced back to exactly what produced it through
:meth:`PipelineConfig.config_hash`.

The model is frozen for the same reason :class:`~app.services.llm_config.LLMConfig`
is: it is handed across task boundaries and must not change mid-run. Presets
are module constants rather than ``Settings`` fields, in line with the rest of
the repository's tunables.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Frozen(BaseModel):
    """Frozen, and strict about unknown fields so a typo fails at parse time."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# --- query -----------------------------------------------------------------


class QueryConfig(_Frozen):
    """How the question becomes the text the channels search for.

    Attributes:
        transform: ``identity`` searches with the question as typed;
            ``multi_query`` adds rewrites in different vocabulary; ``hyde``
            adds a hypothetical code snippet, searched by the dense channel only.
        condense: Rewrite a follow-up into a standalone question using the
            conversation first. Skipped when there is no history.
        n_variants: How many rewrites ``multi_query`` asks for.
        history_messages: How many prior messages are replayed to the answering
            model, counted in messages rather than exchanges.
    """

    transform: Literal["identity", "multi_query", "hyde"] = "identity"
    condense: bool = False
    n_variants: int = Field(default=3, ge=3, le=5)
    history_messages: int = Field(default=5, ge=0, le=20)


# --- channels --------------------------------------------------------------


class _ChannelBase(_Frozen):
    """Fields every channel shares.

    Attributes:
        weight: The channel's weight in fusion.
        k: How many hits the channel returns per query variant.
    """

    weight: float = Field(default=1.0, gt=0, le=10)
    k: int = Field(default=50, ge=1, le=200)


class DenseChannel(_ChannelBase):
    """Vector similarity over every embedded chunk.

    Attributes:
        max_distance: Cosine distances at or above this are dropped before
            ranking. ``0.7`` is a similarity above ``0.3``.
    """

    kind: Literal["dense"] = "dense"
    max_distance: float = Field(default=0.7, gt=0, le=2)


class LexicalChannel(_ChannelBase):
    """Full-text search over every chunk, with identifiers split into words."""

    kind: Literal["lexical"] = "lexical"


class SymbolChannel(_ChannelBase):
    """Exact and fuzzy matching of identifiers in the question against symbol names.

    Attributes:
        min_similarity: The trigram similarity a fuzzy name match must exceed.
    """

    kind: Literal["symbol"] = "symbol"
    min_similarity: float = Field(default=0.3, ge=0, le=1)


class GrepChannel(_ChannelBase):
    """Literal search for identifier-like tokens inside stored symbol bodies."""

    kind: Literal["grep"] = "grep"


class GraphChannel(_ChannelBase):
    """Files one import away from the strongest files the other channels found.

    Attributes:
        seeds: How many top files from the first fusion pass are expanded.
        decay: The fraction of a seed's score its neighbours inherit.
    """

    kind: Literal["graph"] = "graph"
    seeds: int = Field(default=5, ge=1, le=20)
    decay: float = Field(default=0.5, gt=0, le=1)


class CochangeChannel(_ChannelBase):
    """Files that tend to change in the same commits as the strongest files.

    Attributes:
        seeds: How many top files from the first fusion pass are expanded.
    """

    kind: Literal["cochange"] = "cochange"
    seeds: int = Field(default=5, ge=1, le=20)


class HistoryChannel(_ChannelBase):
    """Dense and lexical search restricted to commits and pull requests.

    Attributes:
        max_distance: The dense half's distance cut, as for :class:`DenseChannel`.
    """

    kind: Literal["history"] = "history"
    max_distance: float = Field(default=0.7, gt=0, le=2)


ChannelSpec = Annotated[
    DenseChannel
    | LexicalChannel
    | SymbolChannel
    | GrepChannel
    | GraphChannel
    | CochangeChannel
    | HistoryChannel,
    Field(discriminator="kind"),
]

ChannelKind = Literal["dense", "lexical", "symbol", "grep", "graph", "cochange", "history"]

# Channels that expand the files other channels found rather than searching on
# their own, so they need at least one searching channel beside them.
EXPANSION_CHANNELS: frozenset[str] = frozenset({"graph", "cochange"})


# --- merging, reranking, narrowing -------------------------------------------


class RerankConfig(_Frozen):
    """Which reranker reorders the fused list, and how much of it.

    Attributes:
        kind: ``none`` keeps the fused order.
        candidate_pool: How many fused candidates the reranker sees.
        top_n: How many it returns.
    """

    kind: Literal["none", "cohere", "llm", "jev"] = "none"
    candidate_pool: int = Field(default=60, ge=1, le=200)
    top_n: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def _top_n_fits_the_pool(self) -> Self:
        if self.top_n > self.candidate_pool:
            raise ValueError("rerank.top_n cannot exceed rerank.candidate_pool")
        return self


class DiversifyConfig(_Frozen):
    """Per-source-type caps applied to the final list.

    The caps are soft: once every type has had its share, remaining slots are
    filled by relevance regardless of type. The defaults are the chat
    endpoint's long-standing values.

    Attributes:
        total: How many candidates survive.
        symbol: Cap for symbol chunks.
        commit: Cap for commits.
        pull_request: Cap for pull requests.
        document: Cap for README sections.
        file: Cap for whole-file chunks.
        other: Cap for any type not listed.
    """

    total: int = Field(default=10, ge=1, le=100)
    symbol: int = Field(default=5, ge=0)
    commit: int = Field(default=2, ge=0)
    pull_request: int = Field(default=1, ge=0)
    document: int = Field(default=1, ge=0)
    file: int = Field(default=2, ge=0)
    other: int = Field(default=2, ge=0)

    def caps(self) -> dict[str, int]:
        """The caps keyed by source type, without the fallback for unknown types."""
        return {
            "symbol": self.symbol,
            "commit": self.commit,
            "pull_request": self.pull_request,
            "document": self.document,
            "file": self.file,
        }


# --- execution -------------------------------------------------------------


class AgentConfig(_Frozen):
    """Limits and switches for the tool-calling loop.

    Every limit is a field so an evaluation run records it and can vary it.
    They are generous because the user pays for their own tokens; they exist to
    stop runaways and keep the interface responsive.

    Attributes:
        max_iterations: Model turns per agent or worker.
        max_tool_calls: Tool calls across the whole run.
        max_seconds: Wall clock before the run answers with what it has.
        hard_cancel_seconds: Wall clock before the run is cancelled outright.
        max_input_tokens: Input tokens across the run, from reported usage.
        max_repair_rounds: Rounds spent fixing unsupported citations.
        max_gate_rejections: Times the sufficiency check may send the agent
            back before it must answer.
        seed: Run the retrieval pipeline once before the first model turn.
        tools: Tool names the agent may call; ``None`` means every tool.
        effort: The reasoning effort requested from providers that support it.
    """

    max_iterations: int = Field(default=12, ge=1, le=50)
    max_tool_calls: int = Field(default=60, ge=1, le=300)
    max_seconds: int = Field(default=120, ge=10, le=600)
    hard_cancel_seconds: int = Field(default=150, ge=10, le=900)
    max_input_tokens: int = Field(default=1_500_000, ge=1_000, le=10_000_000)
    max_repair_rounds: int = Field(default=1, ge=0, le=3)
    max_gate_rejections: int = Field(default=2, ge=0, le=5)
    seed: bool = True
    tools: tuple[str, ...] | None = None
    effort: Literal["minimal", "low", "medium", "high"] = "low"

    @model_validator(mode="after")
    def _hard_cancel_after_soft_stop(self) -> Self:
        if self.hard_cancel_seconds < self.max_seconds:
            raise ValueError("agent.hard_cancel_seconds must be at least agent.max_seconds")
        return self


class PlannerConfig(_Frozen):
    """How a question is split across parallel workers.

    Attributes:
        max_workers: The most sub-questions one run may fan out to.
        worker_iterations: Model turns per worker.
        min_subquestions: Below this many sub-questions, planning is skipped
            and a single agent answers.
        plan_threshold: The probability that the question needs several
            independent investigations, below which planning is skipped.
    """

    max_workers: int = Field(default=4, ge=2, le=6)
    worker_iterations: int = Field(default=8, ge=1, le=50)
    min_subquestions: int = Field(default=2, ge=2, le=6)
    plan_threshold: float = Field(default=0.5, ge=0, le=1)

    @model_validator(mode="after")
    def _minimum_fits_the_maximum(self) -> Self:
        if self.min_subquestions > self.max_workers:
            raise ValueError("planner.min_subquestions cannot exceed planner.max_workers")
        return self


class ChecksConfig(_Frozen):
    """The checks that run on the way to an answer.

    Attributes:
        gate: Ask whether the evidence suffices before the agent may answer.
        verify: Check each cited claim against the text it cites.
        guard: Screen repository text for instructions aimed at the model.
        sufficiency_threshold: The probability at which the gate lets the
            agent answer.
        injection_threshold: The probability at which the guard withholds text.
    """

    gate: bool = False
    verify: bool = False
    guard: bool = False
    sufficiency_threshold: float = Field(default=0.7, ge=0, le=1)
    injection_threshold: float = Field(default=0.5, ge=0, le=1)


# --- the whole -------------------------------------------------------------


class PipelineConfig(_Frozen):
    """One complete choice for every slot of the pipeline.

    Attributes:
        name: The preset's name, or ``custom``. Not part of the hash.
        query: How the question is rewritten.
        channels: Which channels search, stored sorted by kind so the order
            they were written in does not change the hash.
        fusion: ``rrf`` merges the channels' lists; ``none`` is only valid with
            a single channel and the ``identity`` transform (condense still
            yields one variant).
        rrf_k: The rank offset in reciprocal rank fusion.
        rerank: Which reranker runs on the fused list.
        diversify: The caps on the final list.
        execution: Answer directly, run the tool-calling agent, or fan out
            to parallel workers.
        agent: Required for ``agent`` and ``planner`` execution.
        planner: Required for ``planner`` execution.
        checks: Which checks run.
        decider: Who makes the narrow yes/no and choice decisions.
    """

    name: str = Field(min_length=1, max_length=64)
    query: QueryConfig = QueryConfig()
    channels: tuple[ChannelSpec, ...] = Field(min_length=1)
    fusion: Literal["none", "rrf"] = "rrf"
    rrf_k: int = Field(default=60, ge=1, le=1000)
    rerank: RerankConfig = RerankConfig()
    diversify: DiversifyConfig = DiversifyConfig()
    execution: Literal["single_shot", "agent", "planner"] = "single_shot"
    agent: AgentConfig | None = None
    planner: PlannerConfig | None = None
    checks: ChecksConfig = ChecksConfig()
    decider: Literal["jev", "llm"] = "jev"

    @field_validator("channels", mode="after")
    @classmethod
    def _sort_channels(cls, channels: tuple[ChannelSpec, ...]) -> tuple[ChannelSpec, ...]:
        return tuple(sorted(channels, key=lambda channel: channel.kind))

    @model_validator(mode="after")
    def _slots_agree(self) -> Self:
        kinds = [channel.kind for channel in self.channels]
        duplicates = sorted({kind for kind in kinds if kinds.count(kind) > 1})
        if duplicates:
            raise ValueError(f"each channel may appear once; repeated: {', '.join(duplicates)}")

        if not set(kinds) - EXPANSION_CHANNELS:
            raise ValueError(
                "graph and cochange expand what other channels find; "
                "add at least one of dense, lexical, symbol, grep or history"
            )

        if self.fusion == "none" and len(self.channels) != 1:
            raise ValueError("fusion 'none' requires exactly one channel")

        if self.fusion == "none" and self.query.transform != "identity":
            raise ValueError(
                "fusion 'none' needs a single query variant; "
                "multi_query and hyde produce several lists to merge"
            )

        if self.query.transform == "hyde" and "dense" not in kinds:
            raise ValueError("the hyde transform is searched by the dense channel, which is off")

        if self.execution == "single_shot":
            if self.agent is not None or self.planner is not None:
                raise ValueError("single_shot execution takes no agent or planner settings")
            if self.checks.gate:
                raise ValueError("the sufficiency gate needs agent or planner execution")
        if self.execution in ("agent", "planner") and self.agent is None:
            raise ValueError(f"{self.execution} execution requires agent settings")
        if self.execution == "planner" and self.planner is None:
            raise ValueError("planner execution requires planner settings")
        if self.execution == "agent" and self.planner is not None:
            raise ValueError("planner settings only apply to planner execution")

        return self

    def channel(self, kind: str) -> ChannelSpec | None:
        """The settings for one channel kind, or ``None`` when it is off."""
        return next((channel for channel in self.channels if channel.kind == kind), None)

    def config_hash(self) -> str:
        """SHA-256 of the canonical JSON of every behavioural field.

        The name is left out, so renaming a preset does not split its results
        from earlier runs, and two arms that behave the same hash the same.
        """
        payload = self.model_dump(mode="json", exclude={"name"})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- presets ---------------------------------------------------------------

# Today's chat endpoint, reproduced exactly: one dense search, distance below
# 0.7, the 50 nearest, the long-standing caps down to 10, no rewriting.
CLASSIC = PipelineConfig(
    name="classic",
    query=QueryConfig(transform="identity", condense=False, history_messages=5),
    channels=(DenseChannel(k=50, max_distance=0.7),),
    fusion="none",
    rerank=RerankConfig(kind="none"),
    diversify=DiversifyConfig(total=10),
)

_HYBRID_CHANNELS = (DenseChannel(), LexicalChannel(), SymbolChannel())

# Grep is weighted below the ranked channels: a literal match is strong evidence
# for a body nothing else indexes, but its hits carry no relevance order.
_STRUCTURAL_CHANNELS = (
    *_HYBRID_CHANNELS,
    GrepChannel(weight=0.7),
    GraphChannel(),
    CochangeChannel(),
    HistoryChannel(),
)

HYBRID = PipelineConfig(
    name="hybrid",
    query=QueryConfig(condense=True),
    channels=_HYBRID_CHANNELS,
    diversify=DiversifyConfig(total=20),
)

HYBRID_RERANK = PipelineConfig(
    name="hybrid_rerank",
    query=QueryConfig(condense=True),
    channels=_HYBRID_CHANNELS,
    rerank=RerankConfig(kind="jev"),
    diversify=DiversifyConfig(total=20),
    checks=ChecksConfig(verify=True),
)

STRUCTURAL = PipelineConfig(
    name="structural",
    query=QueryConfig(condense=True),
    channels=_STRUCTURAL_CHANNELS,
    rerank=RerankConfig(kind="jev"),
    diversify=DiversifyConfig(total=20),
    checks=ChecksConfig(verify=True),
)

DEEP_AGENT = PipelineConfig(
    name="deep_agent",
    query=QueryConfig(condense=True, history_messages=10),
    channels=_STRUCTURAL_CHANNELS,
    rerank=RerankConfig(kind="jev"),
    diversify=DiversifyConfig(total=20),
    execution="agent",
    agent=AgentConfig(),
    checks=ChecksConfig(gate=True, verify=True, guard=True),
)

DEEP_AGENT_WORKERS = PipelineConfig(
    name="deep_agent_workers",
    query=QueryConfig(condense=True, history_messages=10),
    channels=_STRUCTURAL_CHANNELS,
    rerank=RerankConfig(kind="jev"),
    diversify=DiversifyConfig(total=20),
    execution="planner",
    agent=AgentConfig(),
    planner=PlannerConfig(),
    checks=ChecksConfig(gate=True, verify=True, guard=True),
)

PRESETS: dict[str, PipelineConfig] = {
    preset.name: preset
    for preset in (
        CLASSIC,
        HYBRID,
        HYBRID_RERANK,
        STRUCTURAL,
        DEEP_AGENT,
        DEEP_AGENT_WORKERS,
    )
}


def get_preset(name: str) -> PipelineConfig:
    """The preset with this name.

    Raises:
        KeyError: When no preset has that name.
    """
    return PRESETS[name]
