"""Command line entry point: read the configuration, connect, then proxy."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from illume_mcp.proxy import serve

DEFAULT_URL = "https://illume-api.tejasnasa.me"
"""The hosted API. ``/mcp`` is appended to it."""

TOKEN_ENV = "ILLUME_MCP_TOKEN"
MCP_PATH = "/mcp"
TOKEN_REJECTED = "Illume token invalid or revoked; create one in Settings."
EXIT_FAILURE = 1
EXIT_USAGE = 2


class LauncherError(Exception):
    """A failure the user can act on; the message is printed to stderr as is.

    Args:
        message: What to tell the user.
        reported: Whether the message has already been printed.
    """

    def __init__(self, message: str, *, reported: bool = False) -> None:
        super().__init__(message)
        self.reported = reported


def endpoint(url: str) -> str:
    """The MCP endpoint for an API base URL.

    Args:
        url: The API origin, or the full endpoint.

    Returns:
        ``url`` with exactly one trailing ``/mcp``.
    """
    base = url.rstrip("/")
    return base if base.endswith(MCP_PATH) else base + MCP_PATH


class _UnauthorizedWatch:
    """Notes whether the server ever answered 401.

    The SDK turns every HTTP error status into the same generic error, so the status
    has to be observed on the HTTP client itself.
    """

    def __init__(self) -> None:
        self.seen = False

    async def __call__(self, response: httpx2.Response) -> None:
        """Response hook: record a 401, and say so on stderr the first time."""
        if response.status_code == 401 and not self.seen:
            self.seen = True
            print(f"illume-mcp: {TOKEN_REJECTED}", file=sys.stderr, flush=True)


async def run(url: str, token: str) -> None:
    """Connect to the hosted server and proxy stdio to it.

    Args:
        url: The API origin or the full ``/mcp`` endpoint.
        token: The personal access token, sent as a bearer credential.

    Raises:
        LauncherError: If the token is refused or the server cannot be reached.
    """
    watch = _UnauthorizedWatch()
    http_client = httpx2.AsyncClient(
        event_hooks={"response": [watch]},
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx2.Timeout(30.0, read=300.0),
    )
    transport = streamable_http_client(endpoint(url), http_client=http_client)
    try:
        async with http_client, Client(transport, mode="legacy") as upstream:
            await serve(upstream)
    except Exception as exc:
        if watch.seen:
            raise LauncherError(TOKEN_REJECTED, reported=True) from None
        raise LauncherError(f"could not reach Illume at {url} ({type(exc).__name__})") from None


def main(argv: list[str] | None = None) -> None:
    """Run the launcher.

    Args:
        argv: The arguments after the program name; defaults to ``sys.argv``.
    """
    parser = argparse.ArgumentParser(
        prog="illume-mcp",
        description=(
            "Proxy a stdio MCP client to a hosted Illume server. "
            f"The token is read from the {TOKEN_ENV} environment variable."
        ),
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="Illume API URL (default: %(default)s)")
    args = parser.parse_args(argv)

    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        print(
            f"illume-mcp: set {TOKEN_ENV} to an Illume token (create one in Settings).",
            file=sys.stderr,
        )
        sys.exit(EXIT_USAGE)

    try:
        asyncio.run(run(args.url, token))
    except LauncherError as exc:
        if not exc.reported:
            print(f"illume-mcp: {exc}", file=sys.stderr)
        sys.exit(EXIT_FAILURE)
    except KeyboardInterrupt:
        pass
