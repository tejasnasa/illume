"""The proxy: a stdio MCP server whose every handler forwards to the hosted server.

Nothing here interprets a request or a result. Names, schemas, annotations,
structured content and ``isError`` pass through as the upstream produced them, so
the local tool list is the hosted tool list by construction.
"""

from __future__ import annotations

from typing import Any

import mcp_types as types
from mcp import Client
from mcp.server import Server, ServerRequestContext
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

SERVER_NAME = "illume"


def build_server(upstream: Client) -> tuple[Server[Any], InitializationOptions]:
    """Build the local server and the initialize result it will serve.

    The capabilities, instructions and server identity are read from the upstream
    connection, so the local client sees what it would have seen connecting to the
    hosted server directly.

    Args:
        upstream: A connected client for the hosted server.

    Returns:
        The server, and the options that make its ``initialize`` result mirror the
        upstream one.
    """
    session = upstream.session

    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return await session.list_tools(params=params)

    async def call_tool(
        ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        # Reporting is a no-op when the local client sent no progress token, so the
        # callback can be passed unconditionally.
        async def forward_progress(
            progress: float, total: float | None, message: str | None
        ) -> None:
            await ctx.session.report_progress(progress, total, message)

        return await upstream.call_tool(
            params.name,
            params.arguments,
            progress_callback=forward_progress,
        )

    async def list_resources(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListResourcesResult:
        return await session.list_resources(params=params)

    async def list_resource_templates(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListResourceTemplatesResult:
        return await session.list_resource_templates(params=params)

    async def read_resource(
        ctx: ServerRequestContext[Any], params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult:
        return await upstream.read_resource(params.uri)

    async def list_prompts(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListPromptsResult:
        return await session.list_prompts(params=params)

    async def get_prompt(
        ctx: ServerRequestContext[Any], params: types.GetPromptRequestParams
    ) -> types.GetPromptResult:
        return await upstream.get_prompt(params.name, params.arguments)

    info = upstream.server_info
    server: Server[Any] = Server(
        info.name if info is not None else SERVER_NAME,
        version=info.version if info is not None else "",
        title=info.title if info is not None else None,
        instructions=upstream.instructions,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_list_resources=list_resources,
        on_list_resource_templates=list_resource_templates,
        on_read_resource=read_resource,
        on_list_prompts=list_prompts,
        on_get_prompt=get_prompt,
    )
    options = InitializationOptions(
        server_name=server.name,
        server_version=server.version,
        title=server.title,
        capabilities=upstream.server_capabilities,
        instructions=upstream.instructions,
    )
    return server, options


async def serve(upstream: Client) -> None:
    """Serve the local client over stdio until it disconnects.

    Args:
        upstream: A connected client for the hosted server.
    """
    server, options = build_server(upstream)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options)
