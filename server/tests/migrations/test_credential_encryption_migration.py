"""The migration that encrypts stored GitHub tokens and AI keys, and its reverse.

Runs on a scratch database, with rows written in plaintext at the parent revision.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.crypto import credential_aad, decrypt_secret, encrypt_secret, is_envelope
from tests.conftest import _existing_loggers_survive
from tests.migrations.test_agent_runs_migration import scratch_database  # noqa: F401

pytestmark = pytest.mark.migration

REVISION = "d9e0f1a2b3c4"
PARENT = "c8d9e0f1a2b3"

TOKEN = "gho_plaintext_token_0123456789"
KEY = "sk-plaintext-key-0123456789"


def test_the_revision_follows_the_conversations_and_is_the_head(alembic_config):
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(alembic_config)

    assert script.get_revision(REVISION).down_revision == PARENT
    assert script.get_current_head() == REVISION
    assert len(script.get_heads()) == 1


def _credentials(engine, user_id):
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT github_access_token, ai_api_key FROM users WHERE id = :id"),
            {"id": user_id},
        ).one()


def test_upgrade_encrypts_existing_credentials_and_downgrade_restores_them(
    alembic_config,
    scratch_database,  # noqa: F811
):
    from alembic import command

    engine = scratch_database
    plain, empty, already = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    envelope = encrypt_secret(KEY, credential_aad("users", "ai_api_key"))
    with _existing_loggers_survive():
        command.upgrade(alembic_config, PARENT)
        with engine.begin() as connection:
            for user_id, token, key in (
                (plain, TOKEN, KEY),
                (empty, None, None),
                (already, None, envelope),
            ):
                connection.execute(
                    text(
                        "INSERT INTO users (id, name, email, github_access_token, ai_api_key) "
                        "VALUES (:id, 'u', :email, :token, :key)"
                    ),
                    {"id": user_id, "email": f"{user_id}@example.com", "token": token, "key": key},
                )

        command.upgrade(alembic_config, REVISION)

        token_after, key_after = _credentials(engine, plain)
        assert is_envelope(token_after) and is_envelope(key_after)
        assert decrypt_secret(token_after, credential_aad("users", "github_access_token")) == TOKEN
        assert decrypt_secret(key_after, credential_aad("users", "ai_api_key")) == KEY
        assert tuple(_credentials(engine, empty)) == (None, None)
        assert _credentials(engine, already).ai_api_key == envelope

        command.downgrade(alembic_config, PARENT)

    assert tuple(_credentials(engine, plain)) == (TOKEN, KEY)
    assert _credentials(engine, already).ai_api_key == KEY
