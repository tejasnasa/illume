"""Turning stored rows into candidates with their citation keys.

Every channel that reads ``embeddings`` builds its candidates here, so a chunk
found by two channels always gets the same key and fusion merges it.
"""

from __future__ import annotations

import hashlib

from app.models import Embedding
from app.services.retrieval.candidate import Candidate, ChannelHit, Provenance
from app.services.retrieval.citations import (
    code_key,
    commit_key,
    document_key,
    pull_request_key,
)
from app.services.retrieval.resolve import SourceReference

_HISTORY_TYPES = frozenset({"commit", "pull_request"})


def readme_heading(chunk_text: str) -> str:
    """The ``##`` heading of a README chunk, or ``""`` for the opening section.

    README chunks are rendered as ``# README`` followed by the section, so the
    heading, when there is one, is the first line after that marker.
    """
    lines = [line.strip() for line in chunk_text.splitlines() if line.strip()]
    if lines and lines[0] == "# README":
        lines = lines[1:]
    if lines and lines[0].startswith("##"):
        return lines[0].lstrip("#").strip()
    return ""


def key_for(reference: SourceReference) -> str:
    """The citation key for a resolved source.

    A symbol without a known line range falls back to its file's key; a source
    missing the field its key needs (a deleted commit or pull request row)
    falls back to a key on its chunk text so it still has a stable identity.

    Raises:
        ValueError: When a symbol or file source has no path at all.
    """
    source_type = reference.source_type
    if source_type == "symbol":
        if not reference.file_path:
            raise ValueError("a symbol source needs a file path for its key")
        if reference.start_line and reference.end_line:
            return code_key(reference.file_path, reference.start_line, reference.end_line)
        return code_key(reference.file_path)
    if source_type == "file":
        if not reference.file_path:
            raise ValueError("a file source needs a file path for its key")
        return code_key(reference.file_path)
    if source_type == "commit" and reference.commit_hash:
        return commit_key(reference.commit_hash)
    if source_type == "pull_request" and reference.pr_number:
        return pull_request_key(reference.pr_number)
    if source_type == "document":
        return document_key(readme_heading(reference.chunk_text))
    # ``hash()`` is salted per process, so a content digest is what keeps this
    # key the same across runs.
    digest = hashlib.sha256(reference.chunk_text.encode("utf-8")).hexdigest()[:16]
    return f"X:{source_type}:{digest}"


def provenance_for(source_type: str) -> Provenance:
    """``history`` for commits and pull requests, ``repo`` for everything else."""
    return "history" if source_type in _HISTORY_TYPES else "repo"


def candidate_from_embedding(
    embedding: Embedding,
    reference: SourceReference,
    *,
    channel: str,
    variant: int,
    rank: int,
    raw_score: float | None,
) -> Candidate:
    """A candidate for one embedding row, carrying a single channel hit.

    Args:
        embedding: The row that matched.
        reference: The row resolved by ``resolve_sources``.
        channel: The channel kind reporting the hit.
        variant: The query variant index searched.
        rank: One-based position in the channel's list.
        raw_score: The channel's own score for the row.
    """
    return Candidate(
        key=key_for(reference),
        reference=reference,
        text=embedding.chunk_text,
        source_id=embedding.source_id,
        file_id=embedding.file_id,
        channel_hits=(
            ChannelHit(channel=channel, variant=variant, rank=rank, raw_score=raw_score),
        ),
        provenance=provenance_for(embedding.source_type),
    )
