"""Fixtures for the launcher tests: a real backend on the test stack, with committed rows.

The launcher is exercised end to end, so the backend it talks to is the real API run by
uvicorn in a subprocess, not an in-process app. That backend reads committed rows, which
the server suite's rolled-back-transaction fixtures cannot provide. The module therefore
seeds its own user, token and repositories, and deletes the user (cascading the rest) on
teardown.

Nothing here may fall back to ``server/.env``, which points at the production database.
The environment is set explicitly for this process (before ``app`` is imported) and for
the backend subprocess, and both are refused unless the database is the test stack's and
``OPENROUTER_API_KEY`` is empty.

The tests share tables with the server suite, so they must not run alongside it. They are
run by their own pytest invocation, serially, after the server suite.
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

HERE = Path(__file__).resolve().parent
LAUNCHER_SRC = HERE.parent / "src"
SERVER_ROOT = HERE.parents[1] / "server"

TEST_DB_PORT = 5433
TEST_REDIS_PORT = 6380
READY_TIMEOUT_SECONDS = 60

# Every `Settings` field, set explicitly: an unset one is filled from `server/.env`.
# The generation and embedding endpoints point at a closed port so that nothing in
# these tests can reach a billed API.
BACKEND_ENV = {
    "DATABASE_URL": f"postgresql+asyncpg://illume:test@localhost:{TEST_DB_PORT}/illume_test",
    "SYNC_DATABASE_URL": f"postgresql://illume:test@localhost:{TEST_DB_PORT}/illume_test",
    "REDIS_URL": f"redis://localhost:{TEST_REDIS_PORT}/0",
    "SECRET_KEY": "test-secret-key-not-for-production",
    "ACCESS_TOKEN_EXPIRE_MINUTES": "1440",
    "FRONTEND_URL": "http://localhost:3000",
    "ENVIRONMENT": "development",
    "GITHUB_CLIENT_ID": "test-github-client-id",
    "GITHUB_CLIENT_SECRET": "test-github-client-secret",
    "GITHUB_REDIRECT_URL": "http://localhost:8000/api/v1/auth/github/callback",
    "DOMAIN": "localhost",
    "OPENAI_API_KEY": "stub-key-not-a-credential",
    "OPENAI_BASE_URL": "http://127.0.0.1:9/v1",
    "AI_MODEL": "gpt-4o-mini",
    "AI_API_KEY": "stub-key-not-a-credential",
    "AI_BASE_URL": "http://127.0.0.1:9/v1",
    "OPENROUTER_API_KEY": "",
    "RESEND_API_KEY": "re_test_key_not_a_real_credential",
    "CONTACT_TO_EMAIL": "operator@example.com",
    "CONTACT_FROM_EMAIL": "contact@illume.tejasnasa.me",
    "OAUTH_REDIRECT_ALLOWLIST": "[]",
    "MOBILE_TOKEN_EXPIRE_MINUTES": str(60 * 24 * 90),
}

# This process imports `app` to seed the database, so it needs the same environment, and
# the launcher package for the in-process proxy tests.
os.environ.update(BACKEND_ENV)
sys.path.insert(0, str(SERVER_ROOT))
sys.path.insert(0, str(LAUNCHER_SRC))


def _assert_test_stack() -> None:
    """Refuse to continue unless the database is the test stack's and no AI key is set."""
    for key in ("DATABASE_URL", "SYNC_DATABASE_URL"):
        port = urlsplit(os.environ[key]).port
        assert port == TEST_DB_PORT, f"{key} must be the test database on port {TEST_DB_PORT}"
    assert urlsplit(os.environ["REDIS_URL"]).port == TEST_REDIS_PORT
    assert os.environ["OPENROUTER_API_KEY"] == "", "OPENROUTER_API_KEY must be empty"


_assert_test_stack()


@dataclass(frozen=True)
class Backend:
    """A running test backend and the credentials seeded for it.

    Attributes:
        url: The API origin, without ``/mcp``.
        token: A valid personal access token for the seeded user.
        repo_name: The name of one seeded repository.
        repo_number: That repository's number, as the tools address it.
    """

    url: str
    token: str
    repo_name: str
    repo_number: int


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _seed(email: str) -> tuple[str, str, int]:
    from app.core.database import AsyncSessionLocal, async_engine
    from app.services.mcp_tokens import create_token
    from tests.factories import make_user
    from tests.fixtures.agent_tools import seed_tool_repos

    try:
        async with AsyncSessionLocal() as db:
            user = await make_user(db, email=email, name="Launcher Test")
            repos = await seed_tool_repos(db, user)
            await db.commit()
            _, token = await create_token(db, user.id, "launcher-test", expires_in_days=1)
            return token, repos.a.repo.name, repos.a.repo.repo_number
    finally:
        await async_engine.dispose()


async def _delete_user(email: str) -> None:
    from sqlalchemy import delete, select

    from app.core.database import AsyncSessionLocal, async_engine
    from app.models.repository import Repository
    from app.models.user import User

    try:
        async with AsyncSessionLocal() as db:
            user_id = (await db.execute(select(User.id).where(User.email == email))).scalar()
            if user_id is None:
                return
            await db.execute(delete(Repository).where(Repository.user_id == user_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
    finally:
        await async_engine.dispose()


def _wait_until_ready(url: str, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"the test backend exited with code {process.returncode}")
        try:
            httpx.get(f"{url}/healthz", timeout=2)
            return
        except httpx.HTTPError:
            time.sleep(0.5)
    raise RuntimeError(f"the test backend did not answer within {READY_TIMEOUT_SECONDS}s")


@pytest.fixture(scope="module")
def backend() -> Iterator[Backend]:
    """Run the real API on a free port, with a committed user, token and repositories.

    The user has a unique email, so a run that was killed before teardown cannot collide
    with the next one. Teardown stops the server first, then deletes the user over a
    direct database connection (which cascades to the token and repositories).
    """
    email = f"launcher-{uuid.uuid4().hex[:12]}@example.com"
    token, repo_name, repo_number = asyncio.run(_seed(email))
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=SERVER_ROOT,
        env={**os.environ, **BACKEND_ENV},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_until_ready(url, process)
        yield Backend(url=url, token=token, repo_name=repo_name, repo_number=repo_number)
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=15)
        asyncio.run(_delete_user(email))


def launcher_env(token: str | None) -> dict[str, str]:
    """The environment for a launcher subprocess, with ``ILLUME_MCP_TOKEN`` set or removed.

    Args:
        token: The value of ``ILLUME_MCP_TOKEN``, or ``None`` to leave it unset.

    Returns:
        The environment mapping.
    """
    env = {k: v for k, v in os.environ.items() if k != "ILLUME_MCP_TOKEN"}
    env["PYTHONPATH"] = str(LAUNCHER_SRC)
    if token is not None:
        env["ILLUME_MCP_TOKEN"] = token
    return env
