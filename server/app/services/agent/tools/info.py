"""Tools that report what ingestion learned: file facts, the glossary, the overview."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.models import CodeOwner, File, GlossaryEntry, OnboardingGuide, Repository
from app.services.agent.tools.context import ToolContext
from app.services.agent.tools.lookup import find_file, no_such_file, touched
from app.services.agent.tools.output import ListOutput, ToolOutput, excerpt, fence
from app.services.agent.tools.registry import REGISTRY, Tool, ToolInput
from app.services.retrieval.channels.grep import escape_like
from app.services.retrieval.citations import code_key

_GLOSSARY_LIMIT = 10
_OVERVIEW_CRITICAL_FILES = 10
_CONTRIBUTORS_SHOWN = 5


# --- get_file_info ------------------------------------------------------------------


class FileInfoInput(ToolInput):
    path: str = Field(min_length=1, max_length=1024, description="The file's path.")


class Contributor(BaseModel):
    name: str
    percentage: float | None


class FileInfoOutput(ToolOutput):
    found: bool
    path: str
    language: str | None = None
    loc: int | None = None
    criticality: str | None = None
    criticality_reasons: list[str] = []
    fan_in: int = 0
    fan_out: int = 0
    has_tests: bool = False
    change_frequency: float | None = None
    last_modified: str | None = None
    primary_owner: str | None = None
    contributors: list[Contributor] = []
    bus_factor: int | None = None
    is_knowledge_silo: bool | None = None
    reading_order_position: int | None = None
    reading_note: str | None = None

    def render(self) -> str:
        if not self.found:
            return self.note_line()
        lines = [
            f"language: {self.language or 'unknown'}, {self.loc or 0} lines",
            f"criticality: {self.criticality or 'unscored'}"
            + (f" ({'; '.join(self.criticality_reasons)})" if self.criticality_reasons else ""),
            f"imported by {self.fan_in} files, imports {self.fan_out} files",
            f"has tests: {'yes' if self.has_tests else 'no'}",
        ]
        if self.change_frequency is not None:
            lines.append(f"change frequency: {self.change_frequency:g}")
        if self.last_modified:
            lines.append(f"last modified: {self.last_modified}")
        if self.primary_owner:
            others = ", ".join(
                f"{c.name} ({c.percentage:g}%)" if c.percentage is not None else c.name
                for c in self.contributors
            )
            silo = " (knowledge silo)" if self.is_knowledge_silo else ""
            lines.append(f"owner: {self.primary_owner}, bus factor {self.bus_factor}{silo}")
            if others:
                lines.append(f"contributors: {others}")
        if self.reading_order_position is not None:
            lines.append(f"reading order: #{self.reading_order_position}")
        if self.reading_note:
            lines.append(f"why read it: {self.reading_note}")
        return fence(code_key(self.path), "\n".join(lines), label="file facts")


async def _get_file_info(ctx: ToolContext, args: FileInfoInput) -> FileInfoOutput:
    async with ctx.session_factory() as db:
        ref = await find_file(db, ctx.repository.id, args.path)
        if ref is None:
            return FileInfoOutput(found=False, path=args.path, note=no_such_file(args.path))
        file = (
            await db.execute(
                select(File).where(File.id == ref.id, File.repository_id == ctx.repository.id)
            )
        ).scalar_one()
        owner = (
            await db.execute(select(CodeOwner).where(CodeOwner.file_id == ref.id))
        ).scalar_one_or_none()
        reading_order = (
            await db.execute(
                select(OnboardingGuide.reading_order).where(
                    OnboardingGuide.repository_id == ctx.repository.id
                )
            )
        ).scalar_one_or_none()

    position, note = None, None
    for entry in reading_order or []:
        if isinstance(entry, dict) and entry.get("path") == file.path:
            position, note = entry.get("position"), entry.get("annotation") or None
            break

    contributors = [
        Contributor(name=str(c.get("name", "")), percentage=c.get("percentage"))
        for c in ((owner.contributors if owner else None) or [])[:_CONTRIBUTORS_SHOWN]
        if isinstance(c, dict)
    ]
    return FileInfoOutput(
        found=True,
        path=file.path,
        language=file.language,
        loc=file.loc,
        criticality=file.criticality,
        criticality_reasons=[str(r) for r in (file.criticality_reasons or [])],
        fan_in=file.fan_in or 0,
        fan_out=file.fan_out or 0,
        has_tests=bool(file.has_tests),
        change_frequency=file.change_frequency,
        last_modified=file.git_last_modified.date().isoformat() if file.git_last_modified else None,
        primary_owner=owner.primary_owner if owner else None,
        contributors=contributors,
        bus_factor=owner.bus_factor if owner else None,
        is_knowledge_silo=owner.is_knowledge_silo if owner else None,
        reading_order_position=position,
        reading_note=note,
    )


# --- get_glossary -------------------------------------------------------------------


class GlossaryInput(ToolInput):
    term: str = Field(
        min_length=1, max_length=200, description="The term, or part of it, to look up."
    )


class GlossaryItem(BaseModel):
    name: str
    definition: str
    file_path: str | None
    line_number: int | None


class GlossaryOutput(ListOutput):
    items: list[GlossaryItem]

    def render(self) -> str:
        if not self.items:
            return self.note_line() + "0 glossary entries matched. Try search_symbols."
        blocks = [self.note_line() + self.count_line("glossary entries")]
        for item in self.items:
            where = f"  ({item.file_path}:{item.line_number})" if item.file_path else ""
            key = (
                code_key(item.file_path, item.line_number, item.line_number)
                if item.file_path and item.line_number
                else code_key(item.file_path)
                if item.file_path
                else "tool:get_glossary"
            )
            blocks.append(fence(key, f"{item.name}{where}\n{item.definition}", label="glossary"))
        return "\n\n".join(blocks)


async def _get_glossary(ctx: ToolContext, args: GlossaryInput) -> GlossaryOutput:
    query = (
        select(
            GlossaryEntry.name,
            GlossaryEntry.definition,
            GlossaryEntry.file_path,
            GlossaryEntry.line_number,
            func.count().over().label("total"),
        )
        .where(
            GlossaryEntry.repository_id == ctx.repository.id,
            GlossaryEntry.name.ilike(f"%{escape_like(args.term)}%", escape="\\"),
        )
        .order_by(func.lower(GlossaryEntry.name) != args.term.lower(), GlossaryEntry.name)
        .limit(_GLOSSARY_LIMIT)
    )
    async with ctx.session_factory() as db:
        rows = (await db.execute(query)).all()
    return GlossaryOutput(
        total=int(rows[0].total) if rows else 0,
        items=[
            GlossaryItem(
                name=r.name,
                definition=r.definition,
                file_path=r.file_path,
                line_number=r.line_number,
            )
            for r in rows
        ],
    )


# --- get_overview -------------------------------------------------------------------


class NoInput(ToolInput):
    pass


class CriticalFileEntry(BaseModel):
    path: str
    criticality: str
    reasons: list[str]
    fan_in: int


class OverviewOutput(ToolOutput):
    name: str
    narrative: str | None
    tech_stack: dict[str, Any]
    entry_points: list[str]
    critical_files: list[CriticalFileEntry]
    critical_total: int

    def render(self) -> str:
        parts = [f"Repository: {self.name}"]
        if self.narrative:
            parts.append(self.narrative)
        if self.tech_stack:
            parts.append("Detected stack: " + json.dumps(self.tech_stack, sort_keys=True))
        if self.entry_points:
            parts.append("Entry points: " + ", ".join(self.entry_points))
        if self.critical_files:
            rows = [
                f"{c.path}  {c.criticality}  fan-in {c.fan_in}"
                + (f"  ({'; '.join(c.reasons[:3])})" if c.reasons else "")
                for c in self.critical_files
            ]
            parts.append(
                f"{len(self.critical_files)} of {self.critical_total} critical files:\n"
                + "\n".join(rows)
            )
        if not self.narrative and not self.critical_files:
            parts.append("No architecture brief has been generated for this repository yet.")
        return fence("tool:get_overview", "\n\n".join(parts), label="overview")


async def _get_overview(ctx: ToolContext, args: NoInput) -> OverviewOutput:
    async with ctx.session_factory() as db:
        repo = (
            await db.execute(select(Repository).where(Repository.id == ctx.repository.id))
        ).scalar_one()
        guide = (
            await db.execute(
                select(OnboardingGuide.architecture_brief, OnboardingGuide.critical_files).where(
                    OnboardingGuide.repository_id == ctx.repository.id
                )
            )
        ).first()
        name, summary = repo.name, repo.architecture_summary
        stack, entries = repo.detected_stack, repo.entry_points

    brief: dict[str, Any] = (guide.architecture_brief if guide else None) or {}
    critical: list[Any] = (guide.critical_files if guide else None) or []
    narrative = brief.get("narrative") or summary
    entry_points: Any = brief.get("entry_points") or entries or []
    return OverviewOutput(
        name=name,
        narrative=excerpt(narrative, 4000) if narrative else None,
        tech_stack=brief.get("tech_stack") or stack or {},
        entry_points=[str(e) for e in (entry_points if isinstance(entry_points, list) else [])],
        critical_files=[
            CriticalFileEntry(
                path=str(c.get("path", "")),
                criticality=str(c.get("criticality", "")),
                reasons=[str(r) for r in c.get("reasons", [])],
                fan_in=int(c.get("fan_in", 0)),
            )
            for c in critical[:_OVERVIEW_CRITICAL_FILES]
            if isinstance(c, dict)
        ],
        critical_total=len(critical),
    )


REGISTRY.register(
    Tool(
        name="get_file_info",
        description=(
            "Facts about one file: criticality and why, how many files import it and how many "
            "it imports, who owns it and whether that is a single person, whether it has "
            "tests, how often and how recently it changes, and where it sits in the reading "
            "order. Use it to judge how risky or central a file is."
        ),
        input_model=FileInfoInput,
        output_model=FileInfoOutput,
        handler=_get_file_info,
        cost="free",
        timeout_s=10,
        emits_nodes=lambda out: touched(out.path) if out.found else None,
    )
)

REGISTRY.register(
    Tool(
        name="get_glossary",
        description=(
            "Look up project terms in the glossary generated for this repository. Returns "
            "definitions of the domain concepts and key symbols whose names contain the term."
        ),
        input_model=GlossaryInput,
        output_model=GlossaryOutput,
        handler=_get_glossary,
        cost="free",
        timeout_s=10,
    )
)

REGISTRY.register(
    Tool(
        name="get_overview",
        description=(
            "The repository at a glance: the architecture summary, detected tech stack, entry "
            "points and the most critical files. Call it first for broad questions about what "
            "the project is or how it is organised."
        ),
        input_model=NoInput,
        output_model=OverviewOutput,
        handler=_get_overview,
        cost="free",
        timeout_s=10,
    )
)
