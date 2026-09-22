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


# The stride between two xdist workers' `repo_number` bands.
#
# This must be *larger than the whole range the per-module base literals occupy*, and that
# is the property that makes the scheme collision-free -- see
# `committed_repo_number_base` for why. It was 10_000, which is roughly the spacing the
# bases themselves used, so a module running one worker higher landed exactly on the next
# module's numbers: `test_ingest_task` at 950_000 on gw1 reached 960_000, which is where
# `test_pipeline` and `test_sweep_task` both start on gw0. The result was an
# `IntegrityError` on `repositories_repo_number_key` that appeared only when two modules
# happened to be scheduled onto those two workers at once -- an intermittent red that
# passes in isolation, which is the worst kind.
#
# A stride far above every base keeps each module inside its own 10-million-wide slot on
# every worker, so no two (module, worker) pairs can ever produce the same number.
REPO_NUMBER_BAND = 10_000_000


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

    **The invariant callers must hold:** pass a base that is *pairwise distinct across
    modules* and *smaller than* `REPO_NUMBER_BAND`. Given both, two (module, worker) pairs
    can never produce the same number, for any number of workers:

        base_a + i * BAND == base_b + j * BAND
      => base_a - base_b == (j - i) * BAND

    and since every base lies in `[0, BAND)` the left side has magnitude below `BAND`, so
    `j - i` must be 0, which forces `base_a == base_b` and therefore `a == b`.

    The band being *wider than the base range* is the load-bearing half. A band comparable
    to the spacing between bases lets a module on a higher worker walk into the next
    module's range, which is a real collision rather than a theoretical one.
    """
    import os

    worker = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    try:
        index = int(worker.removeprefix("gw"))
    except ValueError:
        index = 0
    return base + index * REPO_NUMBER_BAND
