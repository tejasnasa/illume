"""Progress notifications pass through the proxy to a client that asked for them."""

from __future__ import annotations

from typing import Any

import mcp_types as types
from illume_mcp.proxy import build_server
from mcp import Client
from mcp.server import Server, ServerRequestContext


def fake_hosted_server() -> Server[Any]:
    """A server with one tool that reports three progress steps, then answers."""

    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="slow", input_schema={"type": "object", "properties": {}})]
        )

    async def call_tool(
        ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        for step in (1.0, 2.0, 3.0):
            await ctx.session.report_progress(step, 3.0, f"step {int(step)}")
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="done")],
            structured_content={"steps": 3},
        )

    return Server("hosted", on_list_tools=list_tools, on_call_tool=call_tool)


async def test_progress_reaches_a_client_that_asked_for_it() -> None:
    seen: list[tuple[float, float | None, str | None]] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        seen.append((progress, total, message))

    async with Client(fake_hosted_server()) as hosted:
        local_server, _ = build_server(hosted)
        async with Client(local_server) as local:
            result = await local.call_tool("slow", {}, progress_callback=on_progress)

    assert seen == [(1.0, 3.0, "step 1"), (2.0, 3.0, "step 2"), (3.0, 3.0, "step 3")]
    assert result.structured_content == {"steps": 3}
    assert not result.is_error


async def test_a_call_without_a_progress_token_still_succeeds() -> None:
    async with Client(fake_hosted_server()) as hosted:
        local_server, _ = build_server(hosted)
        async with Client(local_server) as local:
            result = await local.call_tool("slow", {})

    assert result.structured_content == {"steps": 3}
