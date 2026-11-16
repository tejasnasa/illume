"""The MCP server: its tools, its HTTP transport, and how it is mounted in the API.

The server is built on the SDK's low-level ``Server`` rather than ``MCPServer``,
because tools here carry hand-written input schemas and set ``structuredContent``
and ``isError`` themselves; ``MCPServer`` derives a tool's schema from a Python
signature and validates arguments against that.

The transport is stateless Streamable HTTP: every POST is served on its own, so
there are no sessions to keep, nothing is lost on a restart and no sticky routing
is needed. Responses are SSE streams, which is what lets a long call send
progress notifications and keep-alive pings, and what turns a client disconnect
into a cancellation of the running handler. A short call still answers with one
SSE event and closes.

Everything that reads the database takes its sessions from the
``session_factory`` handed to :func:`build_mcp`, never from the module-level
engine, so a test can bind the whole server to its own transaction.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import mcp_types as types
from mcp.server import Server, ServerRequestContext
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.applications import Starlette
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings

MCP_PATH = "/mcp"
"""Where the server is mounted. The public URL is exactly this, with no trailing slash."""

SERVER_NAME = "illume"

_LOCAL_HOSTS = ["localhost", "127.0.0.1", "[::1]"]


def _api_host_names(url: str) -> list[str]:
    """The ``Host`` header values a request to the API at ``url`` can carry.

    A client omits the port from ``Host`` when it is the scheme's default, so a URL
    without an explicit port yields the bare host name, and one with a port yields
    ``host:port``.

    Args:
        url: Any absolute URL on the API's origin.

    Returns:
        The allowed ``Host`` values, or an empty list when ``url`` has no host.
    """
    parts = urlsplit(url)
    if not parts.hostname:
        return []
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    return [f"{host}:{parts.port}"] if parts.port else [host]


def _origin(url: str) -> str | None:
    """The browser ``Origin`` of ``url`` (scheme, host and port), or ``None`` without a host."""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc.rpartition('@')[2]}"


def _allowed_hosts() -> list[str]:
    # The OAuth callback is the one configured URL that points at the API itself;
    # `DOMAIN` is the cookie domain, which may be a parent of the API host.
    hosts = _api_host_names(settings.GITHUB_REDIRECT_URL)
    if settings.ENVIRONMENT != "production":
        hosts += _LOCAL_HOSTS + [f"{host}:*" for host in _LOCAL_HOSTS] + ["testserver"]
    return list(dict.fromkeys(hosts))


def _allowed_origins() -> list[str]:
    origins = [_origin(settings.FRONTEND_URL), _origin(settings.GITHUB_REDIRECT_URL)]
    if settings.ENVIRONMENT != "production":
        origins += [f"http://{host}:*" for host in _LOCAL_HOSTS]
    return list(dict.fromkeys(origin for origin in origins if origin))


MCP_ALLOWED_HOSTS: list[str] = _allowed_hosts()
"""``Host`` values the endpoint answers to; anything else is refused with 421."""

MCP_ALLOWED_ORIGINS: list[str] = _allowed_origins()
"""Browser origins allowed to call the endpoint. A request with no ``Origin`` (any
non-browser client) is allowed; a foreign one is refused with 403."""

TRANSPORT_SECURITY = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=MCP_ALLOWED_HOSTS,
    allowed_origins=MCP_ALLOWED_ORIGINS,
)

ToolHandler = Callable[[ServerRequestContext[Any], dict[str, Any]], Awaitable[types.CallToolResult]]


@dataclass(frozen=True)
class McpTool:
    """One tool as the server lists and calls it.

    Attributes:
        definition: What ``tools/list`` advertises, including the input schema.
        handler: Called with the request context and the call's arguments.
    """

    definition: types.Tool
    handler: ToolHandler


def _text_result(text: str, *, is_error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)], is_error=is_error
    )


async def _ping(ctx: ServerRequestContext[Any], arguments: dict[str, Any]) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text="pong")], structured_content={"ok": True}
    )


PING = McpTool(
    definition=types.Tool(
        name="ping",
        title="Ping",
        description="Check that the Illume MCP server is reachable. Returns 'pong'.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        annotations=types.ToolAnnotations(read_only_hint=True, idempotent_hint=True),
    ),
    handler=_ping,
)


def build_mcp(
    *, session_factory: async_sessionmaker[AsyncSession]
) -> tuple[Server[Any], Starlette]:
    """Build the MCP server and the ASGI app that serves it.

    Each call returns a new server with its own session manager. The manager's
    ``run()`` can be entered only once, so whoever serves the app enters
    ``server.session_manager.run()`` exactly once for its lifetime: the API's
    lifespan in production, a test fixture in the suite.

    Args:
        session_factory: The only source of database sessions for the server. The
            ping tool reads nothing, so nothing holds it yet.

    Returns:
        The low-level server and an ASGI app to mount at :data:`MCP_PATH`. The
        app answers at its own root, so the mount point is the public URL.
    """
    tools: dict[str, McpTool] = {PING.definition.name: PING}

    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[tool.definition for tool in tools.values()])

    async def call_tool(
        ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        tool = tools.get(params.name)
        if tool is None:
            return _text_result(f"Unknown tool: {params.name}", is_error=True)
        return await tool.handler(ctx, params.arguments or {})

    def input_schema(name: str) -> dict[str, Any] | None:
        tool = tools.get(name)
        return None if tool is None else tool.definition.input_schema

    server: Server[Any] = Server(
        SERVER_NAME,
        get_tool_input_schema=input_schema,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )
    asgi_app = server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=False,
        transport_security=TRANSPORT_SECURITY,
    )
    return server, asgi_app


class McpBarePathMiddleware:
    """Serve ``POST /mcp`` in place, instead of redirecting it to ``/mcp/``.

    A Starlette ``Mount`` only matches paths below its prefix, so the bare path
    would get a 307 to the slashed one. Behind a TLS-terminating proxy that
    redirect points at ``http://`` (uvicorn runs without proxy headers), and the
    SDK client refuses to follow a downgrade. Rewriting the path before routing
    keeps the public URL exactly :data:`MCP_PATH`.

    Args:
        app: The ASGI app to wrap.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Rewrite the bare mount path to the slashed one, then pass the request on."""
        if scope["type"] == "http" and scope["path"] == MCP_PATH:
            scope = {**scope, "path": f"{MCP_PATH}/", "raw_path": f"{MCP_PATH}/".encode()}
        await self.app(scope, receive, send)


def install_mcp(app: Starlette, asgi_app: Starlette) -> None:
    """Mount the MCP app at :data:`MCP_PATH` and make the bare path answer in place.

    Args:
        app: The application to mount into (the API, or a test's small app).
        asgi_app: The app returned by :func:`build_mcp`.
    """
    app.mount(MCP_PATH, asgi_app)
    app.add_middleware(McpBarePathMiddleware)
