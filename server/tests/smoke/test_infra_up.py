"""Postgres (with pgvector) and Redis are reachable.

Fails with an actionable message rather than a connection traceback, because the
usual cause is simply that the test stack is not running.
"""

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.smoke

START_HINT = (
    "Test infrastructure is not reachable. Start it with:\n"
    "    docker compose -f docker-compose.test.yml up -d"
)


async def test_postgres_is_reachable(engine):
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - re-raised with guidance below
        pytest.fail(f"{START_HINT}\n\nOriginal error: {exc}")

    assert result.scalar() == 1


async def test_pgvector_extension_is_installed(engine):
    """The Embedding model uses Vector(1536); migrations fail without pgvector."""
    async with engine.connect() as connection:
        result = await connection.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )

    assert result.scalar() == "vector", "pgvector extension is missing from the test database"


async def test_redis_is_reachable(redis_client):
    try:
        pong = await redis_client.ping()
    except Exception as exc:  # noqa: BLE001 - re-raised with guidance below
        pytest.fail(f"{START_HINT}\n\nOriginal error: {exc}")

    assert pong is True
