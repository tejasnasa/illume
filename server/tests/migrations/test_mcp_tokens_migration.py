"""The migration that creates ``mcp_tokens``.

Runs on a scratch database for the same reason the agent-runs round trip does.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect

from tests.conftest import _existing_loggers_survive
from tests.migrations.test_agent_runs_migration import scratch_database  # noqa: F401

pytestmark = pytest.mark.migration

REVISION = "b7c8d9e0f1a2"
PARENT = "a3b4c5d6e7f8"
COLUMNS = {
    "id",
    "user_id",
    "name",
    "token_prefix",
    "token_hash",
    "created_at",
    "last_used_at",
    "expires_at",
    "revoked_at",
}


def table_exists(engine) -> bool:
    return "mcp_tokens" in inspect(engine).get_table_names()


def indexes(engine) -> dict[str, dict]:
    return {index["name"]: index for index in inspect(engine).get_indexes("mcp_tokens")}


def test_the_revision_follows_the_staleness_columns(alembic_config):
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(alembic_config)

    assert script.get_revision(REVISION).down_revision == PARENT


def test_upgrade_creates_the_table_and_downgrade_drops_it(alembic_config, scratch_database):  # noqa: F811
    from alembic import command

    engine = scratch_database
    with _existing_loggers_survive():
        command.upgrade(alembic_config, PARENT)
        assert not table_exists(engine)

        command.upgrade(alembic_config, REVISION)
        assert table_exists(engine)
        assert {c["name"] for c in inspect(engine).get_columns("mcp_tokens")} == COLUMNS
        found = indexes(engine)
        assert found["ix_mcp_tokens_token_hash"]["unique"]
        assert found["ix_mcp_tokens_token_hash"]["column_names"] == ["token_hash"]
        assert found["ix_mcp_tokens_user_id"]["column_names"] == ["user_id"]
        [fk] = inspect(engine).get_foreign_keys("mcp_tokens")
        assert fk["referred_table"] == "users"
        assert fk["options"]["ondelete"] == "CASCADE"

        command.downgrade(alembic_config, PARENT)
        assert not table_exists(engine)

        command.upgrade(alembic_config, REVISION)
        assert table_exists(engine)
