"""Running the retrieval channels over a question and narrowing what they find.

The stages, in order: build the query variants, embed every text a dense search
will need in one call, search with each channel over each variant, fuse the
lists, optionally expand the strongest files through the graph and co-change
channels and fuse again, take the candidate pool, rerank it, and diversify.

Every channel call runs in its own savepoint. A SQL failure aborts the enclosing
Postgres transaction, and the session is shared, so without the savepoint one
failing channel would break every channel after it. A failed channel, a failed
query rewrite and a failed reranker all degrade to a smaller result with a
``degraded`` event and a trace entry; none of them fails the request.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.services.llm_config import LLMConfig
from app.services.retrieval.candidate import Candidate, QueryVariant
from app.services.retrieval.channels import get_channel, get_expansion_channel
from app.services.retrieval.channels.base import RetrievalContext
from app.services.retrieval.config import EXPANSION_CHANNELS, PipelineConfig
from app.services.retrieval.diversify import diversify
from app.services.retrieval.fusion import RankedList, fuse, reciprocal_rank_fusion
from app.services.retrieval.query import HistoryMessage, build_variants
from app.services.retrieval.rerank import get_reranker

logger = logging.getLogger(__name__)

# Channels whose searches embed the query text.
_DENSE_USING = frozenset({"dense", "history"})


@dataclass(frozen=True)
class ChannelTrace:
    """What one channel did for one query variant.

    Attributes:
        channel: The channel kind.
        variant: The query variant index; ``0`` for expansion channels.
        stage: ``search`` for channels that search the question, ``expansion``
            for graph and co-change.
        candidates: How many candidates it returned (``0`` when it failed).
        ms: Wall time in milliseconds.
        error: The failure, as ``ExceptionType: message``, or ``None``.
    """

    channel: str
    variant: int
    stage: str
    candidates: int
    ms: float
    error: str | None = None


@dataclass(frozen=True)
class RetrievalTrace:
    """How a retrieval ran, in JSON-serialisable form.

    Attributes:
        channels: One entry per ``(channel, variant)``, in the order they ran.
        reranker: The reranker kind the config asked for.
        reranker_degraded: Whether the reranker failed and the fused order was used.
        degraded: The payload of every ``degraded`` event raised, in order.
        config_hash: :meth:`PipelineConfig.config_hash` of the config that ran.
        rerank_calls: The provider requests the reranker made, raw responses
            included, as :meth:`RerankCall.to_dict` records. Kept for the log
            and the evaluation; empty when no provider was called.
    """

    channels: tuple[ChannelTrace, ...]
    reranker: str
    reranker_degraded: bool
    degraded: tuple[dict[str, Any], ...]
    config_hash: str
    rerank_calls: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class RetrievalResult:
    """The outcome of one retrieval.

    Attributes:
        question: The standalone question the channels started from.
        variants: Every query variant searched, variant 0 first.
        candidates: The final, diversified list, best first.
        pool: The fused pool handed to the reranker, before reranking.
        trace: How the run went.
    """

    question: str
    variants: tuple[QueryVariant, ...]
    candidates: tuple[Candidate, ...]
    pool: tuple[Candidate, ...]
    trace: RetrievalTrace


@dataclass
class _Run:
    """Mutable state of one retrieval: the trace entries and degradations so far."""

    ctx: RetrievalContext
    traces: list[ChannelTrace] = field(default_factory=list)
    degraded: list[dict[str, Any]] = field(default_factory=list)
    search_errors: list[Exception] = field(default_factory=list)

    async def emit(self, event: str, payload: dict[str, Any]) -> None:
        """Records a ``degraded`` event and forwards every event to the context's emitter."""
        if event == "degraded":
            self.degraded.append(dict(payload))
        try:
            await self.ctx.emit(event, payload)
        except Exception:
            logger.warning("emitting %s failed", event, exc_info=True)


def _error_text(error: Exception) -> str:
    """``ExceptionType: message``, bounded so a huge SQL error stays loggable."""
    return f"{type(error).__name__}: {error}"[:300]


def _variants_for(kind: str, variants: Sequence[QueryVariant]) -> list[QueryVariant]:
    """The variants a channel searches: hypothetical snippets go to dense search only."""
    if kind == "dense":
        return list(variants)
    return [variant for variant in variants if variant.kind != "hyde"]


async def _guarded(
    run: _Run,
    channel: str,
    variant: int,
    stage: str,
    weight: float,
    call: Callable[[], Awaitable[list[Candidate]]],
) -> RankedList | None:
    """Runs one channel call in a savepoint, tracing it and absorbing any failure.

    Args:
        run: The run's state.
        channel: The channel kind, for the trace and the ranked list.
        variant: The variant index, for the trace and the ranked list.
        stage: ``search`` or ``expansion``.
        weight: The channel spec's fusion weight.
        call: Zero-argument coroutine function doing the channel's work.

    Returns:
        The ranked list, or ``None`` when the call failed.
    """
    started = time.perf_counter()
    try:
        async with run.ctx.db.begin_nested():
            found = await call()
    except Exception as error:
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        reason = _error_text(error)
        logger.warning("channel %s (variant %d) failed: %s", channel, variant, reason)
        if stage == "search":
            run.search_errors.append(error)
        run.traces.append(ChannelTrace(channel, variant, stage, 0, elapsed, reason))
        await run.emit(
            "degraded",
            {"stage": stage, "channel": channel, "variant": variant, "reason": reason},
        )
        return None
    elapsed = round((time.perf_counter() - started) * 1000, 2)
    run.traces.append(ChannelTrace(channel, variant, stage, len(found), elapsed))
    return RankedList(channel, variant, weight, tuple(found))


async def _rerank(
    run: _Run,
    config: PipelineConfig,
    question: str,
    pool: list[Candidate],
    llm: LLMConfig | None,
) -> tuple[list[Candidate], bool, tuple[dict[str, Any], ...]]:
    """Reranks the pool, falling back to the fused order when the reranker fails.

    Returns:
        The reranked candidates, whether the reranker degraded, and the raw
        provider calls it made (including those made before a failure). With
        ``kind="none"`` the pool is returned whole.
    """
    settings = config.rerank
    if settings.kind == "none":
        return pool, False, ()
    reranker = None
    try:
        reranker = get_reranker(settings.kind, llm=llm)
        reranked = await reranker.rerank(question, pool, settings.top_n)
        return reranked, False, _calls_of(reranker)
    except Exception as error:
        reason = _error_text(error)
        logger.warning("reranker %s failed: %s", settings.kind, reason)
        await run.emit("degraded", {"stage": "rerank", "reranker": settings.kind, "reason": reason})
        return pool[: settings.top_n], True, _calls_of(reranker)


def _calls_of(reranker: Any) -> tuple[dict[str, Any], ...]:
    """The reranker's recorded provider calls as plain dicts, tolerating a bare reranker."""
    return tuple(call.to_dict() for call in getattr(reranker, "calls", ()))


async def retrieve(
    config: PipelineConfig,
    question: str,
    *,
    ctx: RetrievalContext,
    history: Sequence[HistoryMessage] = (),
    llm: LLMConfig | None = None,
) -> RetrievalResult:
    """Turns a question into a ranked, diversified candidate list.

    Channels run one at a time on ``ctx.db``; each call is wrapped in a
    savepoint so a failing channel leaves the others usable. Failures of a
    channel, a query rewrite or the reranker are recorded in the trace, emitted
    as ``degraded`` events, and otherwise absorbed, with one exception: when
    every searching channel fails there is no partial result to fall back to,
    and the first channel's error is raised.

    Args:
        config: Which transforms, channels, fusion, reranker and caps to use.
        question: The user's question as typed.
        ctx: The repository, session, query embedder and emitter.
        history: Prior chat messages, oldest first, for the condense step.
        llm: The caller's generation credential for query rewrites and the
            reranker; ``None`` uses the server's free-tier credential if any.

    Returns:
        The final candidates, the fused pool they came from, and the trace.

    Raises:
        Exception: The first channel's own error, when every searching channel
            failed.
    """
    run = _Run(ctx)

    standalone, variants = await build_variants(
        question, history, config.query, llm=llm, emit=run.emit
    )

    searching = [spec for spec in config.channels if spec.kind not in EXPANSION_CHANNELS]
    expanding = [spec for spec in config.channels if spec.kind in EXPANSION_CHANNELS]

    dense_texts = [
        variant.text
        for spec in searching
        if spec.kind in _DENSE_USING
        for variant in _variants_for(spec.kind, variants)
    ]
    if dense_texts:
        try:
            await ctx.prefetch_embeddings(dense_texts)
        except Exception as error:
            # The dense channels retry per variant and record their own failure.
            logger.warning("embedding the query variants failed: %s", _error_text(error))

    lists: list[RankedList] = []
    for spec in searching:
        for variant in _variants_for(spec.kind, variants):

            async def search(spec=spec, variant=variant) -> list[Candidate]:
                return await get_channel(spec.kind).search(ctx, variant, spec)

            ranked = await _guarded(run, spec.kind, variant.index, "search", spec.weight, search)
            if ranked is not None:
                lists.append(ranked)

    if not lists and run.search_errors:
        # Every search failed, so there is nothing to degrade to. Returning an
        # empty result would read as "nothing in this repository matches" and
        # hide an outage such as a failed embedding call; the caller's error
        # handling should see the real error instead.
        raise run.search_errors[0]

    fused = fuse(lists, method=config.fusion, rrf_k=config.rrf_k)

    if expanding:
        seeds = fused
        expansion_lists: list[RankedList] = []
        for spec in expanding:

            async def expand(spec=spec) -> list[Candidate]:
                return await get_expansion_channel(spec.kind).expand(ctx, seeds, spec)

            ranked = await _guarded(run, spec.kind, 0, "expansion", spec.weight, expand)
            if ranked is not None:
                expansion_lists.append(ranked)
        if expansion_lists:
            fused = reciprocal_rank_fusion([*lists, *expansion_lists], rrf_k=config.rrf_k)

    pool = fused[: config.rerank.candidate_pool]
    reranked, reranker_degraded, rerank_calls = await _rerank(run, config, standalone, pool, llm)
    final = diversify(reranked, config.diversify)

    return RetrievalResult(
        question=standalone,
        variants=tuple(variants),
        candidates=tuple(final),
        pool=tuple(pool),
        trace=RetrievalTrace(
            channels=tuple(run.traces),
            reranker=config.rerank.kind,
            reranker_degraded=reranker_degraded,
            degraded=tuple(run.degraded),
            config_hash=config.config_hash(),
            rerank_calls=rerank_calls,
        ),
    )
