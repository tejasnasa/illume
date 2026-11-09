"""The values that flow through the retrieval pipeline.

A channel turns a query variant into candidates, fusion merges candidates that
name the same thing, and a reranker reorders them. Every stage works on the
same frozen :class:`Candidate`, so a result can always say which channel found
it, at what rank, and with what raw score.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.services.retrieval.resolve import SourceReference

SourceType = Literal["symbol", "file", "commit", "pull_request", "document"]

VariantKind = Literal["original", "condensed", "multi_query", "hyde"]

Provenance = Literal["repo", "history"]


@dataclass(frozen=True)
class QueryVariant:
    """One phrasing of the question that the channels search with.

    Attributes:
        text: The text to search for.
        kind: How the text was produced. ``hyde`` text is a hypothetical code
            snippet rather than a question, which is why only the dense channel
            searches with it.
        index: Position among the variants of one question. Fusion treats each
            ``(channel, index)`` pair as its own ranked list.
    """

    text: str
    kind: VariantKind = "original"
    index: int = 0


def query_payload(variants: Sequence[QueryVariant]) -> list[dict[str, str]]:
    """The variants a retrieval searched with, in the shape its event reports them."""
    return [{"text": variant.text, "kind": variant.kind} for variant in variants]


@dataclass(frozen=True)
class ChannelHit:
    """Where one channel ranked one candidate.

    Attributes:
        channel: The channel kind that produced the hit.
        variant: The :attr:`QueryVariant.index` the channel searched with.
        rank: One-based position in that channel's list.
        raw_score: The channel's own score (a distance, a ``ts_rank_cd``, a
            similarity). Scales differ between channels, which is why fusion
            uses only ``rank``; the score is kept for analysis.
    """

    channel: str
    variant: int
    rank: int
    raw_score: float | None = None


@dataclass(frozen=True)
class Candidate:
    """A retrievable thing, with every channel hit that found it.

    The key identifies the thing rather than the chunk, so the same function
    found by two channels is one candidate with two hits once fused.

    Attributes:
        key: The stable citation key, see :mod:`app.services.retrieval.citations`.
        reference: The citation details shown to the user.
        text: What the model sees for this candidate.
        source_id: The row the candidate came from, when it has one.
        file_id: The owning file, for symbol and file candidates. Graph and
            co-change expansion seed from this.
        channel_hits: One entry per (channel, variant) that returned it.
        fused_score: Set by fusion.
        rerank_score: Set by a reranker.
        provenance: ``history`` for commits and pull requests, ``repo`` for
            everything read from the code.
    """

    key: str
    reference: SourceReference
    text: str
    source_id: UUID | None = None
    file_id: UUID | None = None
    channel_hits: tuple[ChannelHit, ...] = ()
    fused_score: float | None = None
    rerank_score: float | None = None
    provenance: Provenance = "repo"

    @property
    def source_type(self) -> str:
        """The kind of source, taken from the reference."""
        return self.reference.source_type

    @property
    def file_path(self) -> str | None:
        """The owning file's path, when the source has one."""
        return self.reference.file_path
