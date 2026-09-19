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
from app.services.file_graph import query_file_edges
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
