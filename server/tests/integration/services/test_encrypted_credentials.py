"""The database holds credential envelopes; the ORM hands back the plaintext."""

import pytest
from sqlalchemy import select, text

from app.core.crypto import ENVELOPE_PREFIX
from app.models.user import User
from tests.factories import make_user

pytestmark = pytest.mark.integration

GITHUB_TOKEN = "gho_0123456789abcdefghij"
AI_KEY = "sk-0123456789abcdefghij"


async def test_credentials_are_stored_encrypted_and_read_back_in_plaintext(db_session):
    user = await make_user(db_session, github_access_token=GITHUB_TOKEN, ai_api_key=AI_KEY)

    stored = (
        await db_session.execute(
            text("SELECT github_access_token, ai_api_key FROM users WHERE id = :id"),
            {"id": user.id},
        )
    ).one()
    assert all(value.startswith(ENVELOPE_PREFIX) for value in stored)
    assert GITHUB_TOKEN not in stored[0] and AI_KEY not in stored[1]

    user_id = user.id
    db_session.expire_all()
    reloaded = (await db_session.execute(select(User).where(User.id == user_id))).scalar_one()
    assert (reloaded.github_access_token, reloaded.ai_api_key) == (GITHUB_TOKEN, AI_KEY)


async def test_the_is_not_null_check_still_works_on_an_encrypted_column(db_session):
    user = await make_user(db_session, ai_api_key=AI_KEY)

    found = (
        await db_session.execute(
            select(User.id).where(User.id == user.id, User.ai_api_key.isnot(None))
        )
    ).scalar_one_or_none()

    assert found == user.id


async def test_a_row_written_before_encryption_still_reads(db_session):
    user = await make_user(db_session)
    await db_session.execute(
        text("UPDATE users SET github_access_token = :token WHERE id = :id"),
        {"token": GITHUB_TOKEN, "id": user.id},
    )

    user_id = user.id
    db_session.expire_all()
    reloaded = (await db_session.execute(select(User).where(User.id == user_id))).scalar_one()

    assert reloaded.github_access_token == GITHUB_TOKEN
