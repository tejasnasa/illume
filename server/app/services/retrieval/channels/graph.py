"""Files one import away from the strongest files an earlier pass found."""

from __future__ import annotations

import math
from collections.abc import Sequence
from uuid import UUID

from app.services.file_graph import query_neighbours_async
from app.services.retrieval.candidate import Candidate
from app.services.retrieval.channels._files import file_candidates, seed_files
from app.services.retrieval.channels.base import RetrievalContext
from app.services.retrieval.config import ChannelSpec, GraphChannel

# How much a heavier connection adds: the multiplier is ``1 + 0.1 * ln(1 + weight)``,
# so ten collapsed dependencies lift a score by about a quarter.
WEIGHT_GAIN = 0.1


def neighbour_score(seed_score: float, decay: float, weight: int) -> float:
    """What a neighbour inherits from one seed over an edge of ``weight``."""
    return seed_score * decay * (1.0 + WEIGHT_GAIN * math.log1p(weight))


class GraphExpansion:
    """Importers and importees of the top seed files, scored by seed strength."""

    kind = "graph"

    async def expand(
        self, ctx: RetrievalContext, seeds: Sequence[Candidate], spec: ChannelSpec
    ) -> list[Candidate]:
        """Returns up to ``spec.k`` files adjacent to the seeds in the import graph.

        A neighbour reached from several seeds keeps its highest score. The
        seed files themselves are never returned.

        Raises:
            TypeError: When ``spec`` is not a :class:`GraphChannel`.
        """
        if not isinstance(spec, GraphChannel):
            raise TypeError(f"graph channel given a {type(spec).__name__}")
        seed_scores = seed_files(seeds, spec.seeds)
        if not seed_scores:
            return []
        edges = await query_neighbours_async(ctx.db, ctx.repository_id, list(seed_scores))
        scores: dict[UUID, float] = {}
        for seed_id, neighbour_id, weight in edges:
            if neighbour_id in seed_scores:
                continue
            score = neighbour_score(seed_scores[seed_id], spec.decay, weight)
            if score > scores.get(neighbour_id, float("-inf")):
                scores[neighbour_id] = score
        return await file_candidates(ctx.db, ctx.repository_id, scores, k=spec.k, channel=self.kind)
