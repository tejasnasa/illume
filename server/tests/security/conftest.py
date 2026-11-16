"""Fixtures shared with the MCP integration tests.

The MCP server fixtures are defined next to the tests that drive the protocol; the
security tests that exercise the same server import them here rather than copy them.
"""

from tests.integration.mcp.conftest import (  # noqa: F401
    auth_headers,
    mcp_app,
    mcp_client,
    mcp_connect,
    mcp_http,
    mcp_redis,
    mcp_run_kit,
    mcp_token,
    mcp_user,
)
