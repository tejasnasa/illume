"""Small shared helpers for API tests.

Deliberately not fixtures: everything here is a pure function with no setup or teardown,
and fixtures are for resource lifecycle. Keeping them as plain functions also lets a test
call them more than once -- which the cross-user tests do, signing in as A and then as B
within a single test.
"""

import uuid


async def authenticate(client, user):
    """
    Give the client a session cookie for `user`.

    Auth is a cookie holding a JWT, so signing in during a test is just writing that
    cookie. Going through `/login` instead would make every suite depend on the auth
    router working, which is precisely what the auth tests exist to check.
    """
    from app.core.security import create_access_token

    client.cookies.set("access_token", create_access_token(subject=str(user.id)))
    return client


async def make_two_users(db):
    """Two unrelated accounts, for cross-user access checks."""
    from tests.factories import make_user

    return await make_user(db), await make_user(db)


def random_uuid() -> uuid.UUID:
    """A UUID guaranteed not to match any row a test created."""
    return uuid.uuid4()
