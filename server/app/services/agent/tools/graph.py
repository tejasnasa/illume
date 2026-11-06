"""Tools that follow the import graph and the co-change history between files."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import File
from app.services.agent.tools.context import ToolContext
from app.services.agent.tools.lookup import find_file, no_such_file, paths_of, touched
from app.services.agent.tools.output import ListOutput, ToolOutput, fence
from app.services.agent.tools.registry import REGISTRY, Tool, ToolInput
from app.services.file_graph import query_neighbours_async
from app.services.retrieval.channels.cochange import cochanged_files

Direction = Literal["importers", "importees"]

_COCHANGE_POOL = 200


# --- get_importers / get_importees ------------------------------------------------


class NeighboursInput(ToolInput):
    path: str = Field(min_length=1, max_length=1024, description="The file's path.")
    limit: int = Field(default=30, ge=1, le=100, description="How many files to return.")


class Neighbour(BaseModel):
    path: str
    weight: int
    language: str | None
    fan_in: int


class NeighboursOutput(ListOutput):
    path: str
    direction: Direction
    items: list[Neighbour]

    def render(self) -> str:
        verb = "import" if self.direction == "importers" else "are imported by"
        if not self.items:
            return self.note_line() + f"0 files {verb} {self.path}."
        rows = [f"{n.path}  weight {n.weight}  fan-in {n.fan_in}" for n in self.items]
        header = self.count_line(f"files that {verb} {self.path}")
        body = fence(f"tool:get_{self.direction}", "\n".join(rows), label="listing")
        return self.note_line() + header + " (weight = number of imports)\n" + body


async def _fan_in_and_language(
    db: AsyncSession, repository_id: UUID, ids: list[UUID]
) -> dict[UUID, tuple[str | None, int]]:
    rows = await db.execute(
        select(File.id, File.language, File.fan_in).where(
            File.repository_id == repository_id, File.id.in_(ids)
        )
    )
    return {row.id: (row.language, row.fan_in or 0) for row in rows}


async def _neighbours(
    ctx: ToolContext, args: NeighboursInput, direction: Direction
) -> NeighboursOutput:
    async with ctx.session_factory() as db:
        file = await find_file(db, ctx.repository.id, args.path)
        if file is None:
            return NeighboursOutput(
                path=args.path, direction=direction, total=0, items=[], note=no_such_file(args.path)
            )
        rows = await query_neighbours_async(db, ctx.repository.id, [file.id], direction=direction)
        ids = [neighbour for _, neighbour, _ in rows]
        paths = await paths_of(db, ctx.repository.id, ids)
        facts = await _fan_in_and_language(db, ctx.repository.id, ids)
    ranked = sorted(
        (row for row in rows if row[1] in paths), key=lambda row: (-row[2], paths[row[1]])
    )
    return NeighboursOutput(
        path=file.path,
        direction=direction,
        total=len(ranked),
        items=[
            Neighbour(
                path=paths[neighbour],
                weight=weight,
                language=facts[neighbour][0],
                fan_in=facts[neighbour][1],
            )
            for _, neighbour, weight in ranked[: args.limit]
        ],
    )


async def _get_importers(ctx: ToolContext, args: NeighboursInput) -> NeighboursOutput:
    return await _neighbours(ctx, args, "importers")


async def _get_importees(ctx: ToolContext, args: NeighboursInput) -> NeighboursOutput:
    return await _neighbours(ctx, args, "importees")


def _neighbour_nodes(out: NeighboursOutput):
    return touched(out.path, *(n.path for n in out.items), action="neighbours")


# --- find_path --------------------------------------------------------------------


class FindPathInput(ToolInput):
    source: str = Field(min_length=1, max_length=1024, description="The starting file's path.")
    target: str = Field(min_length=1, max_length=1024, description="The file to reach.")
    max_depth: int = Field(
        default=4, ge=1, le=6, description="The most import steps to follow (1 to 6)."
    )


class FindPathOutput(ToolOutput):
    found: bool
    hops: int | None = None
    direction: Literal["source_imports_target", "target_imports_source"] | None = None
    path: list[str] = []

    def render(self) -> str:
        if not self.found:
            return self.note_line() or "No import path found."
        if self.direction == "target_imports_source":
            meaning = "each file is imported by the next"
        else:
            meaning = "each file imports the next"
        chain = " -> ".join(self.path)
        body = fence("tool:find_path", chain, label="import path")
        return f"{self.hops} hops ({meaning}):\n{body}"


async def _shortest(
    db: AsyncSession,
    repository_id: UUID,
    start: UUID,
    goal: UUID,
    direction: Direction,
    max_depth: int,
) -> list[UUID] | None:
    """The shortest chain of imports from ``start`` to ``goal``, or ``None``."""
    parents: dict[UUID, UUID | None] = {start: None}
    frontier = {start}
    for _ in range(max_depth):
        rows = await query_neighbours_async(db, repository_id, frontier, direction=direction)
        frontier = set()
        for seed, neighbour, _ in rows:
            if neighbour not in parents:
                parents[neighbour] = seed
                frontier.add(neighbour)
        if goal in parents:
            chain = [goal]
            while (parent := parents[chain[-1]]) is not None:
                chain.append(parent)
            return chain[::-1]
        if not frontier:
            return None
    return None


async def _find_path(ctx: ToolContext, args: FindPathInput) -> FindPathOutput:
    async with ctx.session_factory() as db:
        source = await find_file(db, ctx.repository.id, args.source)
        target = await find_file(db, ctx.repository.id, args.target)
        for given, found in ((args.source, source), (args.target, target)):
            if found is None:
                return FindPathOutput(found=False, note=no_such_file(given))
        assert source is not None and target is not None
        if source.id == target.id:
            return FindPathOutput(
                found=True, hops=0, direction="source_imports_target", path=[source.path]
            )

        forward = await _shortest(
            db, ctx.repository.id, source.id, target.id, "importees", args.max_depth
        )
        # A chain the other way only matters if it is shorter than the one found.
        reverse_depth = args.max_depth if forward is None else len(forward) - 2
        backward = (
            await _shortest(db, ctx.repository.id, target.id, source.id, "importees", reverse_depth)
            if reverse_depth >= 1
            else None
        )
        chain, direction = (forward, "source_imports_target")
        if backward is not None:
            chain, direction = (backward[::-1], "target_imports_source")
        if chain is None:
            return FindPathOutput(
                found=False,
                note=(
                    f"No import path between these files within {args.max_depth} steps, "
                    "in either direction."
                ),
            )
        paths = await paths_of(db, ctx.repository.id, chain)
    return FindPathOutput(
        found=True,
        hops=len(chain) - 1,
        direction=direction,  # type: ignore[arg-type]
        path=[paths[file_id] for file_id in chain],
    )


# --- get_cochanged ------------------------------------------------------------------


class CochangedInput(ToolInput):
    path: str = Field(min_length=1, max_length=1024, description="The file's path.")
    k: int = Field(default=10, ge=1, le=50, description="How many files to return.")


class Partner(BaseModel):
    path: str
    together: int
    jaccard: float


class CochangedOutput(ListOutput):
    path: str
    items: list[Partner]

    def render(self) -> str:
        if not self.items:
            return self.note_line() + f"No file changes together with {self.path} often enough."
        rows = [f"{p.path}  together {p.together}  jaccard {p.jaccard:.2f}" for p in self.items]
        header = self.count_line(f"files that change with {self.path}")
        body = fence("tool:get_cochanged", "\n".join(rows), label="listing")
        return self.note_line() + header + " (jaccard = share of their commits in common)\n" + body


async def _get_cochanged(ctx: ToolContext, args: CochangedInput) -> CochangedOutput:
    async with ctx.session_factory() as db:
        file = await find_file(db, ctx.repository.id, args.path)
        if file is None:
            return CochangedOutput(path=args.path, total=0, items=[], note=no_such_file(args.path))
        partners = await cochanged_files(db, ctx.repository.id, file.id, _COCHANGE_POOL)
    return CochangedOutput(
        path=file.path,
        total=len(partners),
        items=[
            Partner(path=p.path, together=p.together, jaccard=round(p.jaccard, 4))
            for p in partners[: args.k]
        ],
    )


REGISTRY.register(
    Tool(
        name="get_importers",
        description=(
            "List the files that import a file, strongest first. Use it to see what depends "
            "on a file and what a change to it could affect. Re-export files are looked "
            "through, so you get the real importers."
        ),
        input_model=NeighboursInput,
        output_model=NeighboursOutput,
        handler=_get_importers,
        cost="free",
        timeout_s=10,
        emits_nodes=_neighbour_nodes,
    )
)

REGISTRY.register(
    Tool(
        name="get_importees",
        description=(
            "List the files that a file imports, strongest first. Use it to see what a file "
            "depends on. Re-export files are looked through."
        ),
        input_model=NeighboursInput,
        output_model=NeighboursOutput,
        handler=_get_importees,
        cost="free",
        timeout_s=10,
        emits_nodes=_neighbour_nodes,
    )
)

REGISTRY.register(
    Tool(
        name="find_path",
        description=(
            "Find the shortest chain of imports connecting two files, trying both directions. "
            "Answers how one part of the code reaches another. Reports when there is none "
            "within max_depth steps."
        ),
        input_model=FindPathInput,
        output_model=FindPathOutput,
        handler=_find_path,
        cost="free",
        timeout_s=20,
        emits_nodes=lambda out: touched(*out.path, action="path") if out.found else None,
    )
)

REGISTRY.register(
    Tool(
        name="get_cochanged",
        description=(
            "List the files that tend to change in the same commits as a file. Shows hidden "
            "coupling that imports do not: files you will probably need to edit together."
        ),
        input_model=CochangedInput,
        output_model=CochangedOutput,
        handler=_get_cochanged,
        cost="free",
        timeout_s=10,
        emits_nodes=lambda out: touched(out.path, *(p.path for p in out.items)),
    )
)
