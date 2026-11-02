"""Pieces shared by more than one retrieval channel."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Embedding
from app.services.retrieval.candidate import Candidate, QueryVariant
from app.services.retrieval.keys import candidate_from_embedding
from app.services.retrieval.resolve import resolve_sources

# The kinds that are embedded and trigram-indexed. The partial indexes on
# ``ast_symbols`` carry this exact predicate, and a query only uses them when it
# repeats it verbatim, so every symbol query interpolates this one string.
SEARCHABLE_KINDS_SQL = "kind IN ('function', 'class', 'method')"

HISTORY_SOURCE_TYPES: tuple[str, ...] = ("commit", "pull_request")


async def embedding_candidates(
    db: AsyncSession,
    rows: Sequence[tuple[Embedding, float]],
    variant: QueryVariant,
    channel: str,
) -> list[Candidate]:
    """Resolves rows in one batch and numbers them from 1 in the order given.

    Args:
        db: The request's session.
        rows: ``(embedding, score)`` pairs, best first.
        variant: The query variant that produced the rows.
        channel: The channel kind to record on each hit.
    """
    references = await resolve_sources(db, [embedding for embedding, _ in rows])
    return [
        candidate_from_embedding(
            embedding,
            reference,
            channel=channel,
            variant=variant.index,
            rank=rank,
            raw_score=score,
        )
        for rank, ((embedding, score), reference) in enumerate(
            zip(rows, references, strict=True), start=1
        )
    ]
