"""Files that tend to change in the same commits as the strongest files found."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.retrieval.candidate import Candidate
from app.services.retrieval.channels._files import file_candidates, seed_files
from app.services.retrieval.channels.base import RetrievalContext
from app.services.retrieval.config import ChannelSpec, CochangeChannel

# Each pair is stored once, so a file's partners are the rows where it is either
# column. The second select swaps the columns so both shapes read the same way.
_PARTNERS = text(
    """
    SELECT file_a_id AS seed_id, file_b_id AS partner_id, together, jaccard
    FROM file_cochange
    WHERE repository_id = :repo AND file_a_id = ANY(:ids)
    UNION ALL
    SELECT file_b_id, file_a_id, together, jaccard
    FROM file_cochange
    WHERE repository_id = :repo AND file_b_id = ANY(:ids)
    """
)

_PARTNERS_OF_ONE = text(
    """
    SELECT f.path, p.together, p.jaccard
    FROM (
        SELECT file_b_id AS partner_id, together, jaccard FROM file_cochange
        WHERE repository_id = :repo AND file_a_id = :file
        UNION ALL
        SELECT file_a_id, together, jaccard FROM file_cochange
        WHERE repository_id = :repo AND file_b_id = :file
    ) p
    JOIN files f ON f.id = p.partner_id AND f.repository_id = :repo
    ORDER BY p.jaccard DESC, p.together DESC, f.path
    LIMIT :limit
    """
)


@dataclass(frozen=True)
class CochangedFile:
    """One file that changes with another.

    Attributes:
        path: The partner's repository-relative path.
        together: Commits that touched both files.
        jaccard: Share of either file's commits that touched both.
    """

    path: str
    together: int
    jaccard: float


async def cochanged_files(
    db: AsyncSession, repository_id: UUID, file_id: UUID, limit: int
) -> list[CochangedFile]:
    """The files that most often change with ``file_id``, strongest first.

    Ordered by jaccard descending, then ``together``, then path. Only files of
    ``repository_id`` are returned.
    """
    rows = await db.execute(
        _PARTNERS_OF_ONE, {"repo": repository_id, "file": file_id, "limit": limit}
    )
    return [CochangedFile(row.path, row.together, row.jaccard) for row in rows]


class CochangeExpansion:
    """Partners of the top seed files in ``file_cochange``, scored by seed strength."""

    kind = "cochange"

    async def expand(
        self, ctx: RetrievalContext, seeds: Sequence[Candidate], spec: ChannelSpec
    ) -> list[Candidate]:
        """Returns up to ``spec.k`` files that change with the seeds.

        The score is the seed's score times the pair's jaccard; a partner of
        several seeds keeps its highest. The seed files are never returned.

        Raises:
            TypeError: When ``spec`` is not a :class:`CochangeChannel`.
        """
        if not isinstance(spec, CochangeChannel):
            raise TypeError(f"cochange channel given a {type(spec).__name__}")
        seed_scores = seed_files(seeds, spec.seeds)
        if not seed_scores:
            return []
        rows = await ctx.db.execute(
            _PARTNERS, {"repo": ctx.repository_id, "ids": list(seed_scores)}
        )
        scores: dict[UUID, float] = {}
        for row in rows:
            if row.partner_id in seed_scores:
                continue
            score = seed_scores[row.seed_id] * row.jaccard
            if score > scores.get(row.partner_id, float("-inf")):
                scores[row.partner_id] = score
        return await file_candidates(ctx.db, ctx.repository_id, scores, k=spec.k, channel=self.kind)
