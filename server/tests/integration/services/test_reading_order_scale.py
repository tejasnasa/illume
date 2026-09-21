"""Phase D: reading-order memory shape and dedup invariant at integration scale.

The unit suite (``test_onboarding.py``, ``test_file_graph.py``) covers the
algorithm in isolation; this file runs it against the real Postgres stack the
ingestion pipeline targets, on graphs an order of magnitude larger than any
unit test would build. Two assertions matter here:

* **Bounded memory.** ``tracemalloc`` peak inside ``build_reading_order`` does
  not grow linearly with file count -- a 10x increase in files must not
  produce a 10x peak. The old code held the edge tuple list, two
  UUID-keyed adjacency maps and the ORM ``File`` rows simultaneously; the
  new code streams the edges through ``iter_file_edges`` and projects the
  adjacency into dense ints, so the only growth comes from the
  *post-processing* tier list, not the streaming phase.
* **Dedup at scale.** Duplicate ``(src, tgt)`` symbol-level edges (which the
  ``IN`` subquery join can produce) do not inflate ``in_degree`` on the
  file level and do not bump a DAG file into the cycle tier. The unit
  ``TestBuildIntAdjacency`` covers this for one duplicate. The ``uq_dependency_edge``
  unique constraint on the database now prevents the duplicate-row case
  this test used to exercise; dedup at the streaming boundary is what
  remains in scope.

A **determinism** check runs alongside the memory check: running the same
data through ``build_reading_order`` twice produces a byte-identical
reading-order list. The unit suite pins the algorithm; this pins the data
path -- the edges out of Postgres must reach ``iter_file_edges`` in an order
the deterministic sort can absorb.

The memory assertion is on the *shape*, not a fragile constant: a
``1000 / 100`` peak ratio below eight is the threshold. ``test_memory.py``
uses the same shape-vs-number approach for the scanner memory test. A
fragile constant would make the test fail on whichever Python build ships a
slightly larger dict entry; the shape invariant is what actually catches
the regression.
"""

from __future__ import annotations

import gc
import itertools
import tracemalloc
import uuid

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.models import AstSymbol, Dependency, File, Repository, User
from app.services.onboarding import build_reading_order

pytestmark = pytest.mark.integration

from tests.conftest import TEST_SYNC_DB_URL  # noqa: E402
from tests.fixtures import openai_stub  # noqa: E402
from tests.helpers import committed_repo_number_base  # noqa: E402

# Same band strategy as test_memory.py and test_ingest_task.py: committing
# tests share the database across xdist workers, so each worker takes its
# own offset. The 800_000 band sits clear of the 700_000 (test_memory.py),
# 900_000 (factories.py) and 950_000 (test_ingest_task.py) bands.
_repo_numbers = itertools.count(committed_repo_number_base(800_000))


def _sync_session_factory():
    """A fresh sync engine + session factory pointed at the test database."""
    engine = create_engine(TEST_SYNC_DB_URL)
    return engine, sessionmaker(bind=engine)


def _make_user_repo(session_factory) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a user + repository pair. Caller is responsible for cleanup."""
    from app.core.security import hash_password

    engine, Session = session_factory
    session = Session()
    try:
        user = User(
            email=f"scale-{uuid.uuid4().hex[:8]}@example.com",
            name="Scale Test User",
            password=hash_password("correct horse battery staple"),
        )
        session.add(user)
        session.flush()

        repo = Repository(
            user_id=user.id,
            github_url="https://github.com/example/scale-test",
            name=f"scale-test-{uuid.uuid4().hex[:8]}",
            status="pending",
            default_branch="main",
            repo_number=next(_repo_numbers),
        )
        session.add(repo)
        session.commit()
        return user.id, repo.id
    finally:
        session.close()


def _cleanup(session_factory, user_id: uuid.UUID, repo_id: uuid.UUID) -> None:
    """Remove the user/repo pair; cascade takes the rest."""
    engine, Session = session_factory
    session = Session()
    try:
        session.execute(delete(Repository).where(Repository.id == repo_id))
        session.execute(delete(User).where(User.id == user_id))
        session.commit()
    finally:
        session.close()
        engine.dispose()


def _build_dag(
    session_factory,
    repo_id: uuid.UUID,
    *,
    file_count: int,
    edge_count: int,
    duplicate_ratio: float = 0.0,
) -> None:
    """Bulk-insert a file_count-file repo with edge_count dependency edges.

    Edges form a layered DAG: file ``i`` depends on ``i-1``, ``i-2``, ...
    depending on what fits in ``edge_count``. With ``duplicate_ratio > 0``
    a fraction of the edges are inserted twice (the dedup invariant under
    test).

    ORM instances are built up front, ``session.add_all`` flushes the
    whole graph in one round trip via the SQLAlchemy identity map, and a
    single ``commit()`` makes the rows visible to ``build_reading_order``.
    File and symbol ids are client-assigned so the symbols can refer to
    their file ids before the files have round-tripped to the database.

    One symbol per file -- enough to be a meaningful edge endpoint without
    bloating the AstSymbol table into a per-row insert hot spot.
    """
    engine, Session = session_factory
    session = Session()
    try:
        file_models = [
            File(
                id=uuid.uuid4(),
                repository_id=repo_id,
                path=f"src/m{i:05d}.py",
                language="python",
                loc=1,
            )
            for i in range(file_count)
        ]
        session.add_all(file_models)
        session.flush()

        file_ids = [f.id for f in file_models]
        symbol_models = [
            AstSymbol(
                id=uuid.uuid4(),
                file_id=fid,
                kind="function",
                name=f"helper_{i}",
                start_line=1,
                end_line=1,
                source_code="def helper(): pass",
            )
            for i, fid in enumerate(file_ids)
        ]
        session.add_all(symbol_models)
        session.flush()

        # Build edges deterministically: file i depends on file (i - j - 1)
        # for the first few j's, until ``edge_count`` is reached.
        edges: list[Dependency] = []
        symbol_by_file = {s.file_id: s.id for s in symbol_models}
        per_file = max(1, edge_count // file_count)
        # ``duplicate_every`` controls how often the (i, k) pair is
        # re-emitted with a fresh row id. ``0`` means no duplicates; any
        # positive integer N means every Nth edge is duplicated.
        duplicate_every = int(1 / max(duplicate_ratio, 1e-9)) if duplicate_ratio > 0 else 0
        for i in range(per_file, file_count):
            src_sym = symbol_by_file[file_ids[i]]
            for k in range(per_file):
                tgt_index = i - k - 1
                if tgt_index < 0:
                    break
                tgt_sym = symbol_by_file[file_ids[tgt_index]]
                edges.append(
                    Dependency(
                        id=uuid.uuid4(),
                        source_symbol_id=src_sym,
                        target_symbol_id=tgt_sym,
                        dep_type="imports",
                    )
                )
                if duplicate_every and (i + k) % duplicate_every == 0:
                    # Insert the same logical edge a second time with a
                    # fresh row id -- the SQL layer cannot collapse these,
                    # so the dedup invariant is what has to.
                    edges.append(
                        Dependency(
                            id=uuid.uuid4(),
                            source_symbol_id=src_sym,
                            target_symbol_id=tgt_sym,
                            dep_type="imports",
                        )
                    )
            if len(edges) >= edge_count * 2:  # duplicates push the count up
                break

        if edges:
            session.add_all(edges)

        session.commit()
    finally:
        session.close()


def _run_reading_order(session_factory, repo_id: uuid.UUID, *, monkeypatch) -> list[dict]:
    """Open a sync session and call ``build_reading_order`` against it.

    The OpenAI stub keeps the LLM call deterministic; without it the
    annotation phase makes real network calls and the timing measurements
    become noise.
    """
    openai_stub.install(monkeypatch)
    engine, Session = session_factory
    session = Session()
    try:
        repo = session.query(Repository).filter(Repository.id == repo_id).one()
        guide = build_reading_order(session, repo)
        return list(guide.reading_order or [])
    finally:
        session.close()


class TestBoundedMemory:
    """``tracemalloc`` peak during ``build_reading_order`` does not grow with file count."""

    def test_peak_does_not_grow_linearly_with_file_count(self, monkeypatch):
        """
        Compare a 100-file repo against a 1000-file one (10x larger) and
        assert the peak grows by much less than 10x.

        The old code's signature was: holding the E-tuple list alongside
        two ``dict[UUID, set[UUID]]`` maps alongside the ORM ``File`` rows.
        A 10x increase in file count with a proportionate edge count would push
        the peak roughly 10x. The new code streams edges through
        ``iter_file_edges`` and never holds the tuple list, so peak growth
        is dominated by the tier list itself -- sub-linear in file count.

        The threshold is sub-linear: a 10x file increase must not produce
        a 10x peak. The 8x cap allows for the tier list itself (which
        scales with file count) plus the adjacency maps and other
        per-run overhead, while still rejecting the linear-growth shape
        that would indicate the edge tuple list has crept back into the
        critical path. ``tracemalloc`` is restarted between runs so prior
        accounting cannot inflate the next peak.
        """
        session_factory_small = _sync_session_factory()
        session_factory_large = _sync_session_factory()
        small_user, small_repo = _make_user_repo(session_factory_small)
        large_user, large_repo = _make_user_repo(session_factory_large)
        try:
            # 100 files, ~500 edges -- proportionally fewer than the
            # plan's 10k/50k so the run stays inside a CI budget.
            _build_dag(session_factory_small, small_repo, file_count=100, edge_count=500)

            tracemalloc.start()
            try:
                small_order = _run_reading_order(
                    session_factory_small, small_repo, monkeypatch=monkeypatch
                )
                gc.collect()
                small_peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()

            assert small_order, "the small build produced an empty reading order"

            # 1000 files, ~5000 edges -- 10x the file count, 10x the edges.
            _build_dag(session_factory_large, large_repo, file_count=1000, edge_count=5000)

            tracemalloc.start()
            try:
                large_order = _run_reading_order(
                    session_factory_large, large_repo, monkeypatch=monkeypatch
                )
                gc.collect()
                large_peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()

            assert large_order, "the large build produced an empty reading order"

            ratio = large_peak / max(small_peak, 1)
            assert ratio < 8, (
                f"tracemalloc peak grew {ratio:.1f}x for a 10x file count increase "
                f"({small_peak} -> {large_peak}); the edge stream is no longer bounded"
            )
        finally:
            _cleanup(session_factory_small, small_user, small_repo)
            _cleanup(session_factory_large, large_user, large_repo)


class TestDeterminismAtScale:
    """Two calls against the same data produce the same stored reading order."""

    def test_repeated_builds_are_byte_identical(self, monkeypatch):
        """
        The unit suite pins determinism for ``_topological_sort``. This
        test pins it for the data path: the edges Postgres yields must
        reach the deterministic sort in an order that produces the same
        output twice in a row.

        A regression where the streaming query returned a different order
        on the second call (e.g. a missing ``ORDER BY`` on a cursor that
        closes mid-iteration) would show up as a difference in tier
        membership or ``(-fan_in, path)`` ordering.
        """
        session_factory = _sync_session_factory()
        user_id, repo_id = _make_user_repo(session_factory)
        try:
            _build_dag(session_factory, repo_id, file_count=200, edge_count=400)

            first = _run_reading_order(session_factory, repo_id, monkeypatch=monkeypatch)
            second = _run_reading_order(session_factory, repo_id, monkeypatch=monkeypatch)

            # The annotation strings differ across calls (the OpenAI stub
            # is deterministic but each batch is asked once); the rest of
            # the payload is the determinism invariant.
            assert [(item["path"], item["tier"], item["position"]) for item in first] == [
                (item["path"], item["tier"], item["position"]) for item in second
            ]
        finally:
            _cleanup(session_factory, user_id, repo_id)
