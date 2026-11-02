"""Commits and pull requests, found by meaning and by keyword together."""

from __future__ import annotations

from uuid import UUID

from app.models import Embedding
from app.services.retrieval.candidate import Candidate, QueryVariant
from app.services.retrieval.channels._common import HISTORY_SOURCE_TYPES
from app.services.retrieval.channels.base import RetrievalContext
from app.services.retrieval.channels.dense import dense_rows
from app.services.retrieval.channels.lexical import lexical_rows
from app.services.retrieval.config import ChannelSpec, HistoryChannel
from app.services.retrieval.keys import candidate_from_embedding
from app.services.retrieval.resolve import resolve_sources

# The rank offset of the fusion inside this channel. Fixed, not configurable: it
# only merges the channel's own two lists, and the pipeline's fusion has its own.
INTERNAL_RRF_K = 60


class HistorySearch:
    """Dense and lexical search restricted to commits and pull requests."""

    kind = "history"

    async def search(
        self, ctx: RetrievalContext, variant: QueryVariant, spec: ChannelSpec
    ) -> list[Candidate]:
        """Returns up to ``spec.k`` commits and pull requests, best first.

        Both halves search only history chunks. Their lists are merged by
        reciprocal rank fusion, so a chunk found by both rises above one found by
        either alone. The lexical half is skipped for a ``hyde`` variant. The
        reported score is the fused score.

        Raises:
            TypeError: When ``spec`` is not a :class:`HistoryChannel`.
        """
        if not isinstance(spec, HistoryChannel):
            raise TypeError(f"history channel given a {type(spec).__name__}")

        vector = await ctx.embedding(variant.text)
        dense = await dense_rows(
            ctx.db,
            ctx.repository_id,
            vector,
            k=spec.k,
            max_distance=spec.max_distance,
            source_types=HISTORY_SOURCE_TYPES,
        )
        lexical = (
            []
            if variant.kind == "hyde"
            else await lexical_rows(
                ctx.db,
                ctx.repository_id,
                variant.text,
                k=spec.k,
                source_types=HISTORY_SOURCE_TYPES,
            )
        )

        unique: dict[UUID, Embedding] = {}
        for embedding, _ in (*dense, *lexical):
            unique.setdefault(embedding.id, embedding)
        embeddings = list(unique.values())
        references = dict(
            zip(unique, await resolve_sources(ctx.db, embeddings), strict=True),
        )

        # Fuse on the citation key so two rows naming the same thing count once.
        scores: dict[str, float] = {}
        winners: dict[str, Embedding] = {}
        for rows in (dense, lexical):
            for rank, (embedding, _) in enumerate(rows, start=1):
                candidate = candidate_from_embedding(
                    embedding,
                    references[embedding.id],
                    channel=self.kind,
                    variant=variant.index,
                    rank=rank,
                    raw_score=None,
                )
                scores[candidate.key] = scores.get(candidate.key, 0.0) + 1.0 / (
                    INTERNAL_RRF_K + rank
                )
                winners.setdefault(candidate.key, embedding)

        ordered = sorted(scores, key=lambda key: (-scores[key], key))[: spec.k]
        return [
            candidate_from_embedding(
                winners[key],
                references[winners[key].id],
                channel=self.kind,
                variant=variant.index,
                rank=rank,
                raw_score=scores[key],
            )
            for rank, key in enumerate(ordered, start=1)
        ]
