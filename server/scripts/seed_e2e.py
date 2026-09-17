"""
Seed the E2E stack with a deterministic user and a fully-ingested repository.

Run against a live API and its database, not in-process:

    uv run python scripts/seed_e2e.py

The user is created **through the registration endpoint**, so the credential path the
browser will use is the one the API actually serves -- same hashing, same validation, same
cookie. Everything else is inserted directly with the test factories, because driving a
real ingestion would need GitHub, OpenAI, and a Celery worker, and would make the E2E
result depend on three external services being reachable and fast.

Two repositories are seeded, not one:

- ``seed-repo`` is the fixture every browsing spec reads. Nothing may mutate it.
- ``reingest-me`` exists so the re-ingest spec has a repository it is allowed to destroy.
  Re-ingest deletes the row and recreates it, cascading away every file, symbol, guide, and
  chat turn -- so it has to be a separate repository, or the specs would pass or fail
  depending on the order Playwright happened to run them in.

Idempotent: the user's repositories are deleted and rebuilt on every run, so a stale seed
never survives into a test. Safe to run against a dev database you do not mind losing the
``E2E_EMAIL`` user from -- and unsafe against one you do.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx

# Running this as a script puts `scripts/` on sys.path, not the server root, so `app.*`
# and `tests.*` are both unimportable without this.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alembic.config import Config  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from alembic import command  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal, async_engine  # noqa: E402
from app.models.repository import Repository  # noqa: E402
from app.models.user import User  # noqa: E402
from tests.factories import make_fully_ingested_repo  # noqa: E402

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
EMAIL = os.environ.get("E2E_EMAIL", "e2e@example.com")
PASSWORD = os.environ.get("E2E_PASSWORD", "correct-horse-1!")
NAME = os.environ.get("E2E_NAME", "E2E User")
OUTPUT = Path(os.environ.get("E2E_SEED_OUTPUT", "e2e-seed.json"))

PRIMARY_NAME = "seed-repo"
REINGEST_NAME = "reingest-me"

# The E2E stack shares the backend suite's database, and that suite supplies explicit
# `repo_number` values from a counter starting at 900_000. This seed leaves its rows
# behind on purpose, so it allocates from a lower band: an overlap would break an
# unrelated backend test with a `UniqueViolationError` several minutes into a run.
REPO_NUMBER_BASE = 800_000

READY_TIMEOUT_SECONDS = 60


def migrate() -> None:
    """
    Bring the E2E schema to head.

    The suite's own fixture does this once per session; the E2E stack has no such hook,
    and seeding into a schema that is one revision behind fails with a confusing column
    error. Running it here means "prepare the database" is a single command.
    """
    config = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", settings.SYNC_DATABASE_URL)
    command.upgrade(config, "head")
    print("schema is at head")


def wait_for_api() -> None:
    """
    Block until the API answers on `/healthz`.

    The web server and this script are started by the same job, so the first polls
    routinely land before uvicorn is listening. Failing here would look like a seeding
    bug rather than a race.
    """
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{BASE_URL}/healthz", timeout=2).status_code == 200:
                return
        except httpx.HTTPError as error:
            last_error = error
        time.sleep(0.5)
    raise SystemExit(f"API at {BASE_URL} did not become ready: {last_error}")


def register() -> None:
    """
    Register the E2E user through the public endpoint.

    A 400 means the address is already taken, which is expected when the previous run's
    user was not cleaned up -- the reset below happens first, so this is only reachable if
    two seeds race.
    """
    response = httpx.post(
        f"{BASE_URL}/api/v1/auth/register",
        json={"email": EMAIL, "name": NAME, "password": PASSWORD},
        timeout=10,
    )
    if response.status_code != 201:
        raise SystemExit(f"registration failed: {response.status_code} {response.text}")
    print(f"registered {EMAIL}")


async def reset_user() -> None:
    """Delete the E2E user and their repositories, so the seed is repeatable."""
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == EMAIL))).scalar_one_or_none()
        if user is None:
            return
        # Repositories first: the children hang off the repository, and deleting through
        # the ORM rather than relying on the FK's ON DELETE keeps this working regardless
        # of what the migrations actually emitted.
        await db.execute(delete(Repository).where(Repository.user_id == user.id))
        await db.execute(delete(User).where(User.id == user.id))
        await db.commit()
        print(f"removed the previous {EMAIL} and their repositories")


async def seed_repositories() -> list[dict]:
    """Insert both fixture repositories and return their identifying fields."""
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == EMAIL))).scalar_one_or_none()
        if user is None:
            raise SystemExit(f"{EMAIL} was not found after registration")

        seeded: list[dict] = []
        for offset, (name, file_count) in enumerate(((PRIMARY_NAME, 4), (REINGEST_NAME, 2))):
            repo, files = await make_fully_ingested_repo(
                db,
                user,
                name=name,
                file_count=file_count,
                repo_number=REPO_NUMBER_BASE + offset,
            )
            seeded.append(
                {
                    "name": repo.name,
                    "repo_id": str(repo.id),
                    "repo_num": repo.repo_number,
                    "file_count": len(files),
                    "github_url": repo.github_url,
                }
            )
            print(f"seeded {repo.name} (repo_num={repo.repo_number}, {len(files)} files)")

    return seeded


async def main() -> None:
    """Migrate, wait for the API, reset, register, and seed."""
    migrate()
    wait_for_api()
    await reset_user()
    register()
    seeded = await seed_repositories()

    artifact = {"base_url": BASE_URL, "email": EMAIL, "password": PASSWORD, "repos": seeded}
    OUTPUT.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.resolve()}")

    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
