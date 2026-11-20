"""A tool registry whose ``read_file`` reads from the harness clone instead of GitHub.

The product's ``read_file`` fetches from api.github.com at the ingested commit with the owner's
token. Without a token that is 60 requests an hour, after which the tool answers ``unavailable``
and the agent arms quietly degrade. The registry built here is identical to the product's, in the
same order, except that ``read_file`` takes its text from the clone at the base commit: no
network, deterministic, and the same text GitHub would have served.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

from sqlalchemy import select

from app.models import File
from app.services.agent.tools import REGISTRY
from app.services.agent.tools.context import ToolContext
from app.services.agent.tools.output import numbered
from app.services.agent.tools.read_file import (
    MAX_LINES_PER_CALL,
    ReadFileInput,
    ReadFileOutput,
    unsafe_path_reason,
)
from app.services.agent.tools.registry import ToolRegistry
from app.services.github_files import BINARY_SNIFF_BYTES, MAX_FILE_BYTES
from evals.mining import clones

READ_FILE = "read_file"


def build_clone_registry(clone: Path, base_commit: str) -> ToolRegistry:
    """The product's tools, with ``read_file`` reading from ``clone`` at ``base_commit``.

    ``read_file`` keeps the product's name, description, input and output models and flags. Its
    handler behaves as the product's does (same path safety check, same check that the file was
    ingested, same windowing, numbering and statuses) except that the text comes from
    :func:`evals.mining.clones.show_file`. A file the database lists but the clone does not hold
    is reported as ``unavailable``, so a mismatch between the corpus and the clone is counted and
    flagged like any other unreadable file rather than passing as a plain miss.

    Args:
        clone: The harness clone of the repository.
        base_commit: The commit the repository was ingested at.

    Returns:
        A new registry; the product's own is not modified.
    """
    registry = ToolRegistry()
    for tool in REGISTRY:
        registry.register(
            replace(tool, handler=_clone_reader(clone, base_commit))
            if tool.name == READ_FILE
            else tool
        )
    return registry


def _clone_reader(clone: Path, base_commit: str):
    async def read_file(ctx: ToolContext, args: ReadFileInput) -> ReadFileOutput:
        # Nothing below this check may run for an unsafe path, the database included.
        if (reason := unsafe_path_reason(args.path)) is not None:
            return ReadFileOutput(
                status="refused_path",
                path=args.path,
                message=(
                    f"Refused: the path {reason}. Give a path relative to the repository root, "
                    "as list_files shows it."
                ),
            )

        async with ctx.session_factory() as db:
            recorded = (
                await db.execute(
                    select(File.path).where(
                        File.repository_id == ctx.repository.id, File.path == args.path
                    )
                )
            ).scalar_one_or_none()
        if recorded is None:
            return ReadFileOutput(
                status="not_in_repository",
                path=args.path,
                message=(
                    f"`{args.path}` is not a file that was ingested from this repository. "
                    "Find real paths with list_files or search_symbols."
                ),
            )

        content = await asyncio.to_thread(clones.show_file, clone, base_commit, recorded)
        if content is None:
            return ReadFileOutput(
                status="unavailable",
                path=recorded,
                message=f"`{recorded}` is not in the clone at commit {base_commit[:8]}.",
            )
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            return ReadFileOutput(
                status="too_large",
                path=recorded,
                message=(
                    f"The file is over {MAX_FILE_BYTES:,} bytes; the limit is "
                    f"{MAX_FILE_BYTES:,}. Use read_symbol or grep_code to reach the part you need."
                ),
            )
        if "\x00" in content[:BINARY_SNIFF_BYTES]:
            return ReadFileOutput(
                status="binary",
                path=recorded,
                message="The file is binary and cannot be shown as text.",
            )

        lines = content.splitlines()
        total = len(lines)
        start = args.start_line or 1
        if start > max(total, 1):
            return ReadFileOutput(
                status="out_of_range",
                path=recorded,
                message=f"`{recorded}` has {total:,} lines; start_line {start:,} is past the end.",
            )
        end = min(args.end_line or total, start + MAX_LINES_PER_CALL - 1, total)
        window = "\n".join(lines[start - 1 : end])
        return ReadFileOutput(
            status="ok",
            path=recorded,
            start_line=start,
            end_line=end,
            total_lines=total,
            text=numbered(window, start),
        )

    return read_file


__all__ = ["READ_FILE", "build_clone_registry"]
