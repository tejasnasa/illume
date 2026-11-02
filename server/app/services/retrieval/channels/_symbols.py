"""Turning matched symbols into candidates, for the channels that search ``ast_symbols``."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.retrieval.candidate import Candidate, ChannelHit, QueryVariant
from app.services.retrieval.channels._common import SEARCHABLE_KINDS_SQL
from app.services.retrieval.keys import key_for
from app.services.retrieval.resolve import SourceReference

# Matches the embedder's chunk limit (2048 estimated tokens at four characters each),
# so a symbol rendered here is never longer than one that was indexed.
MAX_RENDERED_CHARACTERS = 8192


@dataclass(frozen=True)
class SymbolRow:
    """A symbol with the file facts a candidate needs.

    Attributes:
        id: The symbol's row id.
        file_id: The owning file.
        path: The file's repository-relative path.
        kind: ``function``, ``class`` or ``method``.
        name: The symbol's name.
        start_line: First line of the definition, when known.
        end_line: Last line of the definition, when known.
        source_code: The stored body.
        fan_in: How many files import the owning file.
    """

    id: UUID
    file_id: UUID
    path: str
    kind: str
    name: str
    start_line: int | None
    end_line: int | None
    source_code: str | None
    fan_in: int


def render_symbol(row: SymbolRow) -> str:
    """The text shown for a symbol that has no embedding row."""
    rendered = f"# {row.path}\n## {row.kind}: {row.name}\n{row.source_code or ''}"
    return rendered[:MAX_RENDERED_CHARACTERS]


_LOAD_SYMBOLS = text(
    f"""
    SELECT s.id, s.file_id, f.path, s.kind::text AS kind, s.name, s.start_line, s.end_line,
           s.source_code, COALESCE(f.fan_in, 0) AS fan_in
    FROM ast_symbols s
    JOIN files f ON f.id = s.file_id
    WHERE f.repository_id = :repo
      AND s.{SEARCHABLE_KINDS_SQL}
      AND s.id = ANY(:ids)
    """
)


async def load_symbols(
    db: AsyncSession, repository_id: UUID, symbol_ids: Sequence[UUID]
) -> dict[UUID, SymbolRow]:
    """Loads symbols by id in one query, only those of the given repository."""
    if not symbol_ids:
        return {}
    result = await db.execute(_LOAD_SYMBOLS, {"repo": repository_id, "ids": list(symbol_ids)})
    return {row.id: SymbolRow(**row._mapping) for row in result}


async def symbol_candidates(
    db: AsyncSession,
    repository_id: UUID,
    ranked: Sequence[tuple[SymbolRow, float]],
    variant: QueryVariant,
    channel: str,
) -> list[Candidate]:
    """Builds candidates for symbols already in rank order.

    The text is the symbol's own embedded chunk when it has one, fetched for all
    symbols in a single query, so a symbol reads the same whichever channel
    found it. Otherwise it is rendered from the stored body. Symbols whose key
    collides with an earlier one are dropped, so ranks stay contiguous.

    Args:
        db: The request's session.
        repository_id: The repository the symbols belong to.
        ranked: ``(symbol, score)`` pairs, best first.
        variant: The query variant that produced them.
        channel: The channel kind to record on each hit.
    """
    chunks: dict[UUID, str] = {}
    if ranked:
        rows = await db.execute(
            text(
                "SELECT source_id, chunk_text FROM embeddings "
                "WHERE repository_id = :repo AND source_type = 'symbol' "
                "AND source_id = ANY(:ids)"
            ),
            {"repo": repository_id, "ids": [symbol.id for symbol, _ in ranked]},
        )
        chunks = {row.source_id: row.chunk_text for row in rows}

    candidates: list[Candidate] = []
    seen: set[str] = set()
    for symbol, score in ranked:
        chunk_text = chunks.get(symbol.id) or render_symbol(symbol)
        reference = SourceReference(
            source_type="symbol",
            chunk_text=chunk_text,
            file_path=symbol.path,
            symbol_name=symbol.name,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
        )
        key = key_for(reference)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            Candidate(
                key=key,
                reference=reference,
                text=chunk_text,
                source_id=symbol.id,
                file_id=symbol.file_id,
                channel_hits=(
                    ChannelHit(
                        channel=channel,
                        variant=variant.index,
                        rank=len(candidates) + 1,
                        raw_score=score,
                    ),
                ),
            )
        )
    return candidates
