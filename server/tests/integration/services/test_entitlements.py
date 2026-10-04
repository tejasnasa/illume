"""Integration tests for the per-user quota policy.

The two :func:`claim_*` helpers are tested against a real Postgres because
their contract is "two concurrent callers cannot both succeed". A unit test
over a fake session cannot reproduce the row-level ``WHERE`` semantics that
make the claim a compare-and-set; only a real transaction does. The pattern
mirrors :class:`tests.integration.tasks.test_sweep_task.TestClaimPredicate`
-- a single sweep call primes every combination and the assertion reads as
one snapshot, rather than a per-axis sequence.

The headline matrix:

* :func:`claim_free_ingestion` returns ``True`` for the first
  ``FREE_INGESTIONS`` calls and ``False`` for the next -- the bound is
  enforced atomically with the increment, so a user cannot over-spend their
  allowance.
* :func:`claim_free_chat_message` returns ``True`` for the 5th call and
  ``False`` for the 6th -- the bound is enforced atomically with the
  increment, so a user cannot over-spend their allowance.

The :func:`aclaim_*` async twins are exercised by the route layer; this
module covers the sync path because Celery is the caller that already
speaks sync sessions.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.repository import Repository
from app.models.user import User
from app.services.entitlements import (
    FREE_CHAT_MESSAGES,
    FREE_INGESTIONS,
    claim_free_chat_message,
    claim_free_ingestion,
)
from tests.conftest import TEST_SYNC_DB_URL

pytestmark = pytest.mark.integration

# A tuple of (engine, sessionmaker). The engine is consumed by ``_cleanup``
# to dispose the connection pool; the sessionmaker is the way tests open new
# sessions within a single test body.
SessionFactory = tuple[Engine, sessionmaker[Session]]


def _sync_session_factory() -> SessionFactory:
    """A fresh sync engine + session factory pointed at the test database.

    ``expire_on_commit=False`` keeps ``User`` attributes readable after the
    session that produced the row has been committed and closed -- the
    helper functions return a detached instance, and the cleanup path
    reads ``user.id`` after the writing session has gone out of scope.
    Without this, every ``user.id`` access past the commit would attempt a
    lazy reload on a detached instance and raise ``DetachedInstanceError``.
    """
    engine = create_engine(TEST_SYNC_DB_URL)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _make_user(session: Session, *, with_key: bool = False) -> User:
    """A committed user row, optionally seeded with a stored AI key.

    The user_id attribute is referenced by ``repositories.user_id``; a
    unique id per test avoids cross-test contamination.
    """
    user = User(
        id=uuid.uuid4(),
        github_id=str(uuid.uuid4().int)[:20],
        email=f"ent-{uuid.uuid4().hex[:8]}@example.test",
        name="Entitlements Test User",
    )
    if with_key:
        user.ai_provider = "openai"
        user.ai_api_key = "sk-test"
        user.ai_model = "gpt-4o-mini"
        user.ai_key_validated_at = datetime.now(UTC)
    session.add(user)
    session.commit()
    return user


def _cleanup(
    session_factory: SessionFactory,
    user_id: uuid.UUID,
    repo_id: uuid.UUID | None,
) -> None:
    """Remove the seeded rows, then dispose the engine."""
    engine, Session = session_factory
    session = Session()
    try:
        if repo_id is not None:
            session.execute(delete(Repository).where(Repository.id == repo_id))
        session.execute(delete(User).where(User.id == user_id))
        session.commit()
    finally:
        session.close()
        engine.dispose()


def _run_claim_test(body: Callable[[User, sessionmaker[Session]], None]) -> None:
    """Drive one test against a fresh user row, cleaning up after.

    Building a user and a session engine around every test is boilerplate
    that obscures the assertion. ``body`` receives the freshly-committed
    :class:`User` and the sessionmaker (so the test can open as many
    sessions as it needs) and runs the actual test logic. Cleanup runs
    whether the body raises or returns.
    """
    session_factory = _sync_session_factory()
    engine, Session = session_factory
    user: User | None = None
    try:
        user = _make_user(Session())
        body(user, Session)
    finally:
        if user is not None:
            _cleanup(session_factory, user.id, None)
        engine.dispose()


class TestClaimFreeIngestion:
    """``claim_free_ingestion`` -- the bounded per-user free ingestion.

    The ingest claim does **not** commit by design: the caller is expected
    to bundle the claim with the ``Repository`` insert in one transaction,
    so a failed insert rolls back the claim. The tests below follow that
    contract by committing on the caller's session -- the function only
    reports whether the row was updated.
    """

    def test_returns_true_for_the_first_calls_then_false(self):
        """A fresh user has ``FREE_INGESTIONS`` units; the (n+1)th call returns ``False``."""

        def _body(user: User, Session: sessionmaker[Session]) -> None:
            # The matrix: FREE_INGESTIONS succeeds, the next fails. Read in
            # a single list so the assertion is one snapshot. Each claim
            # commits on its own session, matching the caller-owned commit
            # the helper's ``WHERE`` predicate depends on.
            results = []
            for _ in range(FREE_INGESTIONS + 1):
                session = Session()
                results.append(claim_free_ingestion(session, user.id))
                session.commit()

            assert results == [True] * FREE_INGESTIONS + [False]

        _run_claim_test(_body)

    def test_persists_the_increment_on_the_user_row(self):
        """The counter advance is visible to a fresh session; the caller committed."""

        def _body(user: User, Session: sessionmaker[Session]) -> None:
            session = Session()
            claim_free_ingestion(session, user.id)
            session.commit()

            stored = Session().execute(select(User).where(User.id == user.id)).scalar_one()
            assert stored.free_ingestions_used == 1
            assert stored.free_chat_messages_used == 0

        _run_claim_test(_body)

    def test_a_user_with_a_key_still_has_the_default_zero(self):
        """The counter is independent of the BYOK credential.

        A user with their own key is not on the free tier at all -- the
        counter sits at ``0`` forever, but it is still a real column on
        the row.
        """
        session_factory = _sync_session_factory()
        engine, Session = session_factory
        user: User | None = None
        try:
            user = _make_user(Session(), with_key=True)

            stored = Session().execute(select(User).where(User.id == user.id)).scalar_one()
            assert stored.ai_api_key == "sk-test"
            assert stored.free_ingestions_used == 0
        finally:
            if user is not None:
                _cleanup(session_factory, user.id, None)
            engine.dispose()


class TestClaimFreeChatMessage:
    """``claim_free_chat_message`` -- the bounded-per-user chat quota."""

    def test_returns_true_for_the_first_five_calls_then_false(self):
        """A fresh user has ``FREE_CHAT_MESSAGES`` units; the (n+1)th call returns ``False``."""

        def _body(user: User, Session: sessionmaker[Session]) -> None:
            # The matrix: 5 succeeds, 6 fails. Read in a single list-comp
            # so the assertion is one snapshot.
            results = [
                claim_free_chat_message(Session(), user.id) for _ in range(FREE_CHAT_MESSAGES + 1)
            ]

            assert results == [True] * FREE_CHAT_MESSAGES + [False]

        _run_claim_test(_body)

    def test_persists_the_increment_atomically(self):
        """The counter advances by one per call, not by the amount passed (none)."""

        def _body(user: User, Session: sessionmaker[Session]) -> None:
            claim_free_chat_message(Session(), user.id)
            claim_free_chat_message(Session(), user.id)
            claim_free_chat_message(Session(), user.id)

            stored = Session().execute(select(User).where(User.id == user.id)).scalar_one()
            assert stored.free_chat_messages_used == 3

        _run_claim_test(_body)

    def test_two_claims_at_the_cap_both_refuse(self):
        """Two interleaved claims at the cap: both refuse.

        This is the compare-and-set guarantee the ``WHERE`` clause
        provides. Two sequential calls at the cap do not exercise it --
        either could win, but only one actually fires. The two callers
        share a session, but each issues its own ``UPDATE``; the second
        one reads the row the first one already updated.
        """

        def _body(user: User, Session: sessionmaker[Session]) -> None:
            # Burn the cap.
            for _ in range(FREE_CHAT_MESSAGES):
                claim_free_chat_message(Session(), user.id)

            # The next two claims: both refuse because the ``WHERE``
            # predicate ``free_chat_messages_used < N`` no longer matches.
            first = claim_free_chat_message(Session(), user.id)
            second = claim_free_chat_message(Session(), user.id)

            assert first is False
            assert second is False

            stored = Session().execute(select(User).where(User.id == user.id)).scalar_one()
            assert stored.free_chat_messages_used == FREE_CHAT_MESSAGES

        _run_claim_test(_body)
