"""The embedder's page-and-commit contract.

Two properties the stage's peak memory rests on, and neither is visible to a
test that only counts rows at the end:

* **Symbols are read a page at a time, and every symbol is embedded exactly
  once.** The keyset cursor that makes paging commit-safe advances on
  ``AstSymbol.id``; an off-by-one there would silently drop or repeat a
  symbol at a page boundary, and the row count at the end would still look
  plausible.
* **Each batch is committed as its response arrives.** A network failure part
  way through a run must keep the batches that already landed rather than
  discarding all of them.

Both run against real Postgres. The commit-versus-cursor interaction and the
keyset boundary are transaction-level properties; a mocked session reproduces
neither.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import sessionmaker

from app.models.ast_symbol import AstSymbol
from app.models.embedding import Embedding
from app.models.file import File
from app.models.repository import Repository
from app.models.user import User
from app.services import embedder
from app.services.embedder import generate_embeddings
from tests.conftest import TEST_SYNC_DB_URL
from tests.fixtures import openai_stub

pytestmark = pytest.mark.integration


def _sync_session_factory():
    """A fresh sync engine + session factory pointed at the test database."""
    engine = create_engine(TEST_SYNC_DB_URL)
    return engine, sessionmaker(bind=engine)


def _make_repo(session) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a user + repository pair and return their ids."""
    from app.core.security import hash_password

    user = User(
        email=f"embed-{uuid.uuid4().hex[:8]}@example.com",
        name="Embedder Test User",
        password=hash_password("correct horse battery staple"),
    )
    session.add(user)
    session.flush()

    repo = Repository(
        user_id=user.id,
        github_url=f"https://github.com/example/embed-{uuid.uuid4().hex[:8]}",
        name=f"embed-test-{uuid.uuid4().hex[:8]}",
        status="pending",
        default_branch="main",
    )
    session.add(repo)
    session.flush()
    return user.id, repo.id


def _seed_symbols(session, repo_id: uuid.UUID, *, count: int, prefix: str) -> None:
    """Insert ``count`` files, each with one embeddable function symbol."""
    files = [
        {
            "id": uuid.uuid4(),
            "repository_id": repo_id,
            "path": f"src/{prefix}{i:04d}.py",
            "language": "python",
            "loc": 3,
        }
        for i in range(count)
    ]
    session.execute(pg_insert(File), files)
    symbols = [
        {
            "id": uuid.uuid4(),
            "file_id": row["id"],
            "kind": "function",
            "name": f"{prefix}_fn_{i}",
            "start_line": 1,
            "end_line": 1,
            "source_code": "def fn(): return 1",
            "docstring": "Returns 1.",
        }
        for i, row in enumerate(files)
    ]
    session.execute(pg_insert(AstSymbol), symbols)


def _cleanup(session_factory, user_ids: list[uuid.UUID], repo_ids: list[uuid.UUID]) -> None:
    """Remove the seeded rows; cascade takes the files, symbols and embeddings."""
    engine, Session = session_factory
    session = Session()
    try:
        for repo_id in repo_ids:
            session.execute(delete(Repository).where(Repository.id == repo_id))
        for user_id in user_ids:
            session.execute(delete(User).where(User.id == user_id))
        session.commit()
    finally:
        session.close()
        engine.dispose()


def _symbol_embedding_count(session, repo_id: uuid.UUID) -> int:
    return session.execute(
        select(func.count())
        .select_from(Embedding)
        .where(Embedding.repository_id == repo_id, Embedding.source_type == "symbol")
    ).scalar_one()


class _FailOnShortBatch:
    """An embeddings client that fails on any batch smaller than ``BATCH_SIZE``.

    Keyed on the batch's *content* rather than the call ordinal: the batches
    are submitted to a thread pool, so which worker reaches the client first
    is not deterministic. The full first batch has ``BATCH_SIZE`` items and
    the remainder is shorter, so this fails the tail deterministically while
    letting the first batch land.
    """

    def __init__(self) -> None:
        self.embeddings = self
        self.succeeded = 0

    def create(self, *, model: str, input: list[str], **kwargs: Any):
        if len(input) < embedder.BATCH_SIZE:
            raise RuntimeError("synthetic embeddings failure")
        self.succeeded += 1
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.0] * 1536, index=i) for i in range(len(input))]
        )


class TestPartialProgress:
    """Batches already committed survive a later failure in the same run."""

    def test_a_failure_part_way_through_keeps_the_batches_already_committed(self, monkeypatch):
        session_factory = _sync_session_factory()
        engine, Session = session_factory
        session = Session()
        user_id, repo_id = _make_repo(session)
        try:
            # 160 symbols is two batches: a full one of BATCH_SIZE, then a
            # short remainder -- the shape the fake fails on.
            _seed_symbols(session, repo_id, count=embedder.BATCH_SIZE + 60, prefix="p")
            session.commit()

            monkeypatch.setattr(embedder, "OpenAI", lambda *args, **kwargs: _FailOnShortBatch())

            with pytest.raises(RuntimeError, match="synthetic embeddings failure"):
                generate_embeddings(repo_id, session, publish_log=None)

            session.rollback()

            # The full batch was committed before the failure surfaced, so its
            # rows are durable even though the run as a whole raised.
            committed = _symbol_embedding_count(session, repo_id)
            assert committed == embedder.BATCH_SIZE, (
                f"expected the first batch's {embedder.BATCH_SIZE} rows to survive the "
                f"failure, found {committed}"
            )
        finally:
            session.close()
            _cleanup(session_factory, [user_id], [repo_id])


class TestSymbolPaging:
    """Every symbol is embedded exactly once, across any number of pages."""

    def test_every_symbol_is_embedded_exactly_once_across_pages(self, monkeypatch):
        session_factory = _sync_session_factory()
        engine, Session = session_factory
        session = Session()
        user_a, repo_a = _make_repo(session)
        user_b, repo_b = _make_repo(session)
        try:
            # A page size far below the seed size, so the run crosses several
            # page boundaries instead of landing in one page.
            monkeypatch.setattr(embedder, "EMBED_BUILD_BATCH_SIZE", 3)
            _seed_symbols(session, repo_a, count=10, prefix="a")
            # A second repo's symbols sit in the table too. Ordering by
            # ``AstSymbol.id`` walks past them between pages, so a cursor that
            # applied the repository filter *after* the page limit would leak
            # them into repo A's chunks or stall the walk.
            _seed_symbols(session, repo_b, count=12, prefix="b")
            session.commit()

            openai_stub.install(monkeypatch)
            inserted = generate_embeddings(repo_a, session, publish_log=None)

            assert inserted == 10
            assert _symbol_embedding_count(session, repo_a) == 10

            # Exactly once each: ten rows, ten distinct source ids.
            source_ids = session.execute(
                select(Embedding.source_id).where(
                    Embedding.repository_id == repo_a,
                    Embedding.source_type == "symbol",
                )
            ).scalars().all()
            assert len(set(source_ids)) == 10

            # The other repository was not touched by repo A's run.
            assert _symbol_embedding_count(session, repo_b) == 0
        finally:
            session.close()
            _cleanup(session_factory, [user_a, user_b], [repo_a, repo_b])
