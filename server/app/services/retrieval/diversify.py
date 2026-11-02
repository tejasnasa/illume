"""Narrowing a ranked list so no single source type crowds out the rest."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from app.services.retrieval.candidate import Candidate
from app.services.retrieval.config import DiversifyConfig


def diversify(candidates: Sequence[Candidate], config: DiversifyConfig) -> list[Candidate]:
    """Selects up to ``config.total`` candidates while respecting per-type caps.

    Pass 1 walks the list in order and takes a candidate while its source type is
    under its cap (types without a cap use ``config.other``). Pass 2 backfills any
    remaining slots with the next-best candidates regardless of type, so the caps
    are soft: a list of one type can exceed its cap rather than come back short.
    The selection keeps pass 1 picks first, then the backfill, in list order.

    Args:
        candidates: The ranked list, best first.
        config: The total and the per-type caps.

    Returns:
        The selected candidates, a new list.
    """
    caps = config.caps()
    counts: defaultdict[str, int] = defaultdict(int)
    selected: list[Candidate] = []
    taken: set[int] = set()

    for index, candidate in enumerate(candidates):
        source_type = candidate.source_type
        if counts[source_type] < caps.get(source_type, config.other):
            selected.append(candidate)
            taken.add(index)
            counts[source_type] += 1
        if len(selected) == config.total:
            return selected

    for index, candidate in enumerate(candidates):
        if index not in taken:
            selected.append(candidate)
        if len(selected) == config.total:
            return selected

    return selected
