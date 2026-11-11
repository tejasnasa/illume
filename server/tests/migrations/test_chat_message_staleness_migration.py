"""The migration that adds the staleness columns to ``chat_messages``.

Runs on a scratch database for the same reason the agent-runs round trip does.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect

from tests.conftest import _existing_loggers_survive
from tests.migrations.test_agent_runs_migration import scratch_database  # noqa: F401

pytestmark = pytest.mark.migration

REVISION = "a3b4c5d6e7f8"
PARENT = "f2a3b4c5d6e7"
COLUMNS = {
    "answered_commit_sha": "VARCHAR",
    "cited_paths": "JSONB",
    "stale_at": "TIMESTAMP",
    "stale_paths": "JSONB",
    "stale_commit_sha": "VARCHAR",
}


def chat_columns(engine) -> dict[str, dict]:
    return {column["name"]: column for column in inspect(engine).get_columns("chat_messages")}


def test_the_revision_is_the_head_and_follows_the_drop_of_verification(alembic_config):
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(alembic_config)

    assert script.get_revision(REVISION).down_revision == PARENT
    assert script.get_current_head() == REVISION


def test_upgrade_adds_the_columns_and_downgrade_drops_them(alembic_config, scratch_database):  # noqa: F811
    from alembic import command

    engine = scratch_database
    with _existing_loggers_survive():
        command.upgrade(alembic_config, PARENT)
        assert not set(COLUMNS) & set(chat_columns(engine))

        command.upgrade(alembic_config, REVISION)
        added = chat_columns(engine)
        for name, kind in COLUMNS.items():
            assert added[name]["nullable"] is True
            assert str(added[name]["type"]).startswith(kind)

        command.downgrade(alembic_config, PARENT)
        assert not set(COLUMNS) & set(chat_columns(engine))

        command.upgrade(alembic_config, REVISION)
        assert set(COLUMNS) <= set(chat_columns(engine))
