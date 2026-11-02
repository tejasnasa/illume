"""Merging the ranked lists of every channel and query variant into one.

Each list is one ``(channel, variant)`` pair. Reciprocal rank fusion scores a
candidate by how high every list ranked it, so it needs only ranks and not the
channels' incomparable raw scores.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

from app.services.retrieval.candidate import Candidate, ChannelHit


@dataclass(frozen=True)
class RankedList:
    """One channel's results for one query variant.

    Attributes:
        channel: The channel kind that produced the list.
        variant: The query variant index it searched with.
        weight: The channel spec's weight. Variants of one channel share it.
        candidates: The results, best first; position in this tuple is the rank.
    """

    channel: str
    variant: int
    weight: float
    candidates: tuple[Candidate, ...]


def rrf_score(weight: float, rank: int, rrf_k: int) -> float:
    """One list's contribution to a candidate: ``weight / (rrf_k + rank)``."""
    return weight / (rrf_k + rank)


def reciprocal_rank_fusion(lists: Sequence[RankedList], *, rrf_k: int) -> list[Candidate]:
    """Merges ranked lists by candidate key with weighted reciprocal rank fusion.

    ``score(c) = sum(weight(list) / (rrf_k + rank_in_list(c)))`` over the lists
    that contain ``c``, with ranks counted from 1 by position. A key repeated
    inside one list counts once, at its first position.

    The merged candidate takes its ``reference``, ``text``, ``source_id``,
    ``file_id`` and ``provenance`` from its best-ranked appearance, ties going to
    the channel kind and then the variant index in ascending order. Its
    ``channel_hits`` are the union of every appearance's hits, ordered by
    channel, variant and rank, and ``fused_score`` is set. Output is sorted by
    score descending with ties broken by key, so equal inputs give equal outputs.

    Args:
        lists: The ranked lists, in any order.
        rrf_k: The rank offset; larger values flatten the difference between ranks.

    Returns:
        The merged candidates, best first.
    """
    # Lists are visited in a fixed order so float sums do not depend on input order.
    ordered = sorted(lists, key=lambda ranked: (ranked.channel, ranked.variant))

    scores: dict[str, float] = {}
    best: dict[str, tuple[tuple[int, str, int], Candidate]] = {}
    hits: dict[str, set[ChannelHit]] = {}

    for ranked in ordered:
        seen: set[str] = set()
        for position, candidate in enumerate(ranked.candidates, start=1):
            if candidate.key in seen:
                continue
            seen.add(candidate.key)
            scores[candidate.key] = scores.get(candidate.key, 0.0) + rrf_score(
                ranked.weight, position, rrf_k
            )
            order = (position, ranked.channel, ranked.variant)
            if candidate.key not in best or order < best[candidate.key][0]:
                best[candidate.key] = (order, candidate)
            hits.setdefault(candidate.key, set()).update(candidate.channel_hits)

    merged = [
        replace(
            best[key][1],
            channel_hits=tuple(
                sorted(hits[key], key=lambda hit: (hit.channel, hit.variant, hit.rank))
            ),
            fused_score=score,
        )
        for key, score in scores.items()
    ]
    merged.sort(key=lambda candidate: (-(candidate.fused_score or 0.0), candidate.key))
    return merged


def single_list(lists: Sequence[RankedList]) -> list[Candidate]:
    """The only list, unchanged and without a fused score.

    No lists (the one channel failed) gives an empty result.

    Raises:
        ValueError: When there is more than one list.
    """
    if len(lists) > 1:
        raise ValueError(f"fusion 'none' takes a single ranked list, got {len(lists)}")
    return list(lists[0].candidates) if lists else []


def fuse(
    lists: Sequence[RankedList], *, method: Literal["none", "rrf"], rrf_k: int
) -> list[Candidate]:
    """Applies the configured fusion method to the ranked lists.

    Args:
        lists: The ranked lists.
        method: ``rrf`` merges them; ``none`` passes a single list through.
        rrf_k: The rank offset for ``rrf``.
    """
    if method == "none":
        return single_list(lists)
    return reciprocal_rank_fusion(lists, rrf_k=rrf_k)
