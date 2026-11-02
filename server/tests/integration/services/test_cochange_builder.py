"""``build_cochange``: turning stored commits into ``file_cochange`` rows.

The builder is synchronous and never commits, so these tests run on a sync
session whose work is rolled back at the end.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.core.security import hash_password
from app.models import Commit, File, Repository, User
from app.models.file_cochange import FileCochange
from app.services.cochange import (
    MAX_FILES_PER_COMMIT,
    MAX_PARTNERS_PER_FILE,
    _select_pairs,
    build_cochange,
)
from tests.conftest import TEST_SYNC_DB_URL

pytestmark = pytest.mark.integration


@pytest.fixture
def db(migrated_db):
    """A sync session that is rolled back, never committed."""
    engine = create_engine(TEST_SYNC_DB_URL)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        engine.dispose()


def _repo(db, name: str = "cochange") -> Repository:
    user = User(
        email=f"cochange-{uuid.uuid4().hex[:8]}@example.com",
        name="Cochange",
        password=hash_password("correct horse battery staple"),
    )
    db.add(user)
    db.flush()
    repo = Repository(
        user_id=user.id,
        github_url=f"https://github.com/example/{name}-{uuid.uuid4().hex[:6]}",
        name=name,
        status="ready",
        default_branch="main",
    )
    db.add(repo)
    db.flush()
    return repo


def _files(db, repo: Repository, paths) -> dict[str, File]:
    files = {path: File(repository_id=repo.id, path=path, language="python") for path in paths}
    db.add_all(files.values())
    db.flush()
    return files


_commit_counter = iter(range(1, 10**9))


def _commit(db, repo: Repository, paths, *, times: int = 1) -> None:
    for _ in range(times):
        number = next(_commit_counter)
        db.add(
            Commit(
                repository_id=repo.id,
                hash=f"{number:040x}",
                author_name="Ada",
                author_email="ada@example.com",
                message=f"commit {number}",
                files_changed=len(paths),
                changed_files_list=list(paths),
                authored_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    db.flush()


def _rows(db, repo: Repository) -> dict[frozenset[str], FileCochange]:
    path_of = {
        file_id: path
        for file_id, path in db.execute(
            select(File.id, File.path).where(File.repository_id == repo.id)
        )
    }
    return {
        frozenset((path_of[row.file_a_id], path_of[row.file_b_id])): row
        for row in db.scalars(select(FileCochange).where(FileCochange.repository_id == repo.id))
    }


def _pair(a: str, b: str) -> frozenset[str]:
    return frozenset((a, b))


def test_the_counts_and_jaccard_match_a_worked_example(db):
    repo = _repo(db)
    _files(db, repo, ["a.py", "b.py", "c.py"])
    _commit(db, repo, ["a.py", "b.py"], times=2)
    _commit(db, repo, ["a.py", "c.py"])
    _commit(db, repo, ["a.py"])

    stored = build_cochange(db, repo.id)

    rows = _rows(db, repo)
    # a changed in 4 commits, b in 2, both in 2: 2 / (4 + 2 - 2).
    assert stored == 1
    assert set(rows) == {_pair("a.py", "b.py")}
    row = rows[_pair("a.py", "b.py")]
    assert row.together == 2
    assert {row.a_count, row.b_count} == {4, 2}
    assert row.jaccard == pytest.approx(0.5)


def test_counts_follow_the_stored_column_order(db):
    repo = _repo(db)
    files = _files(db, repo, ["a.py", "b.py"])
    _commit(db, repo, ["a.py", "b.py"], times=2)
    _commit(db, repo, ["a.py"], times=3)

    build_cochange(db, repo.id)

    row = _rows(db, repo)[_pair("a.py", "b.py")]
    by_file = {row.file_a_id: row.a_count, row.file_b_id: row.b_count}
    assert by_file == {files["a.py"].id: 5, files["b.py"].id: 2}


def test_a_pair_needs_two_commits_together(db):
    repo = _repo(db)
    _files(db, repo, ["a.py", "b.py", "c.py"])
    _commit(db, repo, ["a.py", "b.py"])
    _commit(db, repo, ["a.py", "c.py"], times=2)

    assert build_cochange(db, repo.id) == 1
    assert set(_rows(db, repo)) == {_pair("a.py", "c.py")}


def test_a_commit_touching_more_than_thirty_files_is_ignored(db):
    repo = _repo(db)
    filler = [f"bulk/{i}.py" for i in range(MAX_FILES_PER_COMMIT)]
    _files(db, repo, ["a.py", "b.py", "x.py", "y.py", *filler])
    # Thirty files exactly is still a usable commit; thirty-one is not.
    _commit(db, repo, ["a.py", "b.py", *filler[: MAX_FILES_PER_COMMIT - 2]], times=2)
    _commit(db, repo, ["x.py", "y.py", *filler[: MAX_FILES_PER_COMMIT - 1]], times=2)

    build_cochange(db, repo.id)

    rows = _rows(db, repo)
    assert rows[_pair("a.py", "b.py")].together == 2
    # The two big commits would have made x and y a pair.
    assert _pair("x.py", "y.py") not in rows
    assert not any("x.py" in pair or "y.py" in pair for pair in rows)


def test_paths_that_no_longer_exist_are_dropped(db):
    repo = _repo(db)
    _files(db, repo, ["a.py", "b.py"])
    _commit(db, repo, ["a.py", "b.py", "deleted.py"], times=2)
    _commit(db, repo, ["a.py", "deleted.py", "gone.py"], times=3)

    build_cochange(db, repo.id)

    rows = _rows(db, repo)
    assert set(rows) == {_pair("a.py", "b.py")}
    # The deleted file adds nothing to a.py's count of five commits.
    assert max(rows[_pair("a.py", "b.py")].a_count, rows[_pair("a.py", "b.py")].b_count) == 5


def test_a_path_repeated_in_one_commit_counts_once(db):
    repo = _repo(db)
    _files(db, repo, ["a.py", "b.py"])
    _commit(db, repo, ["a.py", "a.py", "b.py"], times=2)

    build_cochange(db, repo.id)

    row = _rows(db, repo)[_pair("a.py", "b.py")]
    assert (row.together, row.a_count, row.b_count) == (2, 2, 2)
    assert row.jaccard == 1.0


def test_commits_without_a_file_list_are_skipped(db):
    repo = _repo(db)
    _files(db, repo, ["a.py", "b.py"])
    _commit(db, repo, ["a.py", "b.py"], times=2)
    db.add(
        Commit(
            repository_id=repo.id,
            hash="f" * 40,
            author_name="Ada",
            author_email="ada@example.com",
            message="legacy row",
            changed_files_list=None,
            authored_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    db.flush()

    assert build_cochange(db, repo.id) == 1


def test_a_pair_survives_if_it_is_in_the_top_fifty_of_either_file(db):
    repo = _repo(db)
    partners = [f"p{i:02d}.py" for i in range(MAX_PARTNERS_PER_FILE + 2)]
    _files(db, repo, ["hub.py", *partners])
    # The last two partners change with the hub least often, so they fall outside the
    # hub's fifty strongest. Each has only the hub as a partner, so each pair is the
    # strongest of the partner's own list and must be kept.
    for index, partner in enumerate(partners):
        _commit(db, repo, ["hub.py", partner], times=2 if index >= MAX_PARTNERS_PER_FILE else 4)

    stored = build_cochange(db, repo.id)

    rows = _rows(db, repo)
    assert stored == len(partners)
    for partner in partners[MAX_PARTNERS_PER_FILE:]:
        assert _pair("hub.py", partner) in rows


def test_a_pair_outside_the_top_fifty_of_both_files_is_dropped(db):
    repo = _repo(db)
    left = [f"l{i:02d}.py" for i in range(MAX_PARTNERS_PER_FILE)]
    right = [f"r{i:02d}.py" for i in range(MAX_PARTNERS_PER_FILE)]
    _files(db, repo, ["x.py", "y.py", *left, *right])
    for partner in left:
        _commit(db, repo, ["x.py", partner], times=3)
    for partner in right:
        _commit(db, repo, ["y.py", partner], times=3)
    # The only link between the two hubs, weaker than every other partner either has.
    _commit(db, repo, ["x.py", "y.py"], times=2)

    stored = build_cochange(db, repo.id)

    rows = _rows(db, repo)
    assert _pair("x.py", "y.py") not in rows
    assert stored == 2 * MAX_PARTNERS_PER_FILE


def test_ties_between_partners_break_by_partner_id():
    hub = uuid.UUID(int=1)
    partners = [uuid.UUID(int=1000 + i) for i in range(MAX_PARTNERS_PER_FILE + 1)]
    file_counts = {hub: 100}
    pair_counts = {}
    for partner in partners:
        file_counts[partner] = 100
        pair_counts[(hub, partner)] = 2
        # Each partner has fifty stronger partners of its own, so it does not keep the
        # hub through its own list and only the hub's ranking decides.
        for index in range(MAX_PARTNERS_PER_FILE):
            other = uuid.UUID(int=10_000_000 + partner.int * 100 + index)
            file_counts[other] = 100
            pair_counts[(partner, other)] = 50

    rows = _select_pairs(file_counts, pair_counts)

    kept = {b for a, b, *_ in rows if a == hub}
    # All the hub's pairs tie, so the highest partner id is the one cut.
    assert kept == set(partners[:-1])


def test_every_stored_pair_is_ordered_so_the_constraint_never_fires(db):
    repo = _repo(db)
    paths = [f"m{i:02d}.py" for i in range(24)]
    _files(db, repo, paths)
    # Every file with every other, over and over, so both orders of every pair occur.
    for first in range(len(paths)):
        for second in range(first + 1, len(paths)):
            _commit(db, repo, [paths[second], paths[first]], times=2)

    stored = build_cochange(db, repo.id)

    assert stored == len(paths) * (len(paths) - 1) // 2
    ordered = db.scalar(
        select(func.count())
        .select_from(FileCochange)
        .where(
            FileCochange.repository_id == repo.id, FileCochange.file_a_id < FileCochange.file_b_id
        )
    )
    assert ordered == stored


def test_python_uuid_order_agrees_with_postgres(db):
    ids = [uuid.uuid4() for _ in range(200)]
    # Includes values whose first bytes differ in sign, where a signed or little-endian
    # comparison would disagree.
    ids += [uuid.UUID(int=0), uuid.UUID(int=(1 << 127)), uuid.UUID(int=(1 << 128) - 1)]
    pairs = list(zip(ids, reversed(ids), strict=True))

    for first, second in pairs:
        in_postgres = db.scalar(
            text("SELECT CAST(:a AS uuid) < CAST(:b AS uuid)"), {"a": str(first), "b": str(second)}
        )
        assert in_postgres == (first < second)


def test_a_rebuild_replaces_the_old_rows(db):
    repo = _repo(db)
    files = _files(db, repo, ["a.py", "b.py", "c.py"])
    _commit(db, repo, ["a.py", "b.py"], times=2)
    assert build_cochange(db, repo.id) == 1
    # Nothing can be stale here: a row for a pair the commits no longer support is replaced.
    first, second = sorted((files["a.py"].id, files["c.py"].id))
    db.add(
        FileCochange(
            file_a_id=first,
            file_b_id=second,
            repository_id=repo.id,
            together=9,
            a_count=9,
            b_count=9,
            jaccard=1.0,
        )
    )
    db.flush()
    _commit(db, repo, ["b.py", "c.py"], times=2)

    stored = build_cochange(db, repo.id)

    assert stored == 2
    assert set(_rows(db, repo)) == {_pair("a.py", "b.py"), _pair("b.py", "c.py")}
    assert build_cochange(db, repo.id) == 2


def test_a_rebuild_with_no_usable_commits_empties_the_table(db):
    repo = _repo(db)
    _files(db, repo, ["a.py", "b.py"])
    _commit(db, repo, ["a.py", "b.py"], times=2)
    assert build_cochange(db, repo.id) == 1
    db.execute(text("DELETE FROM commits WHERE repository_id = :r"), {"r": repo.id})

    assert build_cochange(db, repo.id) == 0
    assert _rows(db, repo) == {}


def test_another_repositorys_rows_are_untouched(db):
    mine, theirs = _repo(db, "mine"), _repo(db, "theirs")
    _files(db, mine, ["a.py", "b.py"])
    _files(db, theirs, ["a.py", "b.py"])
    _commit(db, mine, ["a.py", "b.py"], times=2)
    _commit(db, theirs, ["a.py", "b.py"], times=3)
    assert build_cochange(db, theirs.id) == 1
    before = _rows(db, theirs)[_pair("a.py", "b.py")]
    snapshot = (before.file_a_id, before.file_b_id, before.together, before.a_count)

    build_cochange(db, mine.id)
    db.expire_all()

    after = _rows(db, theirs)[_pair("a.py", "b.py")]
    assert (after.file_a_id, after.file_b_id, after.together, after.a_count) == snapshot
    assert _rows(db, mine)[_pair("a.py", "b.py")].together == 2


def test_the_builder_does_not_commit(db, monkeypatch):
    repo = _repo(db)
    _files(db, repo, ["a.py", "b.py"])
    _commit(db, repo, ["a.py", "b.py"], times=2)

    def fail(*args, **kwargs):
        raise AssertionError("build_cochange committed the caller's transaction")

    monkeypatch.setattr(db, "commit", fail)

    assert build_cochange(db, repo.id) == 1
