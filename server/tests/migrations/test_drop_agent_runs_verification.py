"""The migration that drops ``agent_runs.verification``.

Runs on a scratch database for the same reason the agent-runs round trip does.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect

from tests.conftest import _existing_loggers_survive
from tests.migrations.test_agent_runs_migration import scratch_database  # noqa: F401

pytestmark = pytest.mark.migration

REVISION = "f2a3b4c5d6e7"
PARENT = "e1f2a3b4c5d6"


def run_columns(engine) -> dict[str, dict]:
    return {column["name"]: column for column in inspect(engine).get_columns("agent_runs")}


def test_the_revision_follows_the_agent_runs_revision(alembic_config):
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(alembic_config)

    assert script.get_revision(REVISION).down_revision == PARENT


def test_upgrade_drops_the_column_and_downgrade_restores_it(alembic_config, scratch_database):  # noqa: F811
    from alembic import command

    engine = scratch_database
    with _existing_loggers_survive():
        command.upgrade(alembic_config, PARENT)
        assert "verification" in run_columns(engine)

        command.upgrade(alembic_config, REVISION)
        assert "verification" not in run_columns(engine)

        command.downgrade(alembic_config, PARENT)
        restored = run_columns(engine)["verification"]
        assert restored["nullable"] is True
        assert restored["type"].__class__.__name__ == "JSONB"

        command.upgrade(alembic_config, REVISION)
        assert "verification" not in run_columns(engine)
