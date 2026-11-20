"""Snapshot and restore, exercised on a scratch database made for the test.

The shared test database is never dumped or restored here: other workers are using it.
"""

import shutil
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from evals.corpus.snapshot import SnapshotError, restore, snapshot

pytestmark = pytest.mark.integration

if not (shutil.which("pg_dump") and shutil.which("pg_restore")):
    pytest.skip("pg_dump / pg_restore are not on PATH", allow_module_level=True)


def _scratch_url(name: str) -> str:
    from tests.conftest import TEST_SYNC_DB_URL

    return make_url(TEST_SYNC_DB_URL).set(database=name).render_as_string(hide_password=False)


@pytest.fixture
def scratch_db():
    """A throwaway database on the test server, dropped afterwards."""
    from tests.conftest import TEST_SYNC_DB_URL

    name = f"eval_snapshot_{uuid.uuid4().hex}"
    admin = create_engine(TEST_SYNC_DB_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = _scratch_url(name)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.execute(text("CREATE TABLE owners (id int PRIMARY KEY, name text NOT NULL)"))
        connection.execute(
            text(
                "CREATE TABLE items (id int PRIMARY KEY, owner_id int NOT NULL "
                "REFERENCES owners(id), label text, vec vector(3))"
            )
        )
        connection.execute(text("CREATE TABLE tags (id int PRIMARY KEY, item_id int, tag text)"))
        connection.execute(text("INSERT INTO owners VALUES (1, 'ada'), (2, 'grace')"))
        connection.execute(
            text("INSERT INTO items VALUES (1, 1, 'a', '[1,2,3]'), (2, 2, 'b', '[4,5,6]')")
        )
        connection.execute(text("INSERT INTO tags VALUES (1, 1, 'x'), (2, 1, 'y'), (3, 2, 'z')"))
    yield url, engine
    engine.dispose()
    with admin.connect() as connection:
        connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": name},
        )
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    admin.dispose()


TABLES = ("owners", "items", "tags")


def _counts(engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table: connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            for table in TABLES
        }


def test_snapshot_reset_restore_gives_identical_row_counts(scratch_db, tmp_path):
    url, engine = scratch_db
    before = _counts(engine)
    assert before == {"owners": 2, "items": 2, "tags": 3}

    dump = snapshot(url, tmp_path / "snapshots" / "demo.dump")
    assert dump.is_file() and dump.stat().st_size > 0

    with engine.begin() as connection:
        connection.execute(text("TRUNCATE tags, items, owners"))
        connection.execute(text("INSERT INTO owners VALUES (9, 'intruder')"))
    assert _counts(engine) == {"owners": 1, "items": 0, "tags": 0}

    restore(url, dump)
    engine.dispose()
    assert _counts(engine) == before
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT vec::text FROM items WHERE id = 2")).scalar()
            == "[4,5,6]"
        )


def test_restoring_a_missing_snapshot_is_an_error(scratch_db, tmp_path):
    url, _ = scratch_db
    with pytest.raises(SnapshotError, match="no snapshot"):
        restore(url, tmp_path / "absent.dump")


def test_a_missing_tool_is_reported_clearly(scratch_db, tmp_path, monkeypatch):
    url, _ = scratch_db
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(SnapshotError, match="pg_dump was not found"):
        snapshot(url, tmp_path / "x.dump")


def test_the_password_is_passed_by_environment_only(scratch_db, tmp_path, monkeypatch):
    import subprocess

    url, _ = scratch_db
    seen = {}
    real_run = subprocess.run

    def spy(command, **kwargs):
        seen["command"] = command
        seen["env"] = kwargs["env"]
        return real_run(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)
    snapshot(url, tmp_path / "spy.dump")
    password = make_url(url).password
    assert password and seen["env"]["PGPASSWORD"] == password
    assert "--password" not in seen["command"]
    assert not any("://" in str(part) or f":{password}@" in str(part) for part in seen["command"])
