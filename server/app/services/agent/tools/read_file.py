"""The ``read_file`` tool: whole files at the ingested commit, line-numbered and windowed."""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import unquote

from pydantic import Field, model_validator
from sqlalchemy import select

from app.models import File
from app.services.agent.tools.context import ToolContext
from app.services.agent.tools.lookup import touched
from app.services.agent.tools.output import ToolOutput, fence, numbered
from app.services.agent.tools.registry import REGISTRY, Tool, ToolInput
from app.services.github_files import fetch_file
from app.services.retrieval.citations import code_key

MAX_LINES_PER_CALL = 400

_DRIVE_LETTER = re.compile(r"^[A-Za-z]:")


class ReadFileInput(ToolInput):
    path: str = Field(
        min_length=1,
        max_length=1024,
        description="The file's path, relative to the repository root, as list_files shows it.",
    )
    start_line: int | None = Field(
        default=None, ge=1, description="First line to read. Omit to start at line 1."
    )
    end_line: int | None = Field(
        default=None,
        ge=1,
        description=f"Last line to read. At most {MAX_LINES_PER_CALL} lines are returned per call.",
    )

    @model_validator(mode="after")
    def _ordered(self) -> ReadFileInput:
        if self.start_line and self.end_line and self.end_line < self.start_line:
            raise ValueError("`end_line` must not be before `start_line`")
        return self


ReadStatus = Literal[
    "ok",
    "refused_path",
    "not_in_repository",
    "unavailable",
    "not_found",
    "rate_limited",
    "denied",
    "too_large",
    "binary",
    "out_of_range",
]


class ReadFileOutput(ToolOutput):
    status: ReadStatus
    path: str
    message: str = ""
    start_line: int | None = None
    end_line: int | None = None
    total_lines: int | None = None
    retry_after: int | None = None
    text: str = ""

    def render(self) -> str:
        if self.status != "ok":
            return self.message
        total = self.total_lines or 0
        if total == 0:
            return f"{self.path} is empty."
        start, end = self.start_line or 1, self.end_line or 0
        header = f"{self.path} lines {start:,} to {end:,} of {total:,}"
        header += f"; call again with start_line={end + 1} to continue." if end < total else "."
        return header + "\n" + fence(code_key(self.path, start, end), self.text)


def unsafe_path_reason(path: str) -> str | None:
    """Why a path must not be sent anywhere, or ``None`` when it looks safe.

    A path is checked as written and after URL-decoding twice, so an encoded
    traversal (``%2e%2e%2f``) is caught as well as a plain one.
    """
    for candidate in (path, unquote(path), unquote(unquote(path))):
        if "\x00" in candidate:
            return "contains a NUL byte"
        if "\\" in candidate:
            return "contains a backslash"
        if _DRIVE_LETTER.match(candidate):
            return "is an absolute path"
        if any(segment in ("", ".", "..") for segment in candidate.split("/")):
            return "is absolute or contains `.`, `..` or empty segments"
    return None


def _refuse(path: str, status: ReadStatus, message: str) -> ReadFileOutput:
    return ReadFileOutput(status=status, path=path, message=message)


async def _read_file(ctx: ToolContext, args: ReadFileInput) -> ReadFileOutput:
    # Nothing below this check may run for an unsafe path, the database included.
    if (reason := unsafe_path_reason(args.path)) is not None:
        return _refuse(
            args.path,
            "refused_path",
            f"Refused: the path {reason}. Give a path relative to the repository root, "
            "as list_files shows it.",
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
        return _refuse(
            args.path,
            "not_in_repository",
            f"`{args.path}` is not a file that was ingested from this repository. "
            "Find real paths with list_files or search_symbols.",
        )

    sha = ctx.repository.ingested_commit_sha
    if not sha:
        return _refuse(
            args.path, "unavailable", "This repository has no recorded commit to read files at."
        )

    fetched = await fetch_file(
        github_url=ctx.repository.github_url,
        commit_sha=sha,
        path=recorded,
        token=ctx.github_token,
    )
    if fetched.status != "ok" or fetched.content is None:
        return ReadFileOutput(
            status=fetched.status,
            path=recorded,
            message=fetched.message,
            retry_after=fetched.retry_after,
        )

    lines = fetched.content.splitlines()
    total = len(lines)
    start = args.start_line or 1
    if start > max(total, 1):
        return _refuse(
            recorded,
            "out_of_range",
            f"`{recorded}` has {total:,} lines; start_line {start:,} is past the end.",
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


REGISTRY.register(
    Tool(
        name="read_file",
        description=(
            "Read a file's text, line-numbered, exactly as it was at the ingested commit. "
            "Use it for what the symbol tools cannot show: imports, constants, module-level "
            "code, configuration and documentation files. At most "
            f"{MAX_LINES_PER_CALL} lines come back per call; the result says where to continue. "
            "Only files that ingestion recorded can be read, up to 2 MB, and not binary files."
        ),
        input_model=ReadFileInput,
        output_model=ReadFileOutput,
        handler=_read_file,
        cost="network",
        timeout_s=30,
        emits_nodes=lambda out: touched(out.path) if out.status == "ok" else None,
    )
)
