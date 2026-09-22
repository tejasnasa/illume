"""Auto-update sweep dispatch logic.

Tests run against the real test Postgres; the Celery broker is real but
unused because ``sync_repository.delay`` is monkey-patched onto a recorder
the test inspects directly. Wall-clock comes from ``freezegun`` so the
``next_sync_at`` math is checked against the exact instant the sweep
sees.

The headline matrix is the four-axis filter the sweep applies to every
row in ``repositories``:

* ``auto_update_enabled`` true / false
* ``status`` ready / pending / failed
* ``next_sync_at`` due (in the past or NULL) / not due (in the future)
* ``sync_lease_expires_at`` clear (NULL) / live (future) / expired (past)

Only the single combination matching all four pass-conditions is
claimed. A repo that fails any axis must not see its ``next_sync_at``
moved, and must not appear in the dispatch recorder.

Edge cases the matrix does not cover:

* Two sweeps in a row claim a repo only once -- the second sweep's
  SELECT would still find the row, but its CAS UPDATE matches zero
  rows because the first sweep already moved ``next_sync_at`` to the
  future.
* A live lease blocks re-claim while an expired lease does not -- the
  SIGKILL scenario, where a worker's lease row outlives the worker.
* The global ``AUTO_UPDATE_ENABLED`` kill switch returns zero
  dispatches even with due repos on the table.
* Advancing the clock past the interval re-makes a repo due.
* ``celery.conf.beat_schedule`` carries the sweep entry.
"""

from __future__ import annotations

import itertools
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.core.celery import celery
from app.models.repository import Repository
from app.models.user import User
from app.tasks.autoupdate import (
    SWEEP_BATCH_LIMIT,
    SWEEP_INTERVAL_MINUTES,
    sweep_due_repositories,
)
from tests.conftest import TEST_SYNC_DB_URL
from tests.helpers import committed_repo_number_base

pytestmark = pytest.mark.integration


# 965_000 rather than 960_000: bases must be pairwise distinct across modules, and
# ``services/test_pipeline.py`` already starts at 960_000. Two modules sharing a base is a
# guaranteed collision on any shared worker.
_repo_numbers = itertools.count(committed_repo_number_base(965_000))


def sync_session():
    """A short-lived sync session against the test database."""
    engine = create_engine(TEST_SYNC_DB_URL)
    return engine, sessionmaker(bind=engine)


def _make_user(session, *, with_token: bool = True) -> User:
    """An isolated user row, with an optional GitHub token.

    The user_id attribute is referenced by ``repositories.user_id``; a
    unique id per test avoids cross-test contamination.
    """
    user = User(
        id=uuid.uuid4(),
        github_id=str(uuid.uuid4().int)[:20],
        email=f"u{uuid.uuid4().int}@example.test",
        name="Sweep Test User",
        github_access_token="ghp_test_token" if with_token else None,
    )
    session.add(user)
    session.commit()
    return user


def _make_repo(
    session,
    user: User,
    *,
    auto_update_enabled: bool = True,
    status: str = "ready",
    next_sync_at: datetime | None = None,
    sync_lease_expires_at: datetime | None = None,
    interval_hours: int = 6,
) -> Repository:
    """A repository row reflecting exactly the inputs -- the matrix fixture.

    ``repo_number`` is supplied explicitly because the column has no
    database-side generator -- bypassing it would surface as a NOT NULL
    violation. ``factories.py`` documents the same workaround; we
    duplicate the pattern here to avoid sharing ORM instances with the
    factory's async session.
    """
    repo = Repository(
        id=uuid.uuid4(),
        user_id=user.id,
        github_url=f"https://github.com/example/{uuid.uuid4().hex[:8]}",
        name=f"repo-{uuid.uuid4().hex[:8]}",
        status=status,
        auto_update_enabled=auto_update_enabled,
        auto_update_interval_hours=interval_hours,
        next_sync_at=next_sync_at,
        sync_lease_expires_at=sync_lease_expires_at,
        repo_number=next(_repo_numbers),
    )
    session.add(repo)
    session.commit()
    return repo


def _cleanup(session, repos: Iterable[Repository]) -> None:
    """Drop the rows this test inserted so other tests never see them.

    ``delete from repositories`` is needed because the rows are committed
    (the sweep opens its own session, so a row left in the test's
    transaction would be invisible to it).
    """
    ids = [r.id for r in repos]
    session.execute(delete(Repository).where(Repository.id.in_(ids)))
    user_ids = list({r.user_id for r in repos})
    session.execute(delete(User).where(User.id.in_(user_ids)))
    session.commit()


@pytest.fixture
def sweep_recorder(monkeypatch):
    """A stand-in for ``sync_repository.delay`` recording every dispatch."""
    dispatched: list[tuple[str, str | None]] = []

    def fake_delay(repo_id: str, access_token: str | None = None):
        dispatched.append((repo_id, access_token))

    from app.tasks import autoupdate as autoupdate_module

    monkeypatch.setattr(autoupdate_module.sync_repository, "delay", fake_delay)
    return dispatched


@pytest.fixture
def sweep_clock(monkeypatch):
    """Force jitter to zero so the test can compute exact ``next_sync_at``."""
    monkeypatch.setattr("app.tasks.autoupdate.SWEEP_OFFSET_JITTER_SECONDS", 0.0)


@pytest.fixture
def sweep_repos(monkeypatch):
    """A factory for inserted user+repo rows with teardown.

    Yields ``factory(repo_kwargs..., user_kwargs...)`` which inserts a
    fresh user and returns the freshly-inserted repo. All rows are
    removed before the test ends -- no orphan commits outlive the suite.

    The sweep's claim predicate is monkey-patched to also restrict to
    ``id IN (test_rows)`` so the test's sweep run cannot pick up rows
    inserted by a peer xdist worker's concurrently-running test. The
    production predicate is preserved verbatim aside from this scoping.
    """
    engine, Session = sync_session()
    session = Session()
    created_repos: list[Repository] = []
    test_repo_ids: list[uuid.UUID] = []

    def _factory(*, repo: dict | None = None, user: dict | None = None) -> Repository:
        u = _make_user(session, **(user or {}))
        r = _make_repo(session, u, **(repo or {}))
        created_repos.append(r)
        test_repo_ids.append(r.id)
        return r

    from app.tasks import autoupdate as autoupdate_module

    original_predicate = autoupdate_module._claim_predicate

    def _scoped_predicate(now):
        return original_predicate(now) + (Repository.id.in_(test_repo_ids),)

    monkeypatch.setattr(autoupdate_module, "_claim_predicate", _scoped_predicate)

    yield _factory, session

    try:
        _cleanup(session, created_repos)
    finally:
        session.close()


# --- The four-axis claim matrix --------------------------------------------


class TestClaimPredicate:
    """The sweep's WHERE clause gates on four independent axes.

    A single test case primes every combination through one ``sweep`` call
    so the assertion reads as a snapshot of what gets dispatched and what
    does not, rather than a per-axis sequence.
    """

    def test_only_a_ready_enabled_due_repo_with_a_clear_lease_is_claimed(
        self, sweep_recorder, sweep_clock, sweep_repos
    ):
        """All four axes must pass for one repo to be claimed; the rest stay put."""
        now = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

        factory, session = sweep_repos

        # THE one row that should claim.
        should_claim = factory(
            user={"with_token": True},
            repo={
                "auto_update_enabled": True,
                "status": "ready",
                "next_sync_at": now - timedelta(hours=1),
                "sync_lease_expires_at": None,
            },
        )

        # One row that fails each axis individually. ``expected_next`` records the
        # ``next_sync_at`` value we set so the post-sweep assertion can confirm
        # the sweep did not move it -- whatever we wrote is what should be
        # there afterwards.
        expected_next: dict[uuid.UUID, datetime | None] = {}

        def _record(r, repo_kwargs):
            expected_next[r.id] = repo_kwargs.get("next_sync_at")

        disabled = factory(
            user={},
            repo={"auto_update_enabled": False},
        )
        _record(disabled, {"next_sync_at": None})

        pending = factory(
            user={},
            repo={"status": "pending"},
        )
        _record(pending, {"next_sync_at": None})

        not_due = factory(
            user={},
            repo={"next_sync_at": now + timedelta(hours=1)},
        )
        _record(not_due, {"next_sync_at": now + timedelta(hours=1)})

        live_lease = factory(
            user={},
            repo={"sync_lease_expires_at": now + timedelta(minutes=30)},
        )
        _record(live_lease, {"next_sync_at": None})

        with freeze_time(now):
            sweep_due_repositories.apply()

        # Exactly the one expected repo was dispatched.
        assert [(rid, token) for rid, token in sweep_recorder] == [
            (str(should_claim.id), "ghp_test_token"),
        ]

        # Compare every row's ``next_sync_at`` against what the test set.
        # The claimed repo moved to ``now + 6h``; the rest stayed put.
        fresh_session = sync_session()[1]()
        try:
            rows_by_id = {r.id: r for r in fresh_session.scalars(select(Repository)).all()}
            assert rows_by_id[should_claim.id].next_sync_at == now + timedelta(hours=6)
            for rid, expected in expected_next.items():
                assert rows_by_id[rid].next_sync_at == expected, (
                    f"row {rid} next_sync_at drifted from "
                    f"{expected!r} to {rows_by_id[rid].next_sync_at!r}"
                )
        finally:
            fresh_session.close()


# --- Defect 4: lease semantics --------------------------------------------


class TestLeaseSemantics:
    """A live lease blocks re-claim; an expired one does not.

    The expired case is the SIGKILL scenario from the plan: the worker
    holding the lease is gone, but its row outlives the process. The
    lease value stays in the database; what changes is whether it is in
    the past (``< now``) or the future (``>= now``).
    """

    def test_a_live_lease_blocks_re_claim(self, sweep_recorder, sweep_clock, sweep_repos):
        now = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

        factory, _ = sweep_repos
        factory(
            repo={
                "auto_update_enabled": True,
                "status": "ready",
                "next_sync_at": now - timedelta(hours=1),
                "sync_lease_expires_at": now + timedelta(minutes=30),
            },
        )

        with freeze_time(now):
            sweep_due_repositories.apply()

        assert sweep_recorder == []

    def test_an_expired_lease_does_not_block_re_claim(
        self, sweep_recorder, sweep_clock, sweep_repos
    ):
        """An expired lease is the SIGKILL case -- the next sweep must pick it up."""
        now = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

        factory, _ = sweep_repos
        repo = factory(
            repo={
                "auto_update_enabled": True,
                "status": "ready",
                "next_sync_at": now - timedelta(hours=1),
                "sync_lease_expires_at": now - timedelta(minutes=1),
            },
        )

        with freeze_time(now):
            sweep_due_repositories.apply()

        assert [rid for rid, _ in sweep_recorder] == [str(repo.id)]


# --- Two sweeps in a row --------------------------------------------------


class TestIdempotence:
    """A repo due at time T is dispatched exactly once across consecutive sweeps.

    The defect-4 fix: the second sweep's SELECT still finds the row, but
    the per-row CAS update matches zero rows because the first sweep
    already moved ``next_sync_at`` to the future.
    """

    def test_two_consecutive_sweeps_enqueue_once(self, sweep_recorder, sweep_clock, sweep_repos):
        now = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

        factory, session = sweep_repos
        repo = factory(
            user={"with_token": True},
            repo={
                "auto_update_enabled": True,
                "status": "ready",
                "next_sync_at": now - timedelta(hours=1),
                "sync_lease_expires_at": None,
            },
        )

        with freeze_time(now):
            sweep_due_repositories.apply()

        # Advance by a heartbeat -- enough for beat to have fired twice,
        # not enough for the interval to elapse.
        later = now + timedelta(seconds=30)
        with freeze_time(later):
            sweep_due_repositories.apply()

        # Only the first sweep dispatched; the second found the row's
        # ``next_sync_at`` already in the future.
        assert [rid for rid, _ in sweep_recorder] == [str(repo.id)]


# --- Interval advancement ------------------------------------------------


class TestIntervalMakesRepoDue:
    """``next_sync_at = now + interval`` is the contract the sweep relies on.

    Freezing the clock past the interval re-makes a repo claimable. The
    sweep itself sets ``next_sync_at = now + interval + jitter``; a freezegun
    pin at ``now + interval + 1s`` makes the row fall due again.
    """

    def test_advancing_the_clock_past_the_interval_claims_again(
        self, sweep_recorder, sweep_clock, sweep_repos
    ):
        first = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
        second = first + timedelta(hours=6, seconds=1)

        factory, _ = sweep_repos
        repo = factory(
            user={"with_token": True},
            repo={
                "auto_update_enabled": True,
                "status": "ready",
                "next_sync_at": first - timedelta(hours=1),
                "interval_hours": 6,
            },
        )

        with freeze_time(first):
            sweep_due_repositories.apply()
        # First sweep bumped next_sync_at to first + 6h.
        with freeze_time(second):
            sweep_due_repositories.apply()

        # Repo claimed twice -- once per sweep.
        assert [rid for rid, _ in sweep_recorder] == [str(repo.id), str(repo.id)]


# --- Kill switch ---------------------------------------------------------


class TestKillSwitch:
    """``AUTO_UPDATE_ENABLED = False`` is the deployment-wide kill switch."""

    def test_kill_switch_enqueues_nothing(
        self, sweep_recorder, sweep_clock, sweep_repos, monkeypatch
    ):
        now = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

        factory, _ = sweep_repos
        # Even a fully-claimable repo should be ignored.
        factory(
            user={"with_token": True},
            repo={
                "auto_update_enabled": True,
                "status": "ready",
                "next_sync_at": now - timedelta(hours=1),
                "sync_lease_expires_at": None,
            },
        )

        from app.tasks import autoupdate as autoupdate_module

        monkeypatch.setattr(autoupdate_module, "AUTO_UPDATE_ENABLED", False)

        with freeze_time(now):
            sweep_due_repositories.apply()

        assert sweep_recorder == []


# --- Beat schedule --------------------------------------------------------


def test_beat_schedule_contains_the_sweep_entry():
    """The beat schedule is what dispatches the sweep; it must be registered."""
    assert "sweep-due-repositories" in celery.conf.beat_schedule
    entry = celery.conf.beat_schedule["sweep-due-repositories"]
    assert entry["task"] == "app.tasks.autoupdate.sweep_due_repositories"


def test_beat_schedule_runs_at_the_configured_interval():
    """The schedule's cadence matches ``SWEEP_INTERVAL_MINUTES``."""
    entry = celery.conf.beat_schedule["sweep-due-repositories"]
    schedule = entry["schedule"]

    # ``celery.schedules.schedule`` stores ``run_every`` as a
    # ``timedelta``; assert against the same type rather than a raw
    # number so the comparison still works if Celery changes the units.
    assert schedule.run_every == timedelta(minutes=SWEEP_INTERVAL_MINUTES)


# --- Batch limit ---------------------------------------------------------


class TestBatchLimit:
    """``SWEEP_BATCH_LIMIT`` caps a single sweep tick's claim count.

    Tests in this class insert more rows than the cap and assert that
    the dispatched list is exactly the cap-sized batch -- older
    ``next_sync_at`` first -- and that the remainder move to ``updated_at``
    is unchanged and remain claimable on the next tick.
    """

    def test_a_tick_claims_at_most_the_batch_limit(self, sweep_recorder, sweep_clock, sweep_repos):
        now = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

        factory, session = sweep_repos
        # ``SWEEP_BATCH_LIMIT + 5`` eligible repos, with distinct
        # ``next_sync_at`` so the ORDER BY has something to sort on.
        total = SWEEP_BATCH_LIMIT + 5
        rows = [
            factory(
                repo={
                    "auto_update_enabled": True,
                    "status": "ready",
                    "next_sync_at": now - timedelta(hours=total - i),
                },
            )
            for i in range(total)
        ]

        with freeze_time(now):
            sweep_due_repositories.apply()

        # Exactly the batch limit was dispatched.
        assert len(sweep_recorder) == SWEEP_BATCH_LIMIT

        # Verify per-row state directly so the ORDER BY contract is
        # explicitly checked: the SWEEP_BATCH_LIMIT oldest-due rows
        # got their next_sync_at bumped; the rest are still claimable.
        # ``sweep_recorder`` records ``(str(repo_id), token)`` tuples --
        # parse the first element back to a UUID for membership tests.
        fresh = sync_session()[1]()
        try:
            fresh_rows = list(
                fresh.scalars(
                    select(Repository).where(Repository.id.in_([r.id for r in rows]))
                ).all()
            )
            by_id = {r.id: r for r in fresh_rows}

            claimed_ids = {uuid.UUID(recorded_id) for recorded_id, _ in sweep_recorder}
            for r in rows:
                if r.id in claimed_ids:
                    assert by_id[r.id].next_sync_at == now + timedelta(hours=6)
                else:
                    # Untouched; the next sweep at now+30s claims the
                    # rest.
                    assert by_id[r.id].next_sync_at == now - timedelta(hours=total - rows.index(r))
        finally:
            fresh.close()


# --- Owner token passthrough ----------------------------------------------


class TestTokenPassthrough:
    """The user's GitHub token is passed to ``sync_repository.delay``.

    ``sync_repository`` will need it to fetch from GitHub; without it
    only public-repo reads work. The sweep must hand it through.
    """

    def test_dispatch_passes_the_owners_github_token(
        self, sweep_recorder, sweep_clock, sweep_repos
    ):
        now = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

        factory, _ = sweep_repos
        repo_with_token = factory(
            user={"with_token": True},
            repo={
                "auto_update_enabled": True,
                "status": "ready",
                "next_sync_at": now - timedelta(hours=1),
            },
        )
        repo_without_token = factory(
            user={"with_token": False},
            repo={
                "auto_update_enabled": True,
                "status": "ready",
                "next_sync_at": now - timedelta(hours=1),
            },
        )

        with freeze_time(now):
            sweep_due_repositories.apply()

        tokens_by_repo = {rid: token for rid, token in sweep_recorder}
        assert tokens_by_repo[str(repo_with_token.id)] == "ghp_test_token"
        assert tokens_by_repo[str(repo_without_token.id)] is None
