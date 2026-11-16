"""
Run the API on :8010 against the test stack, for poking the MCP endpoint by hand.

    uv run python scripts/mcp_dev.py            # migrate, seed, serve until Ctrl+C
    uv run python scripts/mcp_dev.py --cleanup  # only delete the seeded user

The API is started with **every** ``Settings`` field set in its environment, taken from
``serverEnv`` in ``client/e2e/env.ts`` (so the two harnesses cannot drift apart) plus the
fields that file leaves to their defaults. Overriding only the database and Redis URLs is
not enough: ``Settings`` falls back to ``server/.env`` for anything unset, and that file
points at the production database and carries real AI keys. The script refuses to start
unless the database is the test stack's (port 5433) and ``OPENROUTER_API_KEY`` is empty.

Every OpenAI-compatible URL points at ``scripts/openai_stub_server.py``, started here on
:8098 (the E2E suite owns :8099), so nothing reaches a billed API.

It migrates the test database and **commits** a user with the two-repository tool fixture,
then writes two gitignored files: ``.mcp-dev.json`` for ``claude -p --mcp-config``, carrying
a personal access token for the user as a bearer header, and ``.mcp-dev.cookie``, a session
JWT for the same user, for ``curl -b "access_token=$(cat .mcp-dev.cookie)"``. Neither value
is printed. The user is deleted on exit, cascading the repositories and the token, and the
files are removed; ``--cleanup`` does the same after a run that was killed before it could.

To stop a run gracefully, create the file ``.mcp-dev.stop`` in ``server/``: while serving,
the harness deletes it and shuts down normally, so cleanup runs. That is the way to stop it
on Windows, where a hard kill skips ``finally``.

Two limits, so a live check does not chase them: there is no GitHub stub, so ``read_file``
would call the real api.github.com; and the stub returns one fixed vector for every
embedding, so dense search over the hash-vector fixture returns noise.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

SERVER_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = SERVER_ROOT.parent
sys.path.insert(0, str(SERVER_ROOT))

API_PORT = 8010
STUB_PORT = 8098
TEST_DB_PORT = 5433
EMAIL = "mcp-dev@example.com"
MCP_CONFIG = SERVER_ROOT / ".mcp-dev.json"
SESSION_COOKIE = SERVER_ROOT / ".mcp-dev.cookie"
STOP_FILE = SERVER_ROOT / ".mcp-dev.stop"
READY_TIMEOUT_SECONDS = 60

# The fields `serverEnv` leaves out because their defaults are safe in the E2E stack.
# They are set here anyway: an unset field is one `server/.env` can fill.
EXTRA_ENV = {
    "OPENROUTER_API_KEY": "",
    "OAUTH_REDIRECT_ALLOWLIST": "[]",
    "MOBILE_TOKEN_EXPIRE_MINUTES": str(60 * 24 * 90),
}


def load_server_env() -> dict[str, str]:
    """Read ``serverEnv`` from ``client/e2e/env.ts`` with this harness's ports.

    Returns:
        Every ``Settings`` field, as strings.

    Raises:
        SystemExit: If Node cannot load the file, or the result misses a field.
    """
    script = (
        "const m = await import('./client/e2e/env.ts'); console.log(JSON.stringify(m.serverEnv))"
    )
    result = subprocess.run(
        ["node", "--no-warnings", "--input-type=module", "-e", script],
        cwd=REPO_ROOT,
        env={**os.environ, "E2E_API_PORT": str(API_PORT), "E2E_STUB_PORT": str(STUB_PORT)},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"could not read client/e2e/env.ts: {result.stderr.strip()}")
    return {**json.loads(result.stdout), **EXTRA_ENV}


def assert_safe(env: dict[str, str]) -> None:
    """Refuse to run against anything but the test stack, or with a billed key.

    Args:
        env: The environment the API will run with.

    Raises:
        SystemExit: If a ``Settings`` field is unset, the database is not the test
            stack's, or ``OPENROUTER_API_KEY`` is set.
    """
    from app.core.config import Settings

    missing = set(Settings.model_fields) - set(env)
    if missing:
        raise SystemExit(f"unset Settings fields would fall back to server/.env: {sorted(missing)}")
    for key in ("DATABASE_URL", "SYNC_DATABASE_URL"):
        if urlsplit(env[key]).port != TEST_DB_PORT:
            raise SystemExit(f"{key} is not the test database on port {TEST_DB_PORT}")
    if env["OPENROUTER_API_KEY"]:
        raise SystemExit("OPENROUTER_API_KEY must be empty")


def migrate() -> None:
    """Bring the test database to head."""
    from alembic.config import Config

    from alembic import command
    from app.core.config import settings

    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", settings.SYNC_DATABASE_URL)
    command.upgrade(config, "head")


async def delete_user() -> None:
    """Delete the harness user, and with it their repositories."""
    from sqlalchemy import delete, select

    from app.core.database import AsyncSessionLocal
    from app.models.repository import Repository
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        user_id = (await db.execute(select(User.id).where(User.email == EMAIL))).scalar()
        if user_id is None:
            return
        await db.execute(delete(Repository).where(Repository.user_id == user_id))
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()
    print(f"deleted {EMAIL} and their repositories")


async def seed() -> tuple[dict[str, int], str, str]:
    """Commit the harness user, their MCP token and the two tool repositories.

    Returns:
        Each repository's name mapped to its ``repo_number``, the plaintext MCP
        token, and a session JWT for the user.
    """
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token
    from app.services.mcp_tokens import create_token
    from tests.factories import make_user
    from tests.fixtures.agent_tools import seed_tool_repos

    async with AsyncSessionLocal() as db:
        user = await make_user(db, email=EMAIL, name="MCP Dev")
        repos = await seed_tool_repos(db, user)
        await db.commit()
        _, token = await create_token(db, user.id, "mcp-dev", expires_in_days=30)
        session = create_access_token(str(user.id))
        numbers = {seeded.repo.name: seeded.repo.repo_number for seeded in (repos.a, repos.b)}
        return numbers, token, session


async def reset_and_seed() -> tuple[dict[str, int], str, str]:
    """Replace any leftover harness user with a fresh seed, on one event loop."""
    from app.core.database import async_engine

    try:
        await delete_user()
        return await seed()
    finally:
        await async_engine.dispose()


async def cleanup() -> None:
    """Delete the harness user and the credential files, and release the engine."""
    from app.core.database import async_engine

    for path in (MCP_CONFIG, SESSION_COOKIE, STOP_FILE):
        path.unlink(missing_ok=True)
    try:
        await delete_user()
    finally:
        await async_engine.dispose()


def write_credentials(token: str, session: str) -> None:
    """Write the client config and the session cookie for the harness user.

    Args:
        token: The plaintext MCP token, sent as a bearer header.
        session: A session JWT, for hitting the cookie-authenticated API by hand.
    """
    config = {
        "mcpServers": {
            "illume": {
                "type": "http",
                "url": f"http://localhost:{API_PORT}/mcp",
                "headers": {"Authorization": f"Bearer {token}"},
            }
        }
    }
    MCP_CONFIG.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    SESSION_COOKIE.write_text(session, encoding="utf-8")
    print(f"wrote {MCP_CONFIG} and {SESSION_COOKIE}")


def start(args: list[str], env: dict[str, str]) -> subprocess.Popen:
    """Start ``python -m <args>`` from the server root with ``env``."""
    return subprocess.Popen([sys.executable, "-m", *args], cwd=SERVER_ROOT, env=env)


def wait_until_ready(url: str) -> None:
    """Block until ``url`` answers, or exit after :data:`READY_TIMEOUT_SECONDS`."""
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            httpx.get(url, timeout=2)
            return
        except httpx.HTTPError:
            time.sleep(0.5)
    raise SystemExit(f"{url} did not answer within {READY_TIMEOUT_SECONDS}s")


def serve(env: dict[str, str]) -> None:
    """Run the stub and the API until interrupted, then stop both."""
    process_env = {**os.environ, **env}
    stub = start(
        ["uvicorn", "--app-dir", "scripts", "openai_stub_server:app", "--port", str(STUB_PORT)],
        process_env,
    )
    api = start(["uvicorn", "app.main:app", "--port", str(API_PORT)], process_env)
    try:
        wait_until_ready(f"http://127.0.0.1:{STUB_PORT}/docs")
        wait_until_ready(f"http://127.0.0.1:{API_PORT}/healthz")
        print(f"API on http://localhost:{API_PORT}, MCP at http://localhost:{API_PORT}/mcp")
        while api.poll() is None and stub.poll() is None:
            if STOP_FILE.exists():
                STOP_FILE.unlink(missing_ok=True)
                print("stop file found, shutting down")
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for process in (api, stub):
            process.terminate()
        for process in (api, stub):
            process.wait(timeout=15)


def _interrupt(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


def main() -> None:
    """Check the environment, then clean up, or migrate, seed and serve."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--cleanup", action="store_true", help="only delete the seeded user")
    args = parser.parse_args()

    env = load_server_env()
    # Applied to this process before anything imports `app.core.config`, so the
    # migration and the seed read the same values the API will.
    os.environ.update(env)
    assert_safe(env)

    if args.cleanup:
        asyncio.run(cleanup())
        return

    migrate()
    # A stale stop file would end the run the moment it started.
    STOP_FILE.unlink(missing_ok=True)
    repos, token, session = asyncio.run(reset_and_seed())
    print(f"seeded {EMAIL}: {repos}")
    write_credentials(token, session)

    # A terminate from the outside should still clean up, not leave committed rows behind.
    signal.signal(signal.SIGTERM, _interrupt)
    try:
        serve(env)
    finally:
        asyncio.run(cleanup())


if __name__ == "__main__":
    main()
