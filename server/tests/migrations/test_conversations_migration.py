"""The migration that creates ``conversations`` and attaches every chat turn to one.

Runs on a scratch database for the same reason the agent-runs round trip does. The
backfill is exercised on real rows written at the parent revision.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect, text

from tests.conftest import _existing_loggers_survive
from tests.migrations.test_agent_runs_migration import scratch_database  # noqa: F401

pytestmark = pytest.mark.migration

REVISION = "c8d9e0f1a2b3"
PARENT = "b7c8d9e0f1a2"


def seed(engine) -> dict[str, uuid.UUID]:
    """Two users and two repositories, with turns written at the parent revision."""
    ids = {name: uuid.uuid4() for name in ("ann", "bob", "r1", "r2", "empty_repo")}
    long_question = "  How   does\nthe   authentication flow work in this codebase when " + "x" * 80
    with engine.begin() as connection:
        for name in ("ann", "bob"):
            connection.execute(
                text("INSERT INTO users (id, name, email) VALUES (:id, :username, :email)"),
                {"id": ids[name], "email": f"{name}@example.com", "username": name},
            )
        for name, owner in (("r1", "ann"), ("r2", "ann"), ("empty_repo", "bob")):
            connection.execute(
                text(
                    "INSERT INTO repositories (id, user_id, name, github_url) "
                    "VALUES (:id, :user, :name, :url)"
                ),
                {
                    "id": ids[name],
                    "user": ids[owner],
                    "name": name,
                    "url": f"https://github.com/acme/{name}",
                },
            )
        turns = [
            # Ann on r1: three turns, the earliest is the long question.
            ("ann", "r1", long_question, "2026-01-01 10:00:00+00"),
            ("ann", "r1", "second", "2026-01-02 10:00:00+00"),
            ("ann", "r1", "third", "2026-01-03 10:00:00+00"),
            # Ann on r2: one turn.
            ("ann", "r2", "short question", "2026-02-01 10:00:00+00"),
            # Bob on r1 would be foreign; bob's own repository holds one turn.
            ("bob", "empty_repo", "bob asks", "2026-03-01 10:00:00+00"),
        ]
        for user, repo, question, at in turns:
            connection.execute(
                text(
                    "INSERT INTO chat_messages "
                    "(repository_id, user_id, question, answer, created_at) "
                    "VALUES (:repo, :user, :question, 'a', :at)"
                ),
                {"repo": ids[repo], "user": ids[user], "question": question, "at": at},
            )
    return ids


def test_the_revision_follows_the_mcp_tokens_and_is_the_head(alembic_config):
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(alembic_config)

    assert script.get_revision(REVISION).down_revision == PARENT
    assert script.get_current_head() == REVISION
    assert len(script.get_heads()) == 1


def test_backfill_groups_per_user_and_repository_and_the_column_becomes_required(
    alembic_config,
    scratch_database,  # noqa: F811
):
    from alembic import command

    engine = scratch_database
    with _existing_loggers_survive():
        command.upgrade(alembic_config, PARENT)
        assert "conversations" not in inspect(engine).get_table_names()
        ids = seed(engine)

        command.upgrade(alembic_config, REVISION)

    inspector = inspect(engine)
    assert "conversations" in inspector.get_table_names()
    column = {c["name"]: c for c in inspector.get_columns("chat_messages")}["conversation_id"]
    assert column["nullable"] is False
    index = {i["name"]: i for i in inspector.get_indexes("conversations")}
    assert index["ix_conversations_user_repo_updated"]["column_names"][:2] == [
        "user_id",
        "repository_id",
    ]

    with engine.connect() as connection:
        conversations = connection.execute(
            text(
                "SELECT user_id, repository_id, title, created_at, updated_at, id "
                "FROM conversations ORDER BY created_at"
            )
        ).all()
        assert len(conversations) == 3
        by_pair = {(row.user_id, row.repository_id): row for row in conversations}
        assert set(by_pair) == {
            (ids["ann"], ids["r1"]),
            (ids["ann"], ids["r2"]),
            (ids["bob"], ids["empty_repo"]),
        }

        first = by_pair[(ids["ann"], ids["r1"])]
        assert first.created_at.isoformat().startswith("2026-01-01T10:00")
        assert first.updated_at.isoformat().startswith("2026-01-03T10:00")
        assert first.title.startswith("How does the authentication flow work")
        assert len(first.title) == 60
        assert first.title.endswith("…")
        assert "\n" not in first.title and "  " not in first.title
        assert by_pair[(ids["ann"], ids["r2"])].title == "short question"

        for (user, repo), conversation in by_pair.items():
            rows = connection.execute(
                text(
                    "SELECT user_id, repository_id FROM chat_messages WHERE conversation_id = :id"
                ),
                {"id": conversation.id},
            ).all()
            assert rows
            assert {(r.user_id, r.repository_id) for r in rows} == {(user, repo)}
        counts = connection.execute(
            text("SELECT count(*) FROM chat_messages WHERE conversation_id IS NULL")
        ).scalar_one()
        assert counts == 0


def test_a_message_cannot_be_left_without_a_conversation(alembic_config, scratch_database):  # noqa: F811
    from sqlalchemy.exc import IntegrityError

    from alembic import command

    engine = scratch_database
    with _existing_loggers_survive():
        command.upgrade(alembic_config, REVISION)
    ids = {name: uuid.uuid4() for name in ("u", "r")}
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id, name, email) VALUES (:id, 'u', 'u@example.com')"),
            {"id": ids["u"]},
        )
        connection.execute(
            text(
                "INSERT INTO repositories (id, user_id, name, github_url) "
                "VALUES (:id, :user, 'r', 'https://github.com/acme/r')"
            ),
            {"id": ids["r"], "user": ids["u"]},
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO chat_messages (repository_id, user_id, question, answer) "
                "VALUES (:repo, :user, 'q', 'a')"
            ),
            {"repo": ids["r"], "user": ids["u"]},
        )


def test_deleting_a_conversation_deletes_its_messages_and_downgrade_keeps_the_turns(
    alembic_config,
    scratch_database,  # noqa: F811
):
    from alembic import command

    engine = scratch_database
    with _existing_loggers_survive():
        command.upgrade(alembic_config, PARENT)
        ids = seed(engine)
        command.upgrade(alembic_config, REVISION)

        with engine.begin() as connection:
            victim = connection.execute(
                text("SELECT id FROM conversations WHERE repository_id = :repo"),
                {"repo": ids["r2"]},
            ).scalar_one()
            connection.execute(text("DELETE FROM conversations WHERE id = :id"), {"id": victim})
            remaining = connection.execute(text("SELECT count(*) FROM chat_messages")).scalar_one()
        assert remaining == 4

        command.downgrade(alembic_config, PARENT)

        inspector = inspect(engine)
        assert "conversations" not in inspector.get_table_names()
        assert "conversation_id" not in {c["name"] for c in inspector.get_columns("chat_messages")}
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM chat_messages")).scalar_one() == 4

        command.upgrade(alembic_config, REVISION)
        assert "conversations" in inspect(engine).get_table_names()
