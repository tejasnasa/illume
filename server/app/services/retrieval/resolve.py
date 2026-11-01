"""Resolve embedding hits into citable source references in batch.

A hit is an :class:`~app.models.embedding.Embedding` row whose ``source_id``
points at a different table depending on ``source_type``. Resolving each hit on
its own costs one or two round trips per hit -- up to twenty for a ten-hit
answer, and far more once retrieval hands the resolver a larger pool. This
module groups the hits by type and issues one query per table instead, so the
cost is bounded by the number of source types rather than by the number of hits.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AstSymbol, Commit, Embedding, File, PullRequest


@dataclass
class SourceReference:
    """A resolved citation backing part of an answer.

    Attributes:
        source_type: One of "symbol", "commit", "pull_request", "file",
            or "document".
        chunk_text: The embedded text that matched the query.
        file_path: Path for symbol/file sources.
        symbol_name: Name for symbol sources.
        start_line: Start line for symbol sources.
        end_line: End line for symbol sources.
        commit_hash: Hash for commit sources.
        author_name: Author for commit sources.
        pr_number: Number for pull request sources.
        pr_title: Title for pull request sources.
    """

    source_type: str
    chunk_text: str
    file_path: str | None = None
    symbol_name: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    commit_hash: str | None = None
    author_name: str | None = None
    pr_number: int | None = None
    pr_title: str | None = None


async def resolve_sources(
    db: AsyncSession, embeddings: Sequence[Embedding]
) -> list[SourceReference]:
    """Resolves a batch of hits, preserving their input order.

    One query per backing table, plus a single ``files`` query shared by symbol
    and file hits. A hit whose row has been deleted degrades to a citation with
    ``None`` detail fields rather than disappearing, matching the per-hit
    behaviour this replaces.

    Args:
        db: Async session used for the lookups.
        embeddings: Hits in the order the caller wants them back.

    Returns:
        One :class:`SourceReference` per input hit, in the same order.
    """
    if not embeddings:
        return []

    ids_by_type: dict[str, set[UUID]] = defaultdict(set)
    file_ids: set[UUID] = set()
    for embedding in embeddings:
        ids_by_type[embedding.source_type].add(embedding.source_id)
        if embedding.file_id is not None:
            file_ids.add(embedding.file_id)

    symbols: dict[UUID, AstSymbol] = {}
    if ids_by_type.get("symbol"):
        symbol_rows = (
            await db.execute(select(AstSymbol).where(AstSymbol.id.in_(ids_by_type["symbol"])))
        ).scalars()
        symbols = {row.id: row for row in symbol_rows}

    commits: dict[UUID, Commit] = {}
    if ids_by_type.get("commit"):
        commit_rows = (
            await db.execute(select(Commit).where(Commit.id.in_(ids_by_type["commit"])))
        ).scalars()
        commits = {row.id: row for row in commit_rows}

    pull_requests: dict[UUID, PullRequest] = {}
    if ids_by_type.get("pull_request"):
        pull_request_rows = (
            await db.execute(
                select(PullRequest).where(PullRequest.id.in_(ids_by_type["pull_request"]))
            )
        ).scalars()
        pull_requests = {row.id: row for row in pull_request_rows}

    files: dict[UUID, File] = {}
    if file_ids:
        file_rows = (await db.execute(select(File).where(File.id.in_(file_ids)))).scalars()
        files = {row.id: row for row in file_rows}

    return [
        _reference(embedding, symbols, commits, pull_requests, files) for embedding in embeddings
    ]


def _reference(
    embedding: Embedding,
    symbols: dict[UUID, AstSymbol],
    commits: dict[UUID, Commit],
    pull_requests: dict[UUID, PullRequest],
    files: dict[UUID, File],
) -> SourceReference:
    """Builds one citation from the already-loaded lookup maps."""
    if embedding.source_type == "symbol":
        symbol = symbols.get(embedding.source_id)
        file = files.get(embedding.file_id) if embedding.file_id else None
        return SourceReference(
            source_type="symbol",
            chunk_text=embedding.chunk_text,
            file_path=file.path if file else None,
            symbol_name=symbol.name if symbol else None,
            start_line=symbol.start_line if symbol else None,
            end_line=symbol.end_line if symbol else None,
        )

    if embedding.source_type == "commit":
        commit = commits.get(embedding.source_id)
        return SourceReference(
            source_type="commit",
            chunk_text=embedding.chunk_text,
            commit_hash=commit.hash if commit else None,
            author_name=commit.author_name if commit else None,
        )

    if embedding.source_type == "pull_request":
        pull_request = pull_requests.get(embedding.source_id)
        return SourceReference(
            source_type="pull_request",
            chunk_text=embedding.chunk_text,
            pr_number=pull_request.number if pull_request else None,
            pr_title=pull_request.title if pull_request else None,
        )

    if embedding.source_type == "file":
        file = files.get(embedding.file_id) if embedding.file_id else None
        return SourceReference(
            source_type="file",
            chunk_text=embedding.chunk_text,
            file_path=file.path if file else None,
        )

    # Documents (README sections) are keyed by repository_id, not a row ID.
    return SourceReference(source_type="document", chunk_text=embedding.chunk_text)
