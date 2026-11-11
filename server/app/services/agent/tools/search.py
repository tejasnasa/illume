"""Tools that find things: meaning-based search, symbol names, grep and history."""

from __future__ import annotations

import fnmatch
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select, text

from app.models import Commit
from app.services.agent.tools.context import ToolContext
from app.services.agent.tools.lookup import touched
from app.services.agent.tools.output import ListOutput, Provenance, excerpt, fence
from app.services.agent.tools.registry import REGISTRY, Tool, ToolInput
from app.services.retrieval.candidate import Candidate, QueryVariant
from app.services.retrieval.channels._common import SEARCHABLE_KINDS_SQL
from app.services.retrieval.channels.grep import (
    DEFAULT_MAX_RESULTS,
    MAX_PATTERN_LENGTH,
    escape_like,
    grep_symbols,
)
from app.services.retrieval.channels.history import HistorySearch
from app.services.retrieval.citations import code_key, normalize_path
from app.services.retrieval.config import HistoryChannel
from app.services.retrieval.context import SOURCE_LABELS
from app.services.retrieval.dates import DateRange, parse_day, resolve_date_range
from app.services.retrieval.pipeline import retrieve

SourceKind = Literal["symbol", "file", "commit", "pull_request", "document"]

_HIT_EXCERPT_CHARS = 1500
_HISTORY_EXCERPT_CHARS = 800
_HISTORY_POOL = 50


# --- search_code ----------------------------------------------------------------


class SearchCodeInput(ToolInput):
    query: str = Field(
        min_length=1,
        max_length=500,
        description="What to look for, as a question or a few keywords or identifiers.",
    )
    k: int = Field(default=10, ge=1, le=30, description="How many results to return (1 to 30).")
    source_types: list[SourceKind] | None = Field(
        default=None,
        description="Only return these kinds of source. Omit to search everything.",
    )


class CodeHit(BaseModel):
    key: str
    source_type: str
    provenance: Provenance
    path: str | None
    symbol_name: str | None
    symbol_id: UUID | None
    channels: list[str]
    text: str


class SearchCodeOutput(ListOutput):
    items: list[CodeHit]
    degraded: list[str] = []

    def render(self) -> str:
        if not self.items:
            return self.note_line() + f"0 of {self.total} results. Try other words or a tool."
        lines = [self.note_line() + self.count_line("results")]
        if self.degraded:
            lines.append(f"Some search stages were unavailable ({', '.join(self.degraded)}).")
        for hit in self.items:
            label = SOURCE_LABELS.get(hit.source_type, hit.source_type)
            lines.append(fence(hit.key, hit.text, label=label, provenance=hit.provenance))
        return "\n\n".join(lines)


def _hit(candidate: Candidate) -> CodeHit:
    is_symbol = candidate.source_type == "symbol"
    return CodeHit(
        key=candidate.key,
        source_type=candidate.source_type,
        provenance=candidate.provenance,
        path=candidate.file_path,
        symbol_name=candidate.reference.symbol_name,
        symbol_id=candidate.source_id if is_symbol else None,
        channels=sorted({hit.channel for hit in candidate.channel_hits}),
        text=excerpt(candidate.text, _HIT_EXCERPT_CHARS),
    )


async def _search_code(ctx: ToolContext, args: SearchCodeInput) -> SearchCodeOutput:
    async with ctx.session_factory() as db:
        result = await retrieve(ctx.pipeline, args.query, ctx=ctx.retrieval(db), llm=ctx.llm)
    wanted = set(args.source_types) if args.source_types else None
    matching = [c for c in result.candidates if wanted is None or c.source_type in wanted]
    degraded = sorted({str(item.get("stage", "search")) for item in result.trace.degraded})
    return SearchCodeOutput(
        total=len(matching),
        items=[_hit(candidate) for candidate in matching[: args.k]],
        degraded=degraded,
    )


# --- search_symbols ---------------------------------------------------------------

_FIND_SYMBOLS = text(
    f"""
    SELECT s.id, s.kind::text AS kind, s.name, f.path, s.start_line, s.end_line, s.docstring,
           count(*) OVER () AS total
    FROM ast_symbols s
    JOIN files f ON f.id = s.file_id
    WHERE f.repository_id = :repo
      AND s.{SEARCHABLE_KINDS_SQL}
      AND (CAST(:kind AS text) IS NULL OR s.kind::text = :kind)
      AND (s.name = :name OR s.name % :name OR s.name ILIKE :contains ESCAPE '\\')
    ORDER BY (s.name = :name) DESC, (s.name ILIKE :prefix ESCAPE '\\') DESC,
             similarity(s.name, :name) DESC, f.fan_in DESC NULLS LAST, f.path, s.start_line, s.id
    LIMIT :limit
    """
)


class SearchSymbolsInput(ToolInput):
    name: str = Field(
        min_length=1,
        max_length=200,
        description="The symbol name, or part of it. Spelling need not be exact.",
    )
    kind: Literal["function", "class", "method"] | None = Field(
        default=None, description="Only symbols of this kind. Omit for all kinds."
    )
    limit: int = Field(default=20, ge=1, le=50, description="How many symbols to return.")


class SymbolHit(BaseModel):
    key: str
    symbol_id: UUID
    name: str
    kind: str
    path: str
    start_line: int | None
    end_line: int | None
    doc: str


class SearchSymbolsOutput(ListOutput):
    items: list[SymbolHit]

    def render(self) -> str:
        if not self.items:
            return self.note_line() + "0 symbols matched that name. Try a shorter part of it."
        blocks = [self.note_line() + self.count_line("symbols")]
        for hit in self.items:
            where = f"{hit.path}:{hit.start_line}-{hit.end_line}" if hit.start_line else hit.path
            body = f"{hit.kind} {hit.name}  {where}  id={hit.symbol_id}"
            if hit.doc:
                body += f"\n  {hit.doc}"
            blocks.append(fence(hit.key, body))
        return "\n".join(blocks)


async def _search_symbols(ctx: ToolContext, args: SearchSymbolsInput) -> SearchSymbolsOutput:
    async with ctx.session_factory() as db:
        rows = (
            await db.execute(
                _FIND_SYMBOLS,
                {
                    "repo": ctx.repository.id,
                    "name": args.name,
                    "kind": args.kind,
                    "contains": f"%{escape_like(args.name)}%",
                    "prefix": f"{escape_like(args.name)}%",
                    "limit": args.limit,
                },
            )
        ).all()
    items = [
        SymbolHit(
            key=code_key(row.path, row.start_line, row.end_line)
            if row.start_line and row.end_line
            else code_key(row.path),
            symbol_id=row.id,
            name=row.name,
            kind=row.kind,
            path=row.path,
            start_line=row.start_line,
            end_line=row.end_line,
            doc=excerpt((row.docstring or "").strip().partition("\n")[0], 200),
        )
        for row in rows
    ]
    return SearchSymbolsOutput(total=int(rows[0].total) if rows else 0, items=items)


# --- grep_code ------------------------------------------------------------------


class GrepCodeInput(ToolInput):
    pattern: str = Field(
        min_length=1,
        max_length=MAX_PATTERN_LENGTH,
        description=(
            "A PostgreSQL regular expression, matched against each symbol body. "
            "Escape regex characters to search for them literally."
        ),
    )
    path_glob: str | None = Field(
        default=None,
        max_length=200,
        description="Only search files whose path matches this glob, such as `app/auth/*.py`.",
    )
    max_results: int = Field(
        default=30, ge=1, le=100, description="How many matching symbols to return."
    )


class GrepMatchLine(BaseModel):
    path: str
    line: int
    text: str


class GrepGroup(BaseModel):
    key: str
    symbol_name: str
    lines: list[GrepMatchLine]


class GrepCodeOutput(ListOutput):
    items: list[GrepGroup]
    refusal: str | None = None
    refusal_reason: str | None = None

    def render(self) -> str:
        if self.refusal:
            return f"The search did not run ({self.refusal_reason}). {self.refusal}"
        if not self.items:
            return (
                self.note_line()
                + "0 symbols matched. Only code inside functions, classes and methods is "
                "searched; use read_file for imports, constants and configuration."
            )
        blocks = [self.note_line() + self.count_line("matching symbols")]
        for group in self.items:
            body = "\n".join(f"{m.path}:{m.line}: {m.text}" for m in group.lines)
            blocks.append(fence(group.key, body))
        return "\n".join(blocks)


async def _grep_code(ctx: ToolContext, args: GrepCodeInput) -> GrepCodeOutput:
    glob = args.path_glob
    async with ctx.session_factory() as db:
        result = await grep_symbols(
            db,
            ctx.repository.id,
            args.pattern,
            regex=True,
            max_results=DEFAULT_MAX_RESULTS if glob else args.max_results,
        )
    if result.refusal is not None:
        return GrepCodeOutput(
            total=0,
            items=[],
            refusal=result.refusal.message,
            refusal_reason=result.refusal.reason,
        )

    groups: dict[UUID, GrepGroup] = {}
    for match in result.matches:
        if glob and not fnmatch.fnmatchcase(match.path, normalize_path(glob)):
            continue
        group = groups.get(match.symbol_id)
        if group is None:
            key = (
                code_key(match.path, match.symbol_start_line, match.symbol_end_line)
                if match.symbol_start_line and match.symbol_end_line
                else code_key(match.path)
            )
            group = groups[match.symbol_id] = GrepGroup(
                key=key, symbol_name=match.symbol_name, lines=[]
            )
        group.lines.append(GrepMatchLine(path=match.path, line=match.line, text=match.text))

    kept = list(groups.values())
    # A glob is applied after the search, so the count covers only the symbols it saw.
    total = len(kept) if glob and not result.truncated else result.total_symbols
    note = None
    if glob and result.truncated:
        note = (
            f"The glob was applied to the first {DEFAULT_MAX_RESULTS} matching symbols "
            "only; make the pattern more specific to see the rest."
        )
        total = len(kept)
    return GrepCodeOutput(total=total, items=kept[: args.max_results], note=note)


# --- search_history ---------------------------------------------------------------


class SearchHistoryInput(ToolInput):
    query: str = Field(
        min_length=1, max_length=500, description="What happened or why, in a few words."
    )
    kind: Literal["commit", "pr", "both"] = Field(
        default="both", description="Search commits, pull requests, or both."
    )
    path: str | None = Field(
        default=None,
        max_length=1024,
        description="Only commits that changed this file. Pull requests are left out when set.",
    )
    since: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description=(
            "Only history on or after this date (YYYY-MM-DD). Pass it for time-bounded "
            "questions such as 'in the last two weeks', working the date out from today."
        ),
    )
    until: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Only history on or before this date (YYYY-MM-DD). Pass it with since.",
    )
    k: int = Field(default=10, ge=1, le=30, description="How many results to return (1 to 30).")


class HistoryHit(BaseModel):
    key: str
    kind: str
    author: str | None
    text: str


class SearchHistoryOutput(ListOutput):
    items: list[HistoryHit]

    def render(self) -> str:
        if not self.items:
            return self.note_line() + "0 commits or pull requests matched."
        blocks = [self.note_line() + self.count_line("commits and pull requests")]
        for hit in self.items:
            blocks.append(fence(hit.key, hit.text, label=hit.kind, provenance="history"))
        return "\n\n".join(blocks)


def _history_range(ctx: ToolContext, args: SearchHistoryInput) -> DateRange | None:
    """The time span a history search is restricted to.

    Dates the model passes win. Without them, a span named in the run's question
    is used, so a time-bounded question is filtered even when the model forgets
    the arguments.
    """
    since = parse_day(args.since) if args.since else None
    until = parse_day(args.until) if args.until else None
    if since is not None or until is not None:
        # ``until`` names a day, so the whole day is included.
        end = until.replace(hour=23, minute=59, second=59, microsecond=999999) if until else None
        return DateRange(since, end, "tool arguments")
    if ctx.question:
        return resolve_date_range(ctx.question, datetime.now(UTC))
    return None


async def _search_history(ctx: ToolContext, args: SearchHistoryInput) -> SearchHistoryOutput:
    date_range = _history_range(ctx, args)
    wanted = {
        "commit": {"commit"},
        "pr": {"pull_request"},
        "both": {"commit", "pull_request"},
    }[args.kind]
    note = None
    async with ctx.session_factory() as db:
        found = await HistorySearch().search(
            ctx.retrieval(db, date_range), QueryVariant(args.query), HistoryChannel(k=_HISTORY_POOL)
        )
        found = [candidate for candidate in found if candidate.source_type in wanted]

        if args.path:
            path = normalize_path(args.path)
            commit_ids = [c.source_id for c in found if c.source_type == "commit" and c.source_id]
            touching: set[UUID] = set()
            if commit_ids:
                rows = await db.execute(
                    select(Commit.id, Commit.changed_files_list).where(
                        Commit.repository_id == ctx.repository.id, Commit.id.in_(commit_ids)
                    )
                )
                touching = {row.id for row in rows if path in (row.changed_files_list or [])}
            found = [c for c in found if c.source_id in touching]
            if "pull_request" in wanted:
                note = "A path filter applies to commits only, so pull requests were left out."
    if date_range is not None:
        span = f"Restricted to commits and pull requests {date_range.describe(datetime.now(UTC))}."
        note = f"{span} {note}" if note else span

    items = [
        HistoryHit(
            key=candidate.key,
            kind=candidate.source_type,
            author=candidate.reference.author_name,
            text=excerpt(candidate.text, _HISTORY_EXCERPT_CHARS),
        )
        for candidate in found[: args.k]
    ]
    return SearchHistoryOutput(total=len(found), items=items, note=note)


REGISTRY.register(
    Tool(
        name="search_code",
        description=(
            "Search the repository by meaning and by keyword, using the same retrieval as the "
            "chat. Returns the best matching code, files, commits, pull requests and README "
            "sections, each with a citation key. Start here for open questions; use "
            "search_symbols or grep_code when you know an exact name or string."
        ),
        input_model=SearchCodeInput,
        output_model=SearchCodeOutput,
        handler=_search_code,
        cost="model",
        timeout_s=60,
        emits_nodes=lambda out: touched(*(hit.path for hit in out.items)),
    )
)

REGISTRY.register(
    Tool(
        name="search_symbols",
        description=(
            "Find functions, classes and methods by name. Matches exact names first, then "
            "similar spellings and names that contain the text. Returns path, line range, kind "
            "and the first line of the docstring. Use it when you know roughly what a symbol "
            "is called; use read_symbol to see its body."
        ),
        input_model=SearchSymbolsInput,
        output_model=SearchSymbolsOutput,
        handler=_search_symbols,
        cost="free",
        timeout_s=10,
        emits_nodes=lambda out: touched(*(hit.path for hit in out.items)),
    )
)

REGISTRY.register(
    Tool(
        name="grep_code",
        description=(
            "Search for a regular expression inside the bodies of functions, classes and "
            "methods. Returns `path:line: text` for each matching line. Only code inside "
            "those symbols is searched: module-level statements, imports, constants and "
            "configuration files are not, so use read_file for them. Patterns over "
            f"{MAX_PATTERN_LENGTH} characters, or ones that take too long, are refused."
        ),
        input_model=GrepCodeInput,
        output_model=GrepCodeOutput,
        handler=_grep_code,
        cost="free",
        timeout_s=10,
        emits_nodes=lambda out: touched(*(m.path for g in out.items for m in g.lines)),
    )
)

REGISTRY.register(
    Tool(
        name="search_history",
        description=(
            "Search commit messages and merged pull requests by meaning. Use it for why and "
            "when questions: why something was changed, who introduced it, what a pull "
            "request was for. For a time-bounded question ('in the last two weeks', "
            "'since March') pass since and until as YYYY-MM-DD dates. Results are "
            "history, not the current code."
        ),
        input_model=SearchHistoryInput,
        output_model=SearchHistoryOutput,
        handler=_search_history,
        cost="model",
        timeout_s=30,
    )
)
