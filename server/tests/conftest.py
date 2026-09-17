"""
Shared fixtures for the backend test suite.

The environment is configured at the top of this module, *before* any ``app.*``
import, and that ordering is load-bearing. ``app/core/config.py`` instantiates
``settings`` at import time, ``app/core/database.py`` builds both engines at module
scope from those settings, and ``app/core/celery.py`` constructs the Celery app on
import. Importing anything under ``app`` therefore binds the database URLs
permanently.

A regular fixture is too late to change them: by the time fixtures execute, this
module has already imported the application. Point at the test database here or the
suite silently runs against the developer's real data.
"""

import os
from contextlib import contextmanager

# --- Environment bootstrap. Must precede every `app.*` import below. ---
TEST_DB_URL = "postgresql+asyncpg://illume:test@localhost:5433/illume_test"
TEST_SYNC_DB_URL = "postgresql://illume:test@localhost:5433/illume_test"
TEST_REDIS_URL = "redis://localhost:6380/0"

os.environ.update(
    {
        "DATABASE_URL": TEST_DB_URL,
        "SYNC_DATABASE_URL": TEST_SYNC_DB_URL,
        "REDIS_URL": TEST_REDIS_URL,
        "SECRET_KEY": "test-secret-key-not-for-production",
        "OPENAI_API_KEY": "test-openai-key",
        "AI_MODEL": "gpt-4o-mini",
        "ACCESS_TOKEN_EXPIRE_MINUTES": "1440",
        "FRONTEND_URL": "http://localhost:3000",
        "ENVIRONMENT": "development",
        "GITHUB_CLIENT_ID": "test-github-client-id",
        "GITHUB_CLIENT_SECRET": "test-github-client-secret",
        "GITHUB_REDIRECT_URL": "http://localhost:8000/api/v1/auth/github/callback",
        # Required by Settings but absent from `.env.example`.
        # A bare hostname, not a URL: this value is passed straight through as the
        # cookie `Domain` attribute, and a scheme or port there is not a valid cookie
        # domain.
        "DOMAIN": "localhost",
    }
)

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from alembic import command  # noqa: E402

SERVER_ROOT = Path(__file__).resolve().parents[1]


def pytest_addoption(parser):
    """Add the golden-file regeneration flag."""
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help=(
            "Rewrite golden files with the current output instead of comparing. Review the "
            "diff before committing -- see tests/fixtures/golden/__init__.py."
        ),
    )


@pytest.fixture(scope="session")
def update_golden(request) -> bool:
    """True when the run was asked to rewrite golden files."""
    return bool(request.config.getoption("--update-golden"))


def pytest_configure(config):
    """Seed the test environment before collection reaches any test module."""
    for key, value in list(os.environ.items()):
        if key.startswith(("DATABASE_URL", "SYNC_DATABASE_URL", "REDIS_URL")):
            assert "5433" in value or "6380" in value, (
                f"{key} does not point at the test stack ({value!r}). "
                "Start it with: docker compose -f docker-compose.test.yml up -d"
            )


@pytest.fixture(scope="session")
def alembic_config() -> Config:
    """Alembic config rooted at the server package, targeting the test database."""
    cfg = Config(str(SERVER_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    return cfg


@contextmanager
def _existing_loggers_survive():
    """
    Stop Alembic from disabling every logger the test session has already created.

    `alembic/env.py` calls `logging.config.fileConfig(alembic.ini)`, and `fileConfig`
    defaults to `disable_existing_loggers=True`: it sets `disabled = True` on every
    logger currently in `loggerDict`. Because the suite imports `app.*` before any test
    touches the database, the first migration disables every application logger -- and
    `Logger.isEnabledFor` short-circuits to False for a disabled logger, so any
    `caplog` assertion later in the session silently captures nothing.

    The failure is order-dependent and looks like a broken test rather than a logging
    problem, so the flag is forced off here rather than left to chance. `env.py` re-runs
    on every `upgrade`, so patching the module attribute is picked up by its
    `from logging.config import fileConfig`.
    """
    import logging.config

    original = logging.config.fileConfig

    def patched(*args, **kwargs):
        kwargs["disable_existing_loggers"] = False
        return original(*args, **kwargs)

    logging.config.fileConfig = patched
    try:
        yield
    finally:
        logging.config.fileConfig = original


@pytest.fixture(scope="session")
def migrated_db(alembic_config: Config) -> None:
    """
    Bring the test database to head once per session.

    Under xdist this fixture runs once *per worker*, so several workers can race to
    migrate the same database. Losing that race raises, but it is not a real failure:
    another worker reached head first. Treat "already at head" as success.
    """
    try:
        with _existing_loggers_survive():
            command.upgrade(alembic_config, "head")
    except Exception:
        current = _current_revision(alembic_config)
        if current != _head_revision(alembic_config):
            raise
        # Another worker migrated it first; nothing left to do.


def _head_revision(alembic_config: Config) -> str | None:
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(alembic_config).get_current_head()


def _current_revision(alembic_config: Config) -> str | None:
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine

    engine = create_engine(TEST_SYNC_DB_URL)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def engine(migrated_db):
    """
    Async engine pointed at the test database.

    NullPool is deliberate: pytest-asyncio gives each test its own event loop, and a
    pooled asyncpg connection created on a finished loop raises on reuse. Connections
    are cheap enough here that not pooling is the right trade.
    """
    return create_async_engine(TEST_DB_URL, poolclass=NullPool)


@pytest.fixture
async def db_session(engine):
    """
    A session whose work is always rolled back.

    The session is bound to an outer transaction that is never committed, so any
    ``commit()`` inside application code only releases a savepoint. Tests cannot
    observe each other's rows.
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
def app(db_session):
    """The FastAPI application with its database dependency overridden."""
    from app.core.database import get_async_db
    from app.main import app as fastapi_app

    async def _override():
        yield db_session

    fastapi_app.dependency_overrides[get_async_db] = _override
    yield fastapi_app
    fastapi_app.dependency_overrides.clear()


@pytest.fixture
async def client(app):
    """HTTP client that talks to the app in-process, without a live server."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


@pytest.fixture
async def redis_client():
    """Async Redis client pointed at the test instance."""
    import redis.asyncio as aioredis

    client = aioredis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()
