"""The resources: Illume's overview and reading order of a repository, as Markdown.

Resources are documents a user attaches to a conversation, addressed by URI. Two
templates are offered:

- ``illume://repo/{repo}/overview``: the architecture brief, tech stack, entry
  points and critical files;
- ``illume://repo/{repo}/reading-order``: the suggested order to read the files in.

``{repo}`` is a repository number, a UUID or ``owner/name`` (the slash may be
percent-encoded). It is resolved with :func:`resolve_repo` for the token owner, so
ownership and not-found behaviour are the same as for the tools. The list of
concrete resources is empty: the templates are the whole offer.

Text that came from the repository sits inside ``<source>`` fences, as in tool
results, so a client can tell it from Illume's own headings. A failure is a
JSON-RPC error, never a resource with an error message as its text.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import unquote

import mcp_types as types
from mcp import MCPError
from mcp.server import ServerRequestContext
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.services.agent.tools  # noqa: F401  (importing it registers every tool)
from app.mcp.auth import current_user_id
from app.mcp.context import build_tool_context
from app.mcp.limits import RateLimiter
from app.mcp.repos import McpRepoError, resolve_repo
from app.models.repository import Repository
from app.services.agent.tools.output import fence
from app.services.agent.tools.registry import REGISTRY
from app.services.onboarding_guide import ReadingOrderEntry, get_reading_order

MARKDOWN = "text/markdown"

OVERVIEW_TEMPLATE = "illume://repo/{repo}/overview"
READING_ORDER_TEMPLATE = "illume://repo/{repo}/reading-order"

_URI = re.compile(r"^illume://repo/(?P<repo>[^?#]+)/(?P<kind>overview|reading-order)$")

RESOURCE_TEMPLATES = [
    types.ResourceTemplate(
        name="overview",
        title="Illume overview",
        uri_template=OVERVIEW_TEMPLATE,
        description=(
            "The repository at a glance: the architecture summary, detected tech stack, "
            "entry points and the most critical files. {repo} is the repository number, "
            "UUID or owner/name."
        ),
        mime_type=MARKDOWN,
    ),
    types.ResourceTemplate(
        name="reading-order",
        title="Illume reading order",
        uri_template=READING_ORDER_TEMPLATE,
        description=(
            "The suggested order to read the repository's files in, each with a note on why. "
            "{repo} is the repository number, UUID or owner/name."
        ),
        mime_type=MARKDOWN,
    ),
]

_OVERVIEW_KEY = "tool:get_overview"


def render_overview(data: dict[str, Any]) -> str:
    """Render the ``get_overview`` output as Markdown.

    Args:
        data: The structured output of the ``get_overview`` tool.

    Returns:
        Markdown with Illume's headings outside and every piece of repository text
        inside a ``<source>`` fence.
    """

    def block(body: str) -> str:
        return fence(_OVERVIEW_KEY, body, label="overview")

    sections = [f"# Overview of {data.get('name', 'the repository')}"]
    if data.get("narrative"):
        sections.append("## Architecture\n\n" + block(data["narrative"]))
    else:
        sections.append(
            "## Architecture\n\nNo architecture brief has been generated for this repository yet."
        )
    if data.get("tech_stack"):
        lines = [f"{name}: {value}" for name, value in sorted(data["tech_stack"].items())]
        sections.append("## Tech stack\n\n" + block("\n".join(lines)))
    if data.get("entry_points"):
        sections.append(
            "## Entry points\n\n" + block("\n".join(f"- {entry}" for entry in data["entry_points"]))
        )
    critical = data.get("critical_files") or []
    if critical:
        lines = []
        for entry in critical:
            reasons = entry.get("reasons") or []
            why = f" ({'; '.join(reasons[:3])})" if reasons else ""
            lines.append(
                f"- {entry.get('path', '')}: {entry.get('criticality', '')}, "
                f"fan-in {entry.get('fan_in', 0)}{why}"
            )
        total = data.get("critical_total", len(critical))
        sections.append(
            f"## Critical files ({len(critical)} of {total})\n\n" + block("\n".join(lines))
        )
    return "\n\n".join(sections) + "\n"


def render_reading_order(repo_name: str, entries: list[ReadingOrderEntry]) -> str:
    """Render a reading order as Markdown.

    Args:
        repo_name: The repository's name.
        entries: The entries, in reading order.

    Returns:
        Markdown with one fenced list of position, path and annotation.
    """
    heading = f"# Reading order of {repo_name}"
    if not entries:
        return f"{heading}\n\nNo reading order has been generated for this repository yet.\n"
    lines = [
        f"{e.position}. {e.file_path}" + (f": {e.annotation}" if e.annotation else "")
        for e in entries
    ]
    body = fence("tool:reading_order", "\n".join(lines), label="reading order")
    return f"{heading}\n\n{body}\n"


def _error(code: int, message: str) -> MCPError:
    return MCPError(code=code, message=message)


def build_resource_handlers(
    session_factory: async_sessionmaker[AsyncSession], limiter: RateLimiter
) -> tuple[
    Callable[..., Awaitable[types.ListResourcesResult]],
    Callable[..., Awaitable[types.ListResourceTemplatesResult]],
    Callable[..., Awaitable[types.ReadResourceResult]],
]:
    """Build the three resource request handlers.

    Args:
        session_factory: Source of the sessions used to resolve the repository and
            to run the overview tool.
        limiter: Counts each read against the user's per-minute limit.

    Returns:
        The handlers for ``resources/list``, ``resources/templates/list`` and
        ``resources/read``, in that order.
    """

    async def list_resources(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=[])

    async def list_templates(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListResourceTemplatesResult:
        return types.ListResourceTemplatesResult(resource_templates=RESOURCE_TEMPLATES)

    async def render(db: AsyncSession, repo: Repository, kind: str) -> str:
        if kind == "reading-order":
            entries = await get_reading_order(db, repo.id)
            if entries is None:
                raise _error(
                    types.INVALID_PARAMS,
                    f"Repository {repo.name!r} has no reading order yet; its guide has not "
                    "been generated.",
                )
            return render_reading_order(repo.name, entries)

        # The overview reuses the tool's own queries and shaping.
        context = build_tool_context(repo, None, session_factory=session_factory)
        result = await REGISTRY.call("get_overview", {}, context)
        if result.status != "ok" or result.data is None:
            raise _error(types.INTERNAL_ERROR, f"Could not build the overview: {result.text}")
        return render_overview(result.data)

    async def read_resource(
        ctx: ServerRequestContext[Any], params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult:
        uri = str(params.uri)
        match = _URI.match(uri)
        if match is None:
            raise _error(
                types.INVALID_PARAMS,
                f"Unknown resource {uri!r}. Illume offers {OVERVIEW_TEMPLATE} and "
                f"{READING_ORDER_TEMPLATE}.",
            )
        user_id = current_user_id(ctx)

        if limited := await limiter.check_call(user_id):
            raise _error(types.INVALID_REQUEST, limited.message)

        async with session_factory() as db:
            try:
                repo = await resolve_repo(db, user_id, unquote(match["repo"]))
            except McpRepoError as error:
                raise _error(types.INVALID_PARAMS, error.message) from None
            text = await render(db, repo, match["kind"])

        return types.ReadResourceResult(
            contents=[types.TextResourceContents(uri=uri, mime_type=MARKDOWN, text=text)]
        )

    return list_resources, list_templates, read_resource
