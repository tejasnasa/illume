"""The shape of a tool as the MCP server lists and calls it."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import mcp_types as types
from mcp.server import ServerRequestContext

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


def text_result(
    text: str, *, structured: Any = None, is_error: bool = False
) -> types.CallToolResult:
    """Build a tool result carrying one text block and, optionally, structured data.

    Args:
        text: What the model reads.
        structured: A JSON-serialisable value for ``structuredContent``.
        is_error: Whether the call failed in a way the model can act on.

    Returns:
        The result to hand back from a tool handler.
    """
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        structured_content=structured,
        is_error=is_error,
    )
