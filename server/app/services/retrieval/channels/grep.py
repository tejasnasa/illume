"""Line-level search inside stored symbol bodies, for the channel and for agent tools.

Only code inside functions, classes and methods is stored, so module-level
statements, imports, constants and configuration files are not searchable here.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.retrieval.candidate import Candidate, QueryVariant
from app.services.retrieval.channels._common import SEARCHABLE_KINDS_SQL
from app.services.retrieval.channels._symbols import SymbolRow, load_symbols, symbol_candidates
from app.services.retrieval.channels.base import RetrievalContext
from app.services.retrieval.config import ChannelSpec, GrepChannel
from app.services.retrieval.identifiers import identifier_tokens, quoted_strings

logger = logging.getLogger(__name__)

MAX_PATTERN_LENGTH = 200
DEFAULT_MAX_RESULTS = 200
DEFAULT_TIMEOUT_MS = 2000

RefusalReason = Literal["empty_pattern", "pattern_too_long", "invalid_regex", "timeout"]

# SQLSTATE codes: query_canceled is what ``statement_timeout`` raises, and
# invalid_regular_expression is a pattern Postgres cannot compile.
_QUERY_CANCELED = "57014"
_INVALID_REGEX = "2201B"


@dataclass(frozen=True)
class GrepMatch:
    """One matching line inside one symbol.

    Attributes:
        path: The file's repository-relative path.
        line: The line number in the file (the symbol's first line plus the offset).
        text: The line's text.
        symbol_id: The symbol containing the line.
        symbol_name: That symbol's name.
        file_id: The owning file.
        symbol_kind: ``function``, ``class`` or ``method``.
        symbol_start_line: First line of the symbol, when known.
        symbol_end_line: Last line of the symbol, when known.
        fan_in: How many files import the owning file.
    """

    path: str
    line: int
    text: str
    symbol_id: UUID
    symbol_name: str
    file_id: UUID
    symbol_kind: str
    symbol_start_line: int | None
    symbol_end_line: int | None
    fan_in: int


@dataclass(frozen=True)
class GrepRefusal:
    """Why a search did not run, in words the caller can show.

    Attributes:
        reason: A stable code.
        message: A readable explanation, including what to do about it.
    """

    reason: RefusalReason
    message: str


@dataclass(frozen=True)
class GrepResult:
    """Either the matches, or the reason the search was refused.

    Attributes:
        matches: Matching lines, grouped by symbol, most imported file first.
        total_symbols: How many symbols matched in all, including any cut off.
        truncated: Whether ``total_symbols`` exceeded ``max_results``, so the
            symbols past it are not in ``matches``.
        refusal: Set instead of ``matches`` when the search did not complete.
    """

    matches: tuple[GrepMatch, ...] = ()
    total_symbols: int = 0
    truncated: bool = False
    refusal: GrepRefusal | None = None

    @property
    def ok(self) -> bool:
        """Whether the search completed."""
        return self.refusal is None


def _refuse(reason: RefusalReason, message: str) -> GrepResult:
    return GrepResult(refusal=GrepRefusal(reason=reason, message=message))


def escape_like(pattern: str) -> str:
    """Escapes ``\\``, ``%`` and ``_`` so a ``LIKE`` pattern matches them literally."""
    return pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# The count is over every matching symbol, the rows are only the first page. The
# count window forces the scan to finish, which is why the statement timeout
# matters. The kind predicate and the repository join are what scope the search.
_LITERAL_SQL = f"""
    SELECT s.id, s.file_id, f.path, s.kind::text AS kind, s.name, s.start_line, s.end_line,
           s.source_code, COALESCE(f.fan_in, 0) AS fan_in, count(*) OVER () AS total
    FROM ast_symbols s
    JOIN files f ON f.id = s.file_id
    WHERE f.repository_id = :repo
      AND s.{SEARCHABLE_KINDS_SQL}
      AND s.source_code LIKE :pattern ESCAPE '\\'
    ORDER BY f.fan_in DESC NULLS LAST, f.path, s.start_line, s.id
    LIMIT :limit
"""

_REGEX_SQL = _LITERAL_SQL.replace(
    "s.source_code LIKE :pattern ESCAPE '\\'", "s.source_code ~ :pattern"
)


def _sqlstate(error: DBAPIError) -> str | None:
    """The SQLSTATE of a database error, however the driver wrapper exposes it."""
    original = error.orig
    for holder in (original, getattr(original, "__cause__", None)):
        code = getattr(holder, "sqlstate", None) or getattr(holder, "pgcode", None)
        if code:
            return str(code)
    return None


# Lines of the given symbols that match, with their 1-based position in the body.
# Postgres does the matching, so the pattern is run by the same engine, under the
# same statement timeout, that already accepted it. A regular-expression engine
# that backtracks cannot be interrupted from Python, so no pattern a caller
# supplies is ever run on the event loop.
_REGEX_LINES_SQL = """
    SELECT s.id AS symbol_id, t.ord AS ord, t.line AS line
    FROM ast_symbols s
    CROSS JOIN LATERAL regexp_split_to_table(s.source_code, '\n')
        WITH ORDINALITY AS t(line, ord)
    WHERE s.id = ANY(CAST(:ids AS uuid[]))
      AND t.line ~ :pattern
    ORDER BY s.id, t.ord
"""


def _matching_lines(
    row: SymbolRow, literal: str | None, regex_lines: list[tuple[int, str]] | None = None
) -> list[tuple[int, str]]:
    """The lines of a symbol's body that match, as ``(file line, text)`` pairs.

    Postgres decided the symbol matched. When no single line does (the pattern
    spans lines), the symbol is still reported, at its first line.

    Args:
        row: The symbol.
        literal: The text to find, for a literal search.
        regex_lines: For a regular-expression search, the ``(position, text)``
            pairs Postgres reported, with positions counted from 1 in the body.
    """
    start = row.start_line or 1
    lines = (row.source_code or "").splitlines()
    if literal is not None:
        found = [(start + i, line) for i, line in enumerate(lines) if literal in line]
    else:
        found = [(start + ordinal - 1, line.rstrip("\r")) for ordinal, line in regex_lines or []]
    if not found:
        found = [(start, lines[0] if lines else "")]
    return found


async def grep_symbols(
    db: AsyncSession,
    repository_id: UUID,
    pattern: str,
    *,
    regex: bool,
    max_results: int = DEFAULT_MAX_RESULTS,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> GrepResult:
    """Searches the stored function, class and method bodies of one repository.

    A regular expression is run only by Postgres, both to pick the symbols and to
    find the matching lines inside them, so a pattern that backtracks is cut off
    by the statement timeout instead of blocking the event loop.

    The query runs inside a savepoint with a statement timeout. A timeout or an
    invalid regular expression aborts the surrounding Postgres transaction, and
    the session is shared with the rest of the request, so the savepoint is what
    keeps a bad pattern from poisoning everything after it.

    Args:
        db: The request's session.
        repository_id: The only repository searched.
        pattern: Text to find literally, or a Postgres regular expression.
        regex: Treat ``pattern`` as a regular expression rather than literal text.
        max_results: How many symbols to return at most.
        timeout_ms: How long the query may run before it is cancelled.

    Returns:
        The matching lines, or a refusal. A refusal is returned rather than
        raised; the session remains usable after one.
    """
    if not pattern:
        return _refuse("empty_pattern", "The pattern is empty; give some text to search for.")
    if len(pattern) > MAX_PATTERN_LENGTH:
        return _refuse(
            "pattern_too_long",
            f"The pattern is {len(pattern)} characters; the limit is {MAX_PATTERN_LENGTH}. "
            "Search for a shorter, more specific part of it.",
        )

    parameters = {
        "repo": repository_id,
        "pattern": pattern if regex else f"%{escape_like(pattern)}%",
        "limit": max_results,
    }

    try:
        async with db.begin_nested():
            previous = (
                await db.execute(text("SELECT current_setting('statement_timeout')"))
            ).scalar_one()
            await db.execute(
                text("SELECT set_config('statement_timeout', :value, true)"),
                {"value": f"{int(timeout_ms)}ms"},
            )
            result = await db.execute(text(_REGEX_SQL if regex else _LITERAL_SQL), parameters)
            rows = result.all()
            regex_lines: dict[UUID, list[tuple[int, str]]] = defaultdict(list)
            if regex and rows:
                line_rows = await db.execute(
                    text(_REGEX_LINES_SQL),
                    {"ids": [row.id for row in rows], "pattern": pattern},
                )
                for line_row in line_rows.all():
                    regex_lines[line_row.symbol_id].append((line_row.ord, line_row.line))
            # A setting made inside a savepoint outlives it unless it is undone,
            # and this one would otherwise cut off the rest of the request.
            await db.execute(
                text("SELECT set_config('statement_timeout', :value, true)"),
                {"value": previous},
            )
    except DBAPIError as error:
        code = _sqlstate(error)
        if code == _QUERY_CANCELED:
            return _refuse(
                "timeout",
                f"The pattern took longer than {timeout_ms} ms to run; it is too expensive. "
                "Narrow it, for example with a longer literal part.",
            )
        if code == _INVALID_REGEX:
            return _refuse(
                "invalid_regex",
                "The pattern is not a valid regular expression: "
                f"{_error_detail(error)}. Fix the pattern, or search for it as plain text.",
            )
        raise

    total = int(rows[0].total) if rows else 0
    matches: list[GrepMatch] = []
    for row in rows:
        symbol = SymbolRow(
            id=row.id,
            file_id=row.file_id,
            path=row.path,
            kind=row.kind,
            name=row.name,
            start_line=row.start_line,
            end_line=row.end_line,
            source_code=row.source_code,
            fan_in=row.fan_in,
        )
        matches.extend(
            GrepMatch(
                path=symbol.path,
                line=line,
                text=line_text,
                symbol_id=symbol.id,
                symbol_name=symbol.name,
                file_id=symbol.file_id,
                symbol_kind=symbol.kind,
                symbol_start_line=symbol.start_line,
                symbol_end_line=symbol.end_line,
                fan_in=symbol.fan_in,
            )
            for line, line_text in _matching_lines(
                symbol, None if regex else pattern, regex_lines.get(symbol.id)
            )
        )
    return GrepResult(matches=tuple(matches), total_symbols=total, truncated=total > max_results)


def _error_detail(error: DBAPIError) -> str:
    """The database's own description of a failure, without the driver's class prefix."""
    first_line = str(error.orig).splitlines()[0] if error.orig else str(error)
    return first_line.split(": ", 1)[-1].strip()


def grep_terms(question: str) -> list[str]:
    """The literal strings worth grepping for in a question.

    Identifier-like tokens plus anything in quotes, without repeats.
    """
    return list(dict.fromkeys([*identifier_tokens(question), *quoted_strings(question)]))


class GrepSearch:
    """Finds symbols whose bodies contain an identifier or quoted string from the question."""

    kind = "grep"

    async def search(
        self, ctx: RetrievalContext, variant: QueryVariant, spec: ChannelSpec
    ) -> list[Candidate]:
        """Returns up to ``spec.k`` symbols containing the question's literal terms.

        Each identifier-like token and each quoted string is grepped literally.
        Symbols are merged across terms and ranked by how many lines matched,
        then by how widely the file is imported. A term whose search is refused
        (for instance by the timeout) is skipped. A ``hyde`` variant is searched
        by the dense channel only, so it returns nothing here.

        Raises:
            TypeError: When ``spec`` is not a :class:`GrepChannel`.
        """
        if not isinstance(spec, GrepChannel):
            raise TypeError(f"grep channel given a {type(spec).__name__}")
        if variant.kind == "hyde":
            return []
        terms = grep_terms(variant.text)
        if not terms:
            return []

        line_counts: dict[UUID, int] = defaultdict(int)
        fan_in: dict[UUID, int] = {}
        for term in terms:
            result = await grep_symbols(
                ctx.db, ctx.repository_id, term, regex=False, max_results=spec.k
            )
            if result.refusal is not None:
                logger.info("grep term skipped: %s", result.refusal.reason)
                continue
            for match in result.matches:
                line_counts[match.symbol_id] += 1
                fan_in[match.symbol_id] = match.fan_in

        ordered = sorted(line_counts, key=lambda sid: (-line_counts[sid], -fan_in[sid], sid))
        ordered = ordered[: spec.k]
        symbols = await load_symbols(ctx.db, ctx.repository_id, ordered)
        ranked = [(symbols[sid], float(line_counts[sid])) for sid in ordered if sid in symbols]
        return await symbol_candidates(ctx.db, ctx.repository_id, ranked, variant, self.kind)
