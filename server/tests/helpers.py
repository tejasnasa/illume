"""Small shared helpers for API tests.

Deliberately not fixtures: everything here is a pure function with no setup or teardown,
and fixtures are for resource lifecycle. Keeping them as plain functions also lets a test
call them more than once -- which the cross-user tests do, signing in as A and then as B
within a single test.
"""

import uuid

import pytest

BLOCKED_BY_MISSING_REPO_NUMBER_IDENTITY = pytest.mark.xfail(
    strict=True,
    reason=(
        "Repository creation omits repo_number, and the column has no identity and no "
        "default, so the INSERT fails with a NOT NULL violation. These tests exercise "
        "the route's real behaviour and are expected to pass in an environment whose "
        "schema provisions the value."
    ),
)

# The two markers below are the only ones left standing. Earlier defects each had their
# own marker here, and each was deleted once the defect was fixed and its test began to
# pass -- so a marker existing at all means a known, unfixed defect sits behind it. Both
# of the remaining two trace to the same root cause: nothing ever provisions
# `repo_number`.
EMPTY_MIGRATIONS = pytest.mark.xfail(
    strict=True,
    reason=(
        "Three revisions in the chain contain no `op.` calls and change nothing. One of "
        "them, 1bae111890c6, is the root cause of the row above: it was meant to convert "
        "repo_number into an identity column and was left empty, so repository creation "
        "fails. This test passes once the empty revisions are filled in or removed."
    ),
)


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


# How many `repo_number` values each xdist worker reserves. Wide enough that no worker
# runs out, small enough that the whole span stays far above any real row.
REPO_NUMBER_BAND = 10_000


def committed_repo_number_base(base: int) -> int:
    """
    Offset a committed-`repo_number` band by the xdist worker's index.

    Rows that are *committed* rather than rolled back share the test database across
    processes, and each xdist worker is a separate process with its own copy of whatever
    counter a module defines. So two workers defining `itertools.count(950_000)` both
    insert 950_000, and the loser dies on `repositories_repo_number_key`:

        psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint
        DETAIL:  Key (repo_number)=(950000) already exists.

    The failure is order-dependent, which is what makes it expensive: it appears only when
    two committing tests happen to be scheduled onto different workers at once, so it
    surfaces as an intermittent red that passes in isolation.

    Reads `PYTEST_XDIST_WORKER` (`gw0`, `gw1`, ...), which xdist sets in each worker. Under
    a plain `pytest` run the variable is absent and the base is returned unchanged.
    """
    import os

    worker = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    try:
        index = int(worker.removeprefix("gw"))
    except ValueError:
        index = 0
    return base + index * REPO_NUMBER_BAND
