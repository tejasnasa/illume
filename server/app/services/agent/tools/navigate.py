"""Tools that look around: list files, outline a file, read one symbol."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select

from app.models import AstSymbol, File
from app.services.agent.tools.context import ToolContext
from app.services.agent.tools.lookup import find_file, no_such_file, touched
from app.services.agent.tools.output import ListOutput, fence, numbered
from app.services.agent.tools.registry import REGISTRY, Tool, ToolInput
from app.services.retrieval.channels.grep import escape_like
from app.services.retrieval.citations import code_key, normalize_path

_OUTLINE_LIMIT = 300
_BODY_LIMIT = 5
_OUTLINE_KINDS = ("function", "class", "method")


def _symbol_key(path: str, start: int | None, end: int | None) -> str:
    return code_key(path, start, end) if start and end else code_key(path)


# --- list_files -------------------------------------------------------------------


class ListFilesInput(ToolInput):
    path_prefix: str | None = Field(
        default=None,
        max_length=1024,
        description="Only files whose path starts with this, such as `app/auth/`.",
    )
    language: str | None = Field(
        default=None, max_length=40, description="Only files in this language, such as `python`."
    )
    limit: int = Field(default=50, ge=1, le=200, description="How many files to return.")


class FileEntry(BaseModel):
    path: str
    language: str | None
    loc: int | None
    fan_in: int
    criticality: str | None


class ListFilesOutput(ListOutput):
    items: list[FileEntry]

    def render(self) -> str:
        if not self.items:
            return self.note_line() + "0 files matched. Try a shorter path_prefix."
        rows = [
            f"{f.path}  {f.language or '-'}  {f.loc or 0} loc  fan-in {f.fan_in}  "
            f"{f.criticality or '-'}"
            for f in self.items
        ]
        header = self.count_line("files") + " (path, language, size, importers, criticality)"
        return (
            self.note_line()
            + header
            + "\n"
            + fence("tool:list_files", "\n".join(rows), label="listing")
        )


async def _list_files(ctx: ToolContext, args: ListFilesInput) -> ListFilesOutput:
    query = select(
        File.path,
        File.language,
        File.loc,
        func.coalesce(File.fan_in, 0).label("fan_in"),
        File.criticality,
        func.count().over().label("total"),
    ).where(File.repository_id == ctx.repository.id)
    if args.path_prefix:
        query = query.where(
            File.path.like(escape_like(normalize_path(args.path_prefix)) + "%", escape="\\")
        )
    if args.language:
        query = query.where(func.lower(File.language) == args.language.lower())
    async with ctx.session_factory() as db:
        rows = (await db.execute(query.order_by(File.path).limit(args.limit))).all()
    return ListFilesOutput(
        total=int(rows[0].total) if rows else 0,
        items=[
            FileEntry(
                path=r.path,
                language=r.language,
                loc=r.loc,
                fan_in=r.fan_in,
                criticality=r.criticality,
            )
            for r in rows
        ],
    )


# --- list_symbols -----------------------------------------------------------------


class ListSymbolsInput(ToolInput):
    path: str = Field(min_length=1, max_length=1024, description="The file's path.")


class OutlineEntry(BaseModel):
    kind: str
    name: str
    start_line: int | None
    end_line: int | None


class ListSymbolsOutput(ListOutput):
    path: str
    items: list[OutlineEntry]

    def render(self) -> str:
        if not self.items:
            return self.note_line() + (
                f"0 symbols in {self.path}. Only functions, classes and methods are listed; "
                "use read_file to see the rest of the file."
            )
        rows = [
            f"L{s.start_line}-{s.end_line}  {s.kind} {s.name}"
            if s.start_line
            else f"L?  {s.kind} {s.name}"
            for s in self.items
        ]
        header = self.count_line(f"symbols in {self.path}")
        body = fence(code_key(self.path), "\n".join(rows), label="outline")
        return self.note_line() + header + "\n" + body


async def _list_symbols(ctx: ToolContext, args: ListSymbolsInput) -> ListSymbolsOutput:
    async with ctx.session_factory() as db:
        file = await find_file(db, ctx.repository.id, args.path)
        if file is None:
            return ListSymbolsOutput(
                path=args.path, total=0, items=[], note=no_such_file(args.path)
            )
        rows = (
            await db.execute(
                select(
                    AstSymbol.kind,
                    AstSymbol.name,
                    AstSymbol.start_line,
                    AstSymbol.end_line,
                    func.count().over().label("total"),
                )
                .where(AstSymbol.file_id == file.id, AstSymbol.kind.in_(_OUTLINE_KINDS))
                .order_by(AstSymbol.start_line, AstSymbol.id)
                .limit(_OUTLINE_LIMIT)
            )
        ).all()
    return ListSymbolsOutput(
        path=file.path,
        total=int(rows[0].total) if rows else 0,
        items=[
            OutlineEntry(kind=r.kind, name=r.name, start_line=r.start_line, end_line=r.end_line)
            for r in rows
        ],
    )


# --- read_symbol ------------------------------------------------------------------


class ReadSymbolInput(ToolInput):
    name: str | None = Field(
        default=None, max_length=200, description="The symbol's exact name. Give this or symbol_id."
    )
    symbol_id: UUID | None = Field(
        default=None, description="An id from search_symbols or search_code. Give this or name."
    )
    path: str | None = Field(
        default=None,
        max_length=1024,
        description="With name: only the symbol in this file, when several share the name.",
    )

    @model_validator(mode="after")
    def _one_of_name_or_id(self) -> ReadSymbolInput:
        if (self.name is None) == (self.symbol_id is None):
            raise ValueError("give exactly one of `name` and `symbol_id`")
        return self


class SymbolBody(BaseModel):
    key: str
    symbol_id: UUID
    name: str
    kind: str
    path: str
    start_line: int | None
    end_line: int | None
    source: str


class ReadSymbolOutput(ListOutput):
    items: list[SymbolBody]

    def render(self) -> str:
        if not self.items:
            return self.note_line() + "0 symbols found. Check the name with search_symbols."
        blocks = [self.note_line() + self.count_line("symbols")]
        for symbol in self.items:
            where = f"{symbol.path}:{symbol.start_line}-{symbol.end_line}"
            body = f"{symbol.kind} {symbol.name}  {where}\n{symbol.source}"
            blocks.append(fence(symbol.key, body))
        return "\n\n".join(blocks)


async def _read_symbol(ctx: ToolContext, args: ReadSymbolInput) -> ReadSymbolOutput:
    query = (
        select(
            AstSymbol.id,
            AstSymbol.kind,
            AstSymbol.name,
            AstSymbol.start_line,
            AstSymbol.end_line,
            AstSymbol.source_code,
            File.path,
            func.count().over().label("total"),
        )
        .join(File, File.id == AstSymbol.file_id)
        .where(File.repository_id == ctx.repository.id, AstSymbol.kind != "import")
    )
    if args.symbol_id is not None:
        query = query.where(AstSymbol.id == args.symbol_id)
    else:
        query = query.where(AstSymbol.name == args.name)
        if args.path:
            query = query.where(File.path == normalize_path(args.path))
    query = query.order_by(File.fan_in.desc().nulls_last(), File.path, AstSymbol.start_line)
    async with ctx.session_factory() as db:
        rows = (await db.execute(query.limit(_BODY_LIMIT))).all()

    items = [
        SymbolBody(
            key=_symbol_key(r.path, r.start_line, r.end_line),
            symbol_id=r.id,
            name=r.name,
            kind=r.kind,
            path=r.path,
            start_line=r.start_line,
            end_line=r.end_line,
            source=numbered(r.source_code or "", r.start_line or 1),
        )
        for r in rows
    ]
    total = int(rows[0].total) if rows else 0
    note = "Several symbols share this name; pass `path` to pick one." if total > 1 else None
    if not rows and args.symbol_id is not None:
        note = (
            "That symbol id is no longer in the index, because the repository was updated "
            "after it was returned. Look the symbol up again by name with search_symbols."
        )
    return ReadSymbolOutput(total=total, items=items, note=note)


REGISTRY.register(
    Tool(
        name="list_files",
        description=(
            "List the repository's files, in path order, with language, size, how many files "
            "import each, and criticality. Use it like `ls`: browse a directory with "
            "path_prefix instead of guessing paths."
        ),
        input_model=ListFilesInput,
        output_model=ListFilesOutput,
        handler=_list_files,
        cost="free",
        timeout_s=10,
    )
)

REGISTRY.register(
    Tool(
        name="list_symbols",
        description=(
            "Outline one file: its functions, classes and methods with their line ranges. "
            "Cheaper than reading the file when you only need its shape."
        ),
        input_model=ListSymbolsInput,
        output_model=ListSymbolsOutput,
        handler=_list_symbols,
        cost="free",
        timeout_s=10,
        emits_nodes=lambda out: touched(out.path) if out.items else None,
    )
)

REGISTRY.register(
    Tool(
        name="read_symbol",
        description=(
            "Read the full, line-numbered body of a function, class or method, by exact name "
            "or by id. Reads functions that are too long to appear whole in search results. "
            "If several symbols share a name, pass path to choose."
        ),
        input_model=ReadSymbolInput,
        output_model=ReadSymbolOutput,
        handler=_read_symbol,
        cost="free",
        timeout_s=10,
        emits_nodes=lambda out: touched(*(s.path for s in out.items)),
    )
)
