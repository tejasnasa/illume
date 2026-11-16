"""Tools about the token owner and the repositories they have ingested."""

from __future__ import annotations

from typing import Any

import mcp_types as types
from mcp.server import ServerRequestContext
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.mcp.auth import current_user_id
from app.mcp.limits import RateLimiter
from app.mcp.tool import McpTool, text_result
from app.models.repository import Repository
from app.models.user import User

STATUS_CHOICES = ("ready", "all")


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _repo_entry(repo: Repository) -> dict[str, Any]:
    return {
        "repo": str(repo.repo_number),
        "number": repo.repo_number,
        "id": str(repo.id),
        "name": repo.name,
        "github_url": repo.github_url,
        "status": repo.status,
        "ingested_branch": repo.ingested_branch,
        "ingested_commit_sha": repo.ingested_commit_sha,
        "created_at": _iso(repo.created_at),
        "last_synced_at": _iso(repo.last_synced_at),
    }


def _repo_line(entry: dict[str, Any]) -> str:
    commit = (entry["ingested_commit_sha"] or "")[:8]
    snapshot = (
        f"{entry['ingested_branch'] or 'unknown branch'}@{commit}" if commit else "no snapshot"
    )
    return (
        f"- repo={entry['repo']}  {entry['name']}  <{entry['github_url']}>  "
        f"status={entry['status']}  {snapshot}"
    )


def build_account_tools(
    session_factory: async_sessionmaker[AsyncSession], limiter: RateLimiter | None = None
) -> list[McpTool]:
    """Build the tools that describe the caller and their repositories.

    Args:
        session_factory: Source of the database sessions the handlers use.
        limiter: When given, each call counts toward the user's per-minute limit.

    Returns:
        The ``whoami`` and ``list_repositories`` tools.
    """

    async def whoami(
        ctx: ServerRequestContext[Any], arguments: dict[str, Any]
    ) -> types.CallToolResult:
        user_id = current_user_id(ctx)
        if limiter is not None and (limited := await limiter.check_call(user_id)):
            return text_result(limited.message, is_error=True)
        async with session_factory() as db:
            email = await db.scalar(select(User.email).where(User.id == user_id))
            count = await db.scalar(
                select(func.count()).select_from(Repository).where(Repository.user_id == user_id)
            )
        data = {"email": email, "repositories_count": count or 0}
        return text_result(
            f"Authenticated as {email}, who has {data['repositories_count']} repositories.",
            structured=data,
        )

    async def list_repositories(
        ctx: ServerRequestContext[Any], arguments: dict[str, Any]
    ) -> types.CallToolResult:
        user_id = current_user_id(ctx)
        if limiter is not None and (limited := await limiter.check_call(user_id)):
            return text_result(limited.message, is_error=True)
        status = arguments.get("status", "ready")
        extra = sorted(set(arguments) - {"status"})
        if status not in STATUS_CHOICES or extra:
            problem = (
                f"unexpected argument(s): {', '.join(extra)}" if extra else f"status={status!r}"
            )
            return text_result(
                f"Invalid arguments ({problem}). `status` must be one of "
                f"{', '.join(repr(s) for s in STATUS_CHOICES)}; it defaults to 'ready'.",
                is_error=True,
            )

        user_id = current_user_id(ctx)
        query = select(Repository).where(Repository.user_id == user_id)
        if status == "ready":
            query = query.where(Repository.status == "ready")
        async with session_factory() as db:
            repos = (await db.scalars(query.order_by(Repository.repo_number))).all()

        entries = [_repo_entry(repo) for repo in repos]
        if entries:
            text = "Repositories (pass the `repo` value to other tools):\n" + "\n".join(
                _repo_line(entry) for entry in entries
            )
        elif status == "ready":
            text = (
                "No ready repositories. Use status='all' to include ones that are still ingesting."
            )
        else:
            text = "No repositories have been ingested yet."
        return text_result(text, structured={"repositories": entries})

    return [
        McpTool(
            definition=types.Tool(
                name="whoami",
                title="Who am I",
                description=(
                    "Return the email of the Illume account this token belongs to and how many "
                    "repositories it has. Use it to check that the connection works."
                ),
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                annotations=types.ToolAnnotations(
                    title="Who am I",
                    read_only_hint=True,
                    idempotent_hint=True,
                    open_world_hint=False,
                ),
            ),
            handler=whoami,
        ),
        McpTool(
            definition=types.Tool(
                name="list_repositories",
                title="List repositories",
                description=(
                    "List the repositories the user has ingested into Illume, with the `repo` "
                    "value to pass to every other repository tool, the GitHub URL, ingestion "
                    "status and the branch and commit the data reflects. Call this first. By "
                    "default only repositories that are ready to query are listed; pass "
                    "status='all' to include ones still ingesting or failed."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": list(STATUS_CHOICES),
                            "default": "ready",
                            "description": "'ready' (default) or 'all'.",
                        }
                    },
                    "additionalProperties": False,
                },
                annotations=types.ToolAnnotations(
                    title="List repositories",
                    read_only_hint=True,
                    idempotent_hint=True,
                    open_world_hint=False,
                ),
            ),
            handler=list_repositories,
        ),
    ]
