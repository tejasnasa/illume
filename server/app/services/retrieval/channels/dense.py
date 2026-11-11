"""Vector similarity over every embedded chunk."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.models import Embedding
from app.services.retrieval.candidate import Candidate, QueryVariant
from app.services.retrieval.channels._common import embedding_candidates
from app.services.retrieval.channels.base import RetrievalContext
from app.services.retrieval.config import ChannelSpec, DenseChannel
from app.services.retrieval.vector import prepare_filtered_vector_search


async def dense_rows(
    db: AsyncSession,
    repository_id: UUID,
    query_vector: Sequence[float],
    *,
    k: int,
    max_distance: float,
    source_types: Sequence[str] | None = None,
    where: Sequence[ColumnElement[bool]] = (),
) -> list[tuple[Embedding, float]]:
    """The nearest chunks of one repository, with their cosine distances.

    Rows at or beyond ``max_distance`` are dropped before ranking, so a weak
    match never takes a slot. The order is by distance alone, which is what lets
    the HNSW index serve it; ties are left to the index.

    Args:
        db: The request's session.
        repository_id: The only repository searched.
        query_vector: The embedded query.
        k: How many rows to return at most.
        max_distance: Exclusive upper bound on cosine distance.
        source_types: When given, only chunks of these types are searched.
        where: Further conditions every returned chunk must meet.

    Returns:
        ``(row, distance)`` pairs, nearest first. The stored vector is not loaded.
    """
    # The repository filter runs after the index walk, so pgvector is told to
    # keep scanning until enough rows survive it.
    await prepare_filtered_vector_search(db)
    distance = Embedding.embedding.cosine_distance(list(query_vector))
    statement = (
        select(Embedding, distance.label("distance"))
        .options(defer(Embedding.embedding))
        .where(Embedding.repository_id == repository_id, distance < max_distance)
    )
    if source_types is not None:
        statement = statement.where(Embedding.source_type.in_(list(source_types)))
    for condition in where:
        statement = statement.where(condition)
    rows = (await db.execute(statement.order_by(distance).limit(k))).all()
    return [(row[0], float(row[1])) for row in rows]


class DenseSearch:
    """Nearest chunks by cosine distance, for any variant kind including ``hyde``."""

    kind = "dense"

    async def search(
        self, ctx: RetrievalContext, variant: QueryVariant, spec: ChannelSpec
    ) -> list[Candidate]:
        """Returns up to ``spec.k`` chunks within ``spec.max_distance``, nearest first.

        Raises:
            TypeError: When ``spec`` is not a :class:`DenseChannel`.
        """
        if not isinstance(spec, DenseChannel):
            raise TypeError(f"dense channel given a {type(spec).__name__}")
        vector = await ctx.embedding(variant.text)
        rows = await dense_rows(
            ctx.db,
            ctx.repository_id,
            vector,
            k=spec.k,
            max_distance=spec.max_distance,
        )
        return await embedding_candidates(ctx.db, rows, variant, self.kind)
