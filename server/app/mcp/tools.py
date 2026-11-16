"""The repository tools: Illume's agent tool registry, offered over MCP.

One MCP tool is registered for each entry in the agent's ``REGISTRY`` except
those in :data:`MCP_EXCLUDED`, so a tool added to the registry appears here
without further work. The registry does the work of a call: it validates the
arguments, runs the handler under its timeout and caps the text. This module
adds what MCP needs around that:

- a required ``repo`` argument, resolved to one of the caller's ready
  repositories before anything runs;
- a description written for an outside client rather than for Illume's own
  agent prompt;
- rate limits and one log line per call.
"""

from __future__ import annotations

import copy
import logging
import time
import uuid
from typing import Any

import mcp_types as types
from mcp.server import ServerRequestContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.services.agent.tools  # noqa: F401  (importing it registers every tool)
from app.mcp.auth import current_user_id
from app.mcp.context import build_tool_context
from app.mcp.limits import RateLimiter
from app.mcp.repos import McpRepoError, repo_argument, resolve_repo
from app.mcp.tool import McpTool, text_result
from app.models.user import User
from app.services.agent.tools.registry import REGISTRY, Tool
from app.services.llm_config import LLMConfig

logger = logging.getLogger(__name__)


MCP_EXCLUDED = frozenset({"finish"})
"""Registry tools that exist for Illume's own agent loop and mean nothing to an MCP client."""

REPO_DESCRIPTION = (
    "The repository to use: its number, its UUID, or owner/name, as listed by list_repositories."
)

_REPO_NOTE = "Pass `repo` to choose the repository."

TITLES: dict[str, str] = {
    "search_code": "Search code",
    "search_symbols": "Search symbols",
    "grep_code": "Grep code",
    "search_history": "Search history",
    "list_files": "List files",
    "list_symbols": "List symbols in a file",
    "read_symbol": "Read a symbol",
    "read_file": "Read a file",
    "get_importers": "Get importers",
    "get_importees": "Get importees",
    "find_path": "Find an import path",
    "get_cochanged": "Get co-changed files",
    "get_file_info": "Get file info",
    "get_glossary": "Look up the glossary",
    "get_overview": "Get the repository overview",
}

DESCRIPTION_OVERRIDES: dict[str, str] = {
    "search_code": (
        "Search the repository by meaning and by keyword. Returns the best matching code, "
        "files, commits, pull requests and README sections, each with a citation key. "
        "Start here for open questions; use search_symbols or grep_code when you know an "
        "exact name or string."
    ),
}
"""Descriptions that differ from the registry's. The rest are used as written."""

_OPEN_WORLD = frozenset({"read_file"})
"""Tools that reach outside Illume's own database (``read_file`` calls GitHub)."""


def exposed_tools() -> list[Tool[Any, Any]]:
    """The registry tools offered over MCP, in registration order."""
    return [t for t in REGISTRY if t.name not in MCP_EXCLUDED and t.expose_to_agent]


def mcp_description(tool: Tool[Any, Any]) -> str:
    """What an MCP client reads about ``tool``: its description and how to pick the repository."""
    return f"{DESCRIPTION_OVERRIDES.get(tool.name, tool.description)} {_REPO_NOTE}"


def mcp_input_schema(tool: Tool[Any, Any]) -> dict[str, Any]:
    """The tool's input schema with the required ``repo`` argument added.

    Args:
        tool: A registry tool.

    Returns:
        The model's JSON schema (not the strict-mode rewrite), with ``repo`` first
        among the properties and the required list.

    Raises:
        ValueError: If the tool already has an argument called ``repo``.
    """
    schema = copy.deepcopy(tool.input_model.model_json_schema())
    properties = schema.get("properties", {})
    if "repo" in properties:
        raise ValueError(f"tool {tool.name!r} already has a `repo` argument")
    schema["type"] = "object"
    schema["properties"] = {
        "repo": {"type": "string", "description": REPO_DESCRIPTION},
        **properties,
    }
    schema["required"] = ["repo", *schema.get("required", [])]
    schema["additionalProperties"] = False
    return schema


def _error(text: str) -> types.CallToolResult:
    return text_result(text, is_error=True)


def _is_keyless(row: Any) -> bool:
    """Whether the user has no AI key of their own (an unknown provider counts as none)."""
    try:
        return LLMConfig.from_user(row) is None
    except KeyError:
        return True


def build_repository_tools(
    session_factory: async_sessionmaker[AsyncSession], limiter: RateLimiter
) -> list[McpTool]:
    """Build one MCP tool for each exposed registry tool.

    Args:
        session_factory: Source of the sessions used to resolve the repository and
            handed to the tools for their own queries.
        limiter: Counts each call against the user's limits.

    Returns:
        The tools, in registry order.
    """

    def build(tool: Tool[Any, Any]) -> McpTool:
        async def handler(
            ctx: ServerRequestContext[Any], arguments: dict[str, Any]
        ) -> types.CallToolResult:
            started = time.perf_counter()
            user_id = current_user_id(ctx)
            repo_id: uuid.UUID | None = None

            def finish(
                result: types.CallToolResult, status: str, truncated: bool = False
            ) -> types.CallToolResult:
                elapsed = (time.perf_counter() - started) * 1000
                logger.info(
                    "mcp_tool user=%s repo=%s tool=%s status=%s ms=%.0f truncated=%s",
                    user_id,
                    repo_id or "-",
                    tool.name,
                    status,
                    elapsed,
                    truncated,
                )
                return result

            ref = repo_argument(arguments.get("repo"))
            if ref is None:
                return finish(
                    _error(
                        "Invalid arguments: `repo` is required: the "
                        "repository number, UUID or owner/name from list_repositories."
                    ),
                    "invalid_arguments",
                )
            remaining = {name: value for name, value in arguments.items() if name != "repo"}

            if limited := await limiter.check_call(user_id):
                return finish(_error(limited.message), "rate_limited")

            async with session_factory() as db:
                try:
                    repo = await resolve_repo(db, user_id, ref)
                except McpRepoError as error:
                    return finish(_error(error.message), "repo_error")
                repo_id = repo.id
                account = (
                    await db.execute(
                        select(
                            User.github_access_token,
                            User.ai_provider,
                            User.ai_api_key,
                            User.ai_model,
                        ).where(User.id == user_id)
                    )
                ).one_or_none()
            github_token = account.github_access_token if account else None
            keyless = _is_keyless(account) if account else True

            if limited := await limiter.check_repository_call(
                user_id, cost=tool.cost, keyless=keyless
            ):
                return finish(_error(limited.message), "rate_limited")

            tool_ctx = build_tool_context(repo, github_token, session_factory=session_factory)
            result = await REGISTRY.call(tool.name, remaining, tool_ctx)

            ok = result.status == "ok"
            return finish(
                text_result(
                    result.text if ok else f"[{result.status}] {result.text}",
                    structured=result.data if ok and isinstance(result.data, dict) else None,
                    is_error=not ok,
                ),
                result.status,
                result.truncated,
            )

        title = TITLES.get(tool.name, tool.name.replace("_", " ").capitalize())
        return McpTool(
            definition=types.Tool(
                name=tool.name,
                title=title,
                description=mcp_description(tool),
                input_schema=mcp_input_schema(tool),
                annotations=types.ToolAnnotations(
                    title=title,
                    read_only_hint=True,
                    idempotent_hint=True,
                    open_world_hint=tool.name in _OPEN_WORLD,
                ),
            ),
            handler=handler,
        )

    return [build(tool) for tool in exposed_tools()]
