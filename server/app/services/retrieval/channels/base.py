"""The contract every retrieval channel implements, and what it is handed.

A channel searches one way (vectors, full-text, symbol names, grep, the import
graph, co-change, history) and returns candidates ranked best first, each
carrying one :class:`~app.services.retrieval.candidate.ChannelHit` that records
the channel, the query variant and the rank. Fusion merges candidates from
every channel by key.

**One session, one channel at a time.** An ``AsyncSession`` cannot be used by
two coroutines at once, and the request's session is the one that sees the
request's data (and, in tests, the fixture's uncommitted rows). The context
therefore carries that single session, and the pipeline awaits channels one
after another rather than gathering them. Work that is safe to overlap, such
as embedding every query variant, happens before the channels run. Code that
needs real concurrency, like parallel agent tool calls, builds a separate
context per task with its own session.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.retrieval.candidate import Candidate, QueryVariant
from app.services.retrieval.config import ChannelSpec

Embedder = Callable[[Sequence[str]], Awaitable[list[list[float]]]]
"""Embeds a batch of texts, one vector per text, in input order."""

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]
"""Publishes one named event with a JSON-serialisable payload."""


async def _no_emit(event: str, payload: dict[str, Any]) -> None:
    """The default emitter, for callers that do not stream progress."""


@dataclass
class RetrievalContext:
    """Everything a channel needs that is not the query itself.

    Attributes:
        repository_id: The only repository any channel may read.
        db: The request's session. Never shared between concurrent tasks.
        embed: How query text becomes vectors. Production passes the operator
            key's embedding call; tests pass a deterministic fake.
        emit: Where progress and degradation events go.
    """

    repository_id: UUID
    db: AsyncSession
    embed: Embedder
    emit: Emit = _no_emit
    _vectors: dict[str, list[float]] = field(default_factory=dict, repr=False)

    async def prefetch_embeddings(self, texts: Sequence[str]) -> None:
        """Embeds every text not yet cached, in one batched call."""
        missing = list(dict.fromkeys(text for text in texts if text not in self._vectors))
        if not missing:
            return
        vectors = await self.embed(missing)
        if len(vectors) != len(missing):
            raise ValueError(f"embedder returned {len(vectors)} vectors for {len(missing)} texts")
        self._vectors.update(zip(missing, vectors, strict=True))

    async def embedding(self, text: str) -> list[float]:
        """The vector for one text, embedding it on first use."""
        if text not in self._vectors:
            await self.prefetch_embeddings([text])
        return self._vectors[text]


class Channel(Protocol):
    """One way of finding candidates."""

    kind: str

    async def search(
        self,
        ctx: RetrievalContext,
        variant: QueryVariant,
        spec: ChannelSpec,
    ) -> list[Candidate]:
        """Returns up to ``spec.k`` candidates for one variant, best first.

        Each candidate carries exactly one hit for this channel and variant,
        with ranks starting at 1. Only rows of ``ctx.repository_id`` may be
        returned.
        """
        ...


class ExpansionChannel(Protocol):
    """A channel that grows the files a first pass ranked highest.

    Graph and co-change do not search the question. They take the strongest
    files from an earlier fusion and return the files structurally close to
    them, scored by how strong the seed was.
    """

    kind: str

    async def expand(
        self,
        ctx: RetrievalContext,
        seeds: Sequence[Candidate],
        spec: ChannelSpec,
    ) -> list[Candidate]:
        """Returns up to ``spec.k`` file candidates near the seeds, best first.

        ``seeds`` is the fused list, best first. The first ``spec.seeds``
        distinct files in it are expanded; candidates without a ``file_id``
        are skipped. A seed file is never returned. Hits use ``variant=0``
        with ranks counting up from 1, and only rows of
        ``ctx.repository_id`` may be returned.
        """
        ...
