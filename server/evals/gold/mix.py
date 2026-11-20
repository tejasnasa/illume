"""Choose each repository's questions to match its configured mix.

A repository contributes a set number of change questions and explain questions. Change items
are chosen cluster by cluster, ordered by a hash of the seed and the cluster so the choice does
not depend on input order or random state. Explain items are chosen the same way, one by one.
A pool smaller than the request is not an error: the shortfall is returned so the build can
report it.
"""

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from evals.gold.schema import GoldItem

ANCHOR_TEMPLATE = "changeset.anchor"
UNANSWERABLE_TAG = "unanswerable"


@dataclass(frozen=True)
class Selection:
    """The items chosen for one kind.

    Attributes:
        items: The chosen items, sorted by id.
        requested: How many the mix asked for.
        available: How many the pool held after filtering.
    """

    items: tuple[GoldItem, ...]
    requested: int
    available: int

    @property
    def shortfall(self) -> int:
        """How many fewer than requested were found; zero when the request was met."""
        return max(0, self.requested - len(self.items))


def _rank(seed: int, unit: str) -> tuple[str, str]:
    return hashlib.sha256(f"{seed}:{unit}".encode()).hexdigest(), unit


def select_change_items(
    items: Iterable[GoldItem], count: int, *, seed: int, include_anchor: bool = False
) -> Selection:
    """Choose up to ``count`` change items, whole clusters at a time.

    Args:
        items: Candidate change-set items.
        count: How many to take.
        seed: The ordering seed.
        include_anchor: Keep the anchor variants. By default only the blind variant is kept,
            so ``count`` items are ``count`` distinct pull requests.

    Returns:
        The selection. A cluster that would pass ``count`` is skipped, so with the anchor
        variants on a selection can fall one short.
    """
    pool = [
        item
        for item in items
        if item.family == "changeset" and (include_anchor or item.template != ANCHOR_TEMPLATE)
    ]
    clusters: dict[str, list[GoldItem]] = defaultdict(list)
    for item in pool:
        clusters[item.cluster or item.id].append(item)
    chosen: list[GoldItem] = []
    for unit in sorted(clusters, key=lambda name: _rank(seed, name)):
        members = clusters[unit]
        if len(chosen) + len(members) <= count:
            chosen.extend(members)
    return Selection(tuple(sorted(chosen, key=lambda i: i.id)), count, len(pool))


def select_explain_items(
    items: Iterable[GoldItem], count: int, *, seed: int, include_unanswerable: bool = False
) -> Selection:
    """Choose up to ``count`` hand items.

    Args:
        items: Candidate hand items.
        count: How many to take.
        seed: The ordering seed.
        include_unanswerable: Keep the items tagged ``unanswerable``; left out by default.

    Returns:
        The selection.
    """
    pool = [
        item
        for item in items
        if item.family == "hand" and (include_unanswerable or UNANSWERABLE_TAG not in item.tags)
    ]
    ordered = sorted(pool, key=lambda item: _rank(seed, item.id))[:count]
    return Selection(tuple(sorted(ordered, key=lambda i: i.id)), count, len(pool))


__all__ = ["Selection", "select_change_items", "select_explain_items"]
