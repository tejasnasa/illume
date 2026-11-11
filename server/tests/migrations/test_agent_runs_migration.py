"""The migration that adds ``agent_runs``, ``agent_steps`` and ``chat_messages.agent_run_id``.

Upgrading and downgrading the shared test database would pull the schema out from
under every other test running against it, so the round trip runs on a scratch
database created for the purpose and dropped afterwards.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, inspect, text

from app.core.config import settings
from tests.conftest import TEST_SYNC_DB_URL, _existing_loggers_survive

pytestmark = pytest.mark.migration

REVISION = "e1f2a3b4c5d6"
PARENT = "d0e1f2a3b4c5"


@pytest.fixture
def scratch_database(monkeypatch):
    """An empty database on the test server that Alembic is pointed at."""
    name = f"illume_roundtrip_{uuid.uuid4().hex[:10]}"
    admin = create_engine(TEST_SYNC_DB_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = TEST_SYNC_DB_URL.rsplit("/", 1)[0] + f"/{name}"
    monkeypatch.setattr(settings, "SYNC_DATABASE_URL", url)
    engine = create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def chat_columns(engine) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("chat_messages")}


def test_the_revision_follows_the_previous_one_on_a_single_line_of_history(alembic_config):
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(alembic_config)

    assert script.get_revision(REVISION).down_revision == PARENT
    assert REVISION in {r.revision for r in script.walk_revisions()}
    assert len(script.get_heads()) == 1


def test_upgrade_downgrade_and_upgrade_again(alembic_config, scratch_database):
    from alembic import command

    engine = scratch_database
    with _existing_loggers_survive():
        command.upgrade(alembic_config, PARENT)
        assert "agent_runs" not in tables(engine)
        assert "agent_run_id" not in chat_columns(engine)

        command.upgrade(alembic_config, REVISION)
        assert {"agent_runs", "agent_steps"} <= tables(engine)
        assert "agent_run_id" in chat_columns(engine)

        command.downgrade(alembic_config, PARENT)
        assert not {"agent_runs", "agent_steps"} & tables(engine)
        assert "agent_run_id" not in chat_columns(engine)

        command.upgrade(alembic_config, REVISION)
        assert {"agent_runs", "agent_steps"} <= tables(engine)


def test_the_upgrade_is_safe_to_run_twice(alembic_config, scratch_database):
    from alembic import command

    with _existing_loggers_survive():
        command.upgrade(alembic_config, REVISION)
        # Re-running the revision's body, as two workers reaching a fresh database would.
        from alembic.script import ScriptDirectory

        migration = ScriptDirectory.from_config(alembic_config).get_revision(REVISION).module
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        with scratch_database.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.upgrade()

    assert {"agent_runs", "agent_steps"} <= tables(scratch_database)


def test_the_schema_is_what_the_models_declare(alembic_config, scratch_database):
    from alembic import command

    with _existing_loggers_survive():
        command.upgrade(alembic_config, REVISION)

    inspector = inspect(scratch_database)
    runs = {c["name"]: c for c in inspector.get_columns("agent_runs")}
    steps = {c["name"]: c for c in inspector.get_columns("agent_steps")}
    assert {
        "id",
        "user_id",
        "repository_id",
        "chat_message_id",
        "question",
        "config",
        "config_hash",
        "status",
        "answer",
        "citations",
        "usage",
        "created_at",
    } <= set(runs)
    assert runs["chat_message_id"]["nullable"] is True
    assert runs["config"]["nullable"] is False
    assert {
        "run_id",
        "seq",
        "worker_id",
        "kind",
        "name",
        "payload",
        "tokens_in",
        "tokens_out",
        "latency_ms",
        "created_at",
    } <= set(steps)
    uniques = inspector.get_unique_constraints("agent_steps")
    assert [u["column_names"] for u in uniques] == [["run_id", "seq"]]


def test_the_foreign_keys_cascade_and_clear_as_designed(alembic_config, scratch_database):
    from alembic import command

    with _existing_loggers_survive():
        command.upgrade(alembic_config, REVISION)

    inspector = inspect(scratch_database)

    def actions(table: str) -> dict[str, str | None]:
        return {
            fk["constrained_columns"][0]: (fk["options"] or {}).get("ondelete")
            for fk in inspector.get_foreign_keys(table)
        }

    assert actions("agent_runs") == {
        "user_id": "CASCADE",
        "repository_id": "CASCADE",
        "chat_message_id": "SET NULL",
    }
    assert actions("agent_steps") == {"run_id": "CASCADE"}
    assert actions("chat_messages")["agent_run_id"] == "SET NULL"


def test_existing_chat_turns_survive_and_deleting_a_run_clears_the_link(
    alembic_config, scratch_database
):
    from alembic import command

    engine = scratch_database
    with _existing_loggers_survive():
        command.upgrade(alembic_config, PARENT)
    user, repo, message = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id, name, email) VALUES (:id, 'n', :email)"),
            {"id": user, "email": f"{user}@example.com"},
        )
        connection.execute(
            text(
                "INSERT INTO repositories (id, user_id, github_url, name, status) "
                "VALUES (:id, :user, 'https://github.com/x/y', 'y', 'ready')"
            ),
            {"id": repo, "user": user},
        )
        connection.execute(
            text(
                "INSERT INTO chat_messages (id, repository_id, user_id, question, answer) "
                "VALUES (:id, :repo, :user, 'q', 'a')"
            ),
            {"id": message, "repo": repo, "user": user},
        )

    with _existing_loggers_survive():
        command.upgrade(alembic_config, REVISION)

    run = uuid.uuid4()
    with engine.begin() as connection:
        survivor = connection.execute(
            text("SELECT agent_run_id FROM chat_messages WHERE id = :id"), {"id": message}
        ).one()
        assert survivor[0] is None
        connection.execute(
            text(
                "INSERT INTO agent_runs (id, user_id, repository_id, chat_message_id, question, "
                "preset, config, config_hash) VALUES (:id, :user, :repo, :message, 'q', 'classic', "
                "'{}'::jsonb, :hash)"
            ),
            {"id": run, "user": user, "repo": repo, "message": message, "hash": "0" * 64},
        )
        connection.execute(
            text("UPDATE chat_messages SET agent_run_id = :run WHERE id = :id"),
            {"run": run, "id": message},
        )
        connection.execute(
            text(
                "INSERT INTO agent_steps (run_id, seq, kind, name, payload) "
                "VALUES (:run, 1, 'event', 'run_started', '{}'::jsonb)"
            ),
            {"run": run},
        )

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM agent_runs WHERE id = :id"), {"id": run})
        link = connection.execute(
            text("SELECT agent_run_id FROM chat_messages WHERE id = :id"), {"id": message}
        ).one()
        steps = connection.execute(text("SELECT count(*) FROM agent_steps")).scalar_one()

    assert link[0] is None
    assert steps == 0
