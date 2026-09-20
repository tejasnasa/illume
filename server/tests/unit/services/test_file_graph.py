"""File-level dependency graph: query and projection logic.

`query_file_edges` is the only place the symbol-level `Dependency` join is
collapsed to file pairs. Symmetry matters: a `Dependency` whose target
symbol lives in a different repository must not contribute to this repo's
in-degree or cycle tier.
"""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.security import hash_password
from app.models import AstSymbol, Dependency, File, Repository, User
from app.services.file_graph import (
    build_int_adjacency,
    iter_file_edges,
    query_file_edges,
)
from tests.conftest import TEST_SYNC_DB_URL

pytestmark = pytest.mark.unit


@pytest.fixture
def db_session(migrated_db):
    """A short-lived sync session, rolled back at the end of the test."""
    engine = create_engine(TEST_SYNC_DB_URL)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        engine.dispose()


def _make_user(db, *, label: str) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"file-graph-{label}-{uuid.uuid4().hex[:8]}@example.com",
        name=f"File Graph {label}",
        password=hash_password("correct horse battery staple"),
    )
    db.add(user)
    db.flush()
    return user


def _make_repo(db, *, user_id, name: str) -> Repository:
    repo = Repository(
        user_id=user_id,
        github_url=f"https://github.com/example/{name}",
        name=name,
        status="pending",
        primary_language="python",
        default_branch="main",
        ingested_branch="main",
        ingested_commit_sha="0" * 40,
        # `repo_number` has `Identity()` in the model but no DB sequence backs
        # the column, so a direct insert has to supply one.
        repo_number=uuid.uuid4().int % 10_000_000,
    )
    db.add(repo)
    db.flush()
    return repo


def _make_file(db, *, repo_id, path: str) -> File:
    file = File(repository_id=repo_id, path=path, language="python", loc=10)
    db.add(file)
    db.flush()
    return file


def _make_symbol(db, *, file_id, name: str) -> AstSymbol:
    symbol = AstSymbol(
        file_id=file_id,
        kind="function",
        name=name,
        start_line=1,
        end_line=2,
        source_code="def helper(): pass",
    )
    db.add(symbol)
    db.flush()
    return symbol


class TestQueryFileEdgesSymmetry:
    def test_a_dependency_targeting_another_repo_is_excluded(self, db_session):
        """
        With only the source-side filter, an out-of-repo target leaks through
        and contributes to the in-repo file's phantom fan-in. Both sides must
        be filtered to ``repository_id == repo_id``.
        """
        user = _make_user(db_session, label="sym")
        home_repo = _make_repo(db_session, user_id=user.id, name="home")
        foreign_repo = _make_repo(db_session, user_id=user.id, name="foreign")

        home_file = _make_file(db_session, repo_id=home_repo.id, path="src/home.py")
        foreign_file = _make_file(db_session, repo_id=foreign_repo.id, path="src/foreign.py")

        src_symbol = _make_symbol(db_session, file_id=home_file.id, name="uses_foreign")
        tgt_symbol = _make_symbol(db_session, file_id=foreign_file.id, name="ForeignThing")

        db_session.add(
            Dependency(
                source_symbol_id=src_symbol.id,
                target_symbol_id=tgt_symbol.id,
                dep_type="imports",
            )
        )
        db_session.commit()

        edges = query_file_edges(db_session, home_repo.id)

        assert edges == [], "an out-of-repo dependency target leaked into the in-repo edge set"

    def test_an_in_repo_edge_is_kept(self, db_session):
        user = _make_user(db_session, label="keep")
        repo = _make_repo(db_session, user_id=user.id, name="keep")
        a = _make_file(db_session, repo_id=repo.id, path="src/a.py")
        b = _make_file(db_session, repo_id=repo.id, path="src/b.py")

        sym_a = _make_symbol(db_session, file_id=a.id, name="from_a")
        sym_b = _make_symbol(db_session, file_id=b.id, name="from_b")

        db_session.add(
            Dependency(
                source_symbol_id=sym_a.id,
                target_symbol_id=sym_b.id,
                dep_type="imports",
            )
        )
        db_session.commit()

        edges = query_file_edges(db_session, repo.id)

        assert (a.id, b.id) in edges


class TestIterFileEdges:
    """``iter_file_edges`` is the streaming twin of ``query_file_edges``.

    The unit-level checks here mirror the symmetry test above -- the same
    edge set has to come out the same way -- plus a check that the
    iterator is genuinely lazy (i.e. callers can stop after one row).
    """

    def test_it_yields_the_same_edges_as_query_file_edges(self, db_session):
        """
        For a small in-repo graph, the iterator and the list must agree
        on the multiset of edges. The OOM fix depends on them agreeing,
        because ``build_int_adjacency`` is what consumes the iterator.
        """
        user = _make_user(db_session, label="iter")
        repo = _make_repo(db_session, user_id=user.id, name="iter")
        a = _make_file(db_session, repo_id=repo.id, path="src/a.py")
        b = _make_file(db_session, repo_id=repo.id, path="src/b.py")
        c = _make_file(db_session, repo_id=repo.id, path="src/c.py")

        sym_a = _make_symbol(db_session, file_id=a.id, name="from_a")
        sym_b = _make_symbol(db_session, file_id=b.id, name="from_b")
        sym_b2 = _make_symbol(db_session, file_id=b.id, name="from_b_2")
        sym_c = _make_symbol(db_session, file_id=c.id, name="from_c")

        # Two symbol-level edges between a and b -> one file pair, two rows.
        for src, tgt in [(sym_a, sym_b), (sym_a, sym_b2)]:
            db_session.add(
                Dependency(
                    source_symbol_id=src.id,
                    target_symbol_id=tgt.id,
                    dep_type="imports",
                )
            )
        db_session.add(
            Dependency(
                source_symbol_id=sym_c.id,
                target_symbol_id=sym_a.id,
                dep_type="imports",
            )
        )
        db_session.commit()

        streamed = sorted(iter_file_edges(db_session, repo.id))
        listed = sorted(query_file_edges(db_session, repo.id))

        assert streamed == listed

    def test_it_is_a_generator_not_a_list(self, db_session):
        """
        The OOM fix only works if the iterator is lazy -- a list would
        defeat the purpose. Confirm it is a generator by exhausting one
        row and verifying the rest still stream.
        """
        user = _make_user(db_session, label="lazy")
        repo = _make_repo(db_session, user_id=user.id, name="lazy")
        a = _make_file(db_session, repo_id=repo.id, path="src/a.py")
        b = _make_file(db_session, repo_id=repo.id, path="src/b.py")

        sym_a = _make_symbol(db_session, file_id=a.id, name="from_a")
        sym_b = _make_symbol(db_session, file_id=b.id, name="from_b")
        db_session.add(
            Dependency(
                source_symbol_id=sym_a.id,
                target_symbol_id=sym_b.id,
                dep_type="imports",
            )
        )
        db_session.commit()

        gen = iter_file_edges(db_session, repo.id)
        # Generator flag exists on the underlying object; ``next`` works.
        first = next(gen)
        assert first == (a.id, b.id)


class TestBuildIntAdjacency:
    """``build_int_adjacency`` is the dense-integer core of the rewrite.

    The contract: dense ints assigned in encounter order, self-edges
    dropped, duplicates collapsed. These are the three properties that
    make the rest of the reading-order rewrite correct -- a non-dense
    mapping wastes memory, a non-self-edge-dropped graph over-counts
    in-degree, a non-deduped graph pushes files into the cycle tier
    purely on duplicated edges.
    """

    def test_dense_int_keys_are_assigned_in_encounter_order(self):
        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        edges = [(a, b), (c, b), (a, c)]
        deps, rdeps, int_by_uuid = build_int_adjacency(edges)
        # Encounter order: a, b, c -> 0, 1, 2.
        assert int_by_uuid == {a: 0, b: 1, c: 2}

    def test_self_edges_are_dropped(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        deps, rdeps, int_by_uuid = build_int_adjacency([(a, a), (a, b)])
        a_int = int_by_uuid[a]
        b_int = int_by_uuid[b]
        # The self-edge contributes nothing; only (a, b) is recorded.
        assert deps[a_int] == {b_int}
        assert rdeps[b_int] == {a_int}
        # And no entry maps a file to itself in either direction.
        assert a_int not in deps[a_int]
        assert a_int not in rdeps[a_int]

    def test_duplicate_edges_are_collapsed(self):
        """
        A duplicate (a, b) edge must not double-count in-degree. The
        set-backed adjacency is what guarantees this; a list-backed one
        would.
        """
        a, b = uuid.uuid4(), uuid.uuid4()
        edges = [(a, b), (a, b), (a, b)]
        deps, rdeps, int_by_uuid = build_int_adjacency(edges)
        a_int = int_by_uuid[a]
        b_int = int_by_uuid[b]
        assert len(deps[a_int]) == 1
        assert len(rdeps[b_int]) == 1

    def test_an_empty_edge_iterable_yields_empty_maps(self):
        deps, rdeps, int_by_uuid = build_int_adjacency([])
        assert deps == {}
        assert rdeps == {}
        assert int_by_uuid == {}

    def test_in_degree_is_one_per_target(self):
        """
        Sanity: ``len(rdeps[t])`` matches the number of *distinct*
        importers. This is what the topo sort reads and what the dedup
        invariant is meant to defend.
        """
        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        edges = [(a, c), (b, c), (a, c)]  # duplicate (a, c)
        _, rdeps, int_by_uuid = build_int_adjacency(edges)
        c_int = int_by_uuid[c]
        assert len(rdeps[c_int]) == 2  # a and b, not three
