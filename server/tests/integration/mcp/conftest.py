"""Fixtures that serve a fresh MCP server per test, bound to the test's transaction.

The app-level ``client`` fixture cannot drive ``/mcp``: ``ASGITransport`` never
runs the lifespan, so the global server's session manager is not running, and the
global server opens sessions from the real engine, outside the test transaction.
So each test builds its own server with :func:`build_mcp`, bound to
``session_factory_for`` the test's connection, and serves it from a small
Starlette app wired the way the API is: the same mount, the same bare-path
rewrite, and the real ``AuthMiddleware`` in front.

The session manager and the SDK client both hold anyio task groups, which must be
entered and exited by the same task. pytest-asyncio may run a fixture's setup and
teardown in different tasks, so each is held open by a task of its own.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import fakeredis
import fakeredis.aioredis
import httpx
import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server
from starlette.applications import Starlette

from app.mcp.server import MCP_PATH, build_mcp, install_mcp
from app.middleware.auth import AuthMiddleware
from app.services.agent.session import RunKit
from app.services.mcp_tokens import create_token
from tests.factories import make_user
from tests.fixtures.agent_run import serialized
from tests.fixtures.agent_tools import session_factory_for

BASE_URL = "http://testserver"
MCP_URL = f"{BASE_URL}{MCP_PATH}"


@asynccontextmanager
async def in_own_task[T](context: AbstractAsyncContextManager[T]) -> AsyncIterator[T]:
    """Enter ``context`` in a dedicated task and keep it open until this block ends.

    Args:
        context: An async context manager whose enter and exit must share a task.

    Yields:
        Whatever ``context`` yields.
    """
    loop = asyncio.get_running_loop()
    entered: asyncio.Future[T] = loop.create_future()
    release = asyncio.Event()

    async def hold() -> None:
        try:
            async with context as value:
                entered.set_result(value)
                await release.wait()
        except BaseException as exc:
            if not entered.done():
                entered.set_exception(exc)
            raise

    task = asyncio.create_task(hold())
    try:
        yield await entered
    finally:
        release.set()
        await task


class McpApp:
    """A served MCP server and the app in front of it.

    Attributes:
        server: The low-level server :func:`build_mcp` returned.
        app: The Starlette app serving it at :data:`MCP_PATH`.
    """

    def __init__(self, server: Server[Any], app: Starlette) -> None:
        self.server = server
        self.app = app


class McpRedis:
    """The rate limiter's Redis for one test: a fake server that can be made to fail.

    Attributes:
        server: The fake server every client the factory hands out shares.
        down: When true, the factory raises, as an unreachable Redis would.
    """

    def __init__(self) -> None:
        self.server = fakeredis.FakeServer()
        self.down = False

    def factory(self) -> fakeredis.aioredis.FakeRedis:
        """A new client on the shared server, or a failure when ``down``."""
        if self.down:
            raise ConnectionError("redis is down")
        return fakeredis.aioredis.FakeRedis(server=self.server, decode_responses=True)

    def client(self) -> fakeredis.aioredis.FakeRedis:
        """A client for the test's own reads and writes, ignoring ``down``."""
        return fakeredis.aioredis.FakeRedis(server=self.server, decode_responses=True)


class RunKitBox:
    """The collaborators ``ask_illume`` runs use, replaceable while the server is up.

    Attributes:
        kit: Handed to every run started after it is set. The default is the
            production kit; a test that asks a question sets a scripted one first.
    """

    def __init__(self) -> None:
        self.kit = RunKit()


@pytest.fixture
def mcp_redis() -> McpRedis:
    """The fake Redis behind the server's rate limiter."""
    return McpRedis()


@pytest.fixture
def mcp_run_kit() -> RunKitBox:
    """The model, embedder and decider ``ask_illume`` runs use; set ``.kit`` in a test."""
    return RunKitBox()


@pytest.fixture
async def mcp_app(db_session, mcp_redis, mcp_run_kit) -> AsyncIterator[McpApp]:
    """A fresh MCP server bound to the test transaction, with its session manager running."""
    factory = session_factory_for(db_session.bind)
    server, asgi_app = build_mcp(
        session_factory=factory,
        redis_factory=mcp_redis.factory,
        # Runs write from concurrent tasks; on one shared connection they must not overlap.
        run_sessions=serialized(factory),
        kit_factory=lambda: mcp_run_kit.kit,
    )
    app = Starlette(lifespan=lambda _app: server.session_manager.run())
    app.add_middleware(AuthMiddleware)
    install_mcp(app, asgi_app)
    async with in_own_task(app.router.lifespan_context(app)):
        yield McpApp(server, app)


@pytest.fixture
async def mcp_user(db_session):
    """The user whose token ``auth_headers`` carries."""
    return await make_user(db_session)


@pytest.fixture
async def mcp_token(db_session, mcp_user) -> str:
    """A valid plaintext token for ``mcp_user``, created in the test transaction."""
    _, plaintext = await create_token(db_session, mcp_user.id, "test", 30)
    return plaintext


@pytest.fixture
def auth_headers(mcp_token: str) -> dict[str, str]:
    """The ``Authorization`` header a signed-in client sends."""
    return {"authorization": f"Bearer {mcp_token}"}


@pytest.fixture
async def mcp_http(mcp_app: McpApp) -> AsyncIterator[httpx.AsyncClient]:
    """A raw HTTP client for the MCP app, for checks below the protocol.

    It sends no token; add ``**auth_headers`` to a request to authenticate it.
    """
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mcp_app.app), base_url=BASE_URL
    ) as client:
        yield client


@pytest.fixture
def mcp_connect(mcp_app: McpApp) -> Callable[..., AbstractAsyncContextManager[Client]]:
    """Connect an SDK client to the MCP app.

    Without headers the client is unauthenticated; pass ``**auth_headers`` (or any
    other header) to sign in. ``mode="legacy"`` runs the ``initialize`` handshake
    that today's clients use; ``mode="auto"`` lets the SDK discover the newest
    protocol revision first.
    """

    @asynccontextmanager
    async def connect(*, mode: str = "legacy", **headers: str) -> AsyncIterator[Client]:
        http_client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=mcp_app.app), base_url=BASE_URL, headers=headers
        )
        client = Client(streamable_http_client(MCP_URL, http_client=http_client), mode=mode)
        async with http_client, in_own_task(client) as connected:
            # Every request checks the token on a session that shares the test's
            # connection. The handshake's trailing notification may still be in
            # flight, and cancelling it at teardown would race the connection
            # closing; a completed round trip guarantees it is done.
            await connected.list_tools()
            yield connected

    return connect


@pytest.fixture
async def mcp_client(mcp_connect, auth_headers) -> AsyncIterator[Client]:
    """A signed-in SDK client that has completed ``initialize`` against a fresh server."""
    async with mcp_connect(**auth_headers) as client:
        yield client
