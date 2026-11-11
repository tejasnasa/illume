"""Commits and pull requests, found by meaning and by keyword together.

When the question names a time span ("over the last two weeks"), the search is
restricted to commits authored, and pull requests merged, inside it.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import ColumnElement, and_, or_, select

from app.models import Commit, Embedding, PullRequest
from app.services.retrieval.candidate import Candidate, QueryVariant
from app.services.retrieval.channels._common import HISTORY_SOURCE_TYPES
from app.services.retrieval.channels.base import RetrievalContext
from app.services.retrieval.channels.dense import dense_rows
from app.services.retrieval.channels.lexical import lexical_rows
from app.services.retrieval.config import ChannelSpec, HistoryChannel
from app.services.retrieval.dates import DateRange
from app.services.retrieval.keys import candidate_from_embedding
from app.services.retrieval.resolve import resolve_sources


def date_conditions(repository_id: UUID, date_range: DateRange | None) -> list[ColumnElement[bool]]:
    """The SQL conditions that keep only history inside ``date_range``.

    A commit counts by its authored date and a pull request by its merge date;
    a pull request that was never merged has no date and is left out.
    """
    if date_range is None or (date_range.since is None and date_range.until is None):
        return []
    commits = select(Commit.id).where(Commit.repository_id == repository_id)
    pulls = select(PullRequest.id).where(PullRequest.repository_id == repository_id)
    if date_range.since is not None:
        commits = commits.where(Commit.authored_at >= date_range.since)
        pulls = pulls.where(PullRequest.merged_at >= date_range.since)
    if date_range.until is not None:
        commits = commits.where(Commit.authored_at <= date_range.until)
        pulls = pulls.where(PullRequest.merged_at <= date_range.until)
    return [
        or_(
            and_(Embedding.source_type == "commit", Embedding.source_id.in_(commits)),
            and_(Embedding.source_type == "pull_request", Embedding.source_id.in_(pulls)),
        )
    ]


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
        reported score is the fused score. When the context carries a date range,
        only history inside it is searched.

        Raises:
            TypeError: When ``spec`` is not a :class:`HistoryChannel`.
        """
        if not isinstance(spec, HistoryChannel):
            raise TypeError(f"history channel given a {type(spec).__name__}")

        vector = await ctx.embedding(variant.text)
        within = date_conditions(ctx.repository_id, ctx.date_range)
        dense = await dense_rows(
            ctx.db,
            ctx.repository_id,
            vector,
            k=spec.k,
            max_distance=spec.max_distance,
            source_types=HISTORY_SOURCE_TYPES,
            where=within,
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
                where=within,
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
