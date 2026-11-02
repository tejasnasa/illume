"""Seeds and file candidates for the channels that expand from files.

Graph and co-change both start from the strongest files of an earlier pass and
both return whole files, so choosing the seeds and building the candidates
live here once.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.retrieval.candidate import Candidate, ChannelHit
from app.services.retrieval.keys import key_for
from app.services.retrieval.resolve import SourceReference

# The reciprocal-rank constant used to score a seed that fusion left unscored.
SEED_RANK_CONSTANT = 60

# How many symbol names a rendered file header lists.
MAX_HEADER_SYMBOLS = 15

# The symbol kinds a rendered header names.
_HEADER_KINDS = ("function", "class", "method")


def seed_files(seeds: Sequence[Candidate], limit: int) -> dict[UUID, float]:
    """The files to expand and how strong each one is.

    Takes the first ``limit`` distinct files in ``seeds``, which is best first.
    A file scores as its best candidate does: the candidate's fused score, or
    ``1 / (60 + position)`` with a one-based position in ``seeds`` when fusion
    left it unscored. Candidates with no file (commits, pull requests,
    documents) are skipped.

    Returns:
        File ids in seed order mapped to their score.
    """
    ordered: list[UUID] = []
    scores: dict[UUID, float] = {}
    for position, candidate in enumerate(seeds, start=1):
        file_id = candidate.file_id
        if file_id is None:
            continue
        if file_id not in scores:
            if len(ordered) >= limit:
                continue
            ordered.append(file_id)
            scores[file_id] = float("-inf")
        score = (
            candidate.fused_score
            if candidate.fused_score is not None
            else 1.0 / (SEED_RANK_CONSTANT + position)
        )
        scores[file_id] = max(scores[file_id], score)
    return {file_id: scores[file_id] for file_id in ordered}


def render_file_header(
    path: str, language: str | None, fan_in: int, symbol_names: Sequence[str]
) -> str:
    """The text shown for a file that has no indexed file chunk."""
    lines = [f"# {path}"]
    if language:
        lines.append(f"Language: {language}")
    lines.append(f"Imported by {fan_in} files")
    if symbol_names:
        lines.append("Defines: " + ", ".join(symbol_names[:MAX_HEADER_SYMBOLS]))
    return "\n".join(lines)


async def file_candidates(
    db: AsyncSession,
    repository_id: UUID,
    scores: Mapping[UUID, float],
    *,
    k: int,
    channel: str,
) -> list[Candidate]:
    """Builds ranked ``file`` candidates for the scored files.

    Files are ranked by score descending then path, and only the first ``k``
    are loaded. The text is the file's indexed ``file`` chunk when it has one,
    all fetched in one query; otherwise a header rendered from the file row and
    its symbol names, fetched in a second query for just those files. Files
    outside ``repository_id`` are ignored, however they got into ``scores``.

    Args:
        db: The request's session.
        repository_id: The only repository read.
        scores: Score per file id.
        k: How many candidates to return at most.
        channel: The channel kind to record on each hit.
    """
    if not scores:
        return []
    rows = (
        await db.execute(
            text(
                "SELECT id, path, language, COALESCE(fan_in, 0) AS fan_in FROM files "
                "WHERE repository_id = :repo AND id = ANY(:ids)"
            ),
            {"repo": repository_id, "ids": list(scores)},
        )
    ).all()
    ranked = sorted(rows, key=lambda row: (-scores[row.id], row.path))[:k]
    if not ranked:
        return []
    ids = [row.id for row in ranked]

    chunks = {
        row.file_id: row.chunk_text
        for row in await db.execute(
            text(
                "SELECT file_id, chunk_text FROM embeddings "
                "WHERE repository_id = :repo AND source_type = 'file' AND file_id = ANY(:ids)"
            ),
            {"repo": repository_id, "ids": ids},
        )
    }
    bare = [file_id for file_id in ids if file_id not in chunks]
    names: dict[UUID, list[str]] = {file_id: [] for file_id in bare}
    if bare:
        symbol_rows = await db.execute(
            text(
                "SELECT file_id, name FROM ast_symbols "
                "WHERE file_id = ANY(:ids) AND kind::text = ANY(:kinds) "
                "ORDER BY file_id, start_line NULLS LAST, name"
            ),
            {"ids": bare, "kinds": list(_HEADER_KINDS)},
        )
        for row in symbol_rows:
            names[row.file_id].append(row.name)

    candidates: list[Candidate] = []
    for row in ranked:
        chunk_text = chunks.get(row.id) or render_file_header(
            row.path, row.language, row.fan_in, names.get(row.id, [])
        )
        reference = SourceReference(source_type="file", chunk_text=chunk_text, file_path=row.path)
        candidates.append(
            Candidate(
                key=key_for(reference),
                reference=reference,
                text=chunk_text,
                source_id=row.id,
                file_id=row.id,
                channel_hits=(
                    ChannelHit(
                        channel=channel,
                        variant=0,
                        rank=len(candidates) + 1,
                        raw_score=scores[row.id],
                    ),
                ),
            )
        )
    return candidates
