"""Deleting an account: confirmation, the cascade, and the session after."""

import pytest
from sqlalchemy import func, select

from app.models import ChatMessage, File, Repository
from app.models.user import User
from tests.factories import make_chat_message, make_ingested_repo, make_user
from tests.helpers import authenticate

pytestmark = pytest.mark.integration

ME = "/api/v1/auth/me"


async def delete_account(client, confirm: str):
    return await client.request("DELETE", ME, json={"confirm_email": confirm})


async def count(db, model, **where) -> int:
    stmt = select(func.count()).select_from(model)
    for column, value in where.items():
        stmt = stmt.where(getattr(model, column) == value)
    return (await db.execute(stmt)).scalar_one()


@pytest.fixture
async def owner(client, db_session):
    user = await make_user(db_session)
    repo, _ = await make_ingested_repo(db_session, user)
    await make_chat_message(db_session, repo, user)
    await db_session.commit()
    await authenticate(client, user)
    # Plain values, so the assertions never touch an expired instance.
    return user.id, user.email, repo.id


async def test_removes_the_user_and_everything_it_owns(client, db_session, owner):
    user_id, email, repo_id = owner

    response = await delete_account(client, email)

    assert response.status_code == 204
    db_session.expire_all()
    assert await count(db_session, User, id=user_id) == 0
    assert await count(db_session, Repository, user_id=user_id) == 0
    assert await count(db_session, File, repository_id=repo_id) == 0
    assert await count(db_session, ChatMessage, user_id=user_id) == 0


async def test_leaves_other_accounts_alone(client, db_session, owner):
    _, email, _ = owner
    bystander = await make_user(db_session)
    other_repo, _ = await make_ingested_repo(db_session, bystander)
    bystander_id, other_repo_id = bystander.id, other_repo.id
    await db_session.commit()

    await delete_account(client, email)

    db_session.expire_all()
    assert await count(db_session, User, id=bystander_id) == 1
    assert await count(db_session, Repository, id=other_repo_id) == 1


async def test_confirmation_ignores_case_and_surrounding_space(client, owner):
    _, email, _ = owner

    response = await delete_account(client, f"  {email.upper()} ")

    assert response.status_code == 204


async def test_a_wrong_confirmation_deletes_nothing(client, db_session, owner):
    user_id, _, _ = owner

    response = await delete_account(client, "someone-else@example.com")

    assert response.status_code == 400
    db_session.expire_all()
    assert await count(db_session, User, id=user_id) == 1


async def test_clears_the_session(client, owner):
    _, email, _ = owner

    response = await delete_account(client, email)

    # The cookie is expired on the response itself, whatever domain the jar holds.
    set_cookie = response.headers.get("set-cookie", "")
    assert set_cookie.startswith("access_token=")
    assert "Max-Age=0" in set_cookie


async def test_requires_a_session(client):
    response = await delete_account(client, "anyone@example.com")

    assert response.status_code == 401
