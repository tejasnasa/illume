# ruff: noqa: F811
"""Marking chat answers stale when a sync changes the files they cited.

The marking runs on the sync session after the deterministic transaction has
committed. These tests drive it directly against the test database, and once end
to end through ``sync_repository`` against a local clone.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.chat_message import ChatMessage
from app.models.repository import Repository
from app.tasks import sync as sync_module
from app.tasks.sync import _changed_paths, _mark_stale_answers, sync_repository
from tests.fixtures import sample_repo
from tests.integration.tasks.test_sync_task import (  # noqa: F401
    _make_repo,
    _make_user,
    _rev,
    _write_row,
    cloner_stubbed_to_local,
    stubbed_openai,
    sync_repo,
    sync_session,
    two_comm_working,
)

pytestmark = pytest.mark.integration

HEAD = "b" * 40
LATER = "c" * 40


def add_message(session, repo, *, cited, answered="a" * 40, **fields) -> uuid.UUID:
    message = ChatMessage(
        repository_id=repo.id,
        user_id=repo.user_id,
        question="q",
        answer="a",
        sources=[],
        answered_commit_sha=answered,
        cited_paths=cited,
        **fields,
    )
    session.add(message)
    session.commit()
    return message.id


def reload(session, message_id) -> ChatMessage:
    session.expire_all()
    return session.get(ChatMessage, message_id)


class TestMarking:
    def test_only_answers_that_cited_a_changed_file_are_marked(self, sync_repo):
        factory, session = sync_repo
        repo = factory()
        hit = add_message(session, repo, cited=["src/a.py", "src/b.py"])
        miss = add_message(session, repo, cited=["src/c.py"])
        none = add_message(session, repo, cited=None)
        empty = add_message(session, repo, cited=[])

        _mark_stale_answers(session, repo.id, {"src/b.py", "src/z.py"}, HEAD)

        marked = reload(session, hit)
        assert marked.stale_at is not None
        assert marked.stale_paths == ["src/b.py"]
        assert marked.stale_commit_sha == HEAD
        for untouched in (miss, none, empty):
            row = reload(session, untouched)
            assert row.stale_at is None and row.stale_paths is None
            assert row.stale_commit_sha is None

    @pytest.mark.parametrize("changed", [{"src/a.py"}, None])
    def test_an_answer_given_at_the_new_head_is_not_marked(self, sync_repo, changed):
        factory, session = sync_repo
        repo = factory()
        current = add_message(session, repo, cited=["src/a.py"], answered=HEAD)

        _mark_stale_answers(session, repo.id, changed, HEAD)

        assert reload(session, current).stale_at is None

    def test_a_second_sync_adds_to_the_paths_and_keeps_the_first_time(self, sync_repo):
        factory, session = sync_repo
        repo = factory()
        message = add_message(session, repo, cited=["src/a.py", "src/b.py", "src/c.py"])

        _mark_stale_answers(session, repo.id, {"src/b.py"}, HEAD)
        first = reload(session, message).stale_at
        _mark_stale_answers(session, repo.id, {"src/c.py", "src/b.py", "src/other.py"}, LATER)

        row = reload(session, message)
        assert row.stale_paths == ["src/b.py", "src/c.py"]
        assert row.stale_at == first
        assert row.stale_commit_sha == LATER

    def test_another_repositorys_answers_are_left_alone(self, sync_repo):
        factory, session = sync_repo
        repo = factory()
        other = factory()
        mine = add_message(session, repo, cited=["src/a.py"])
        theirs = add_message(session, other, cited=["src/a.py"])

        _mark_stale_answers(session, repo.id, {"src/a.py"}, HEAD)

        assert reload(session, mine).stale_at is not None
        assert reload(session, theirs).stale_at is None

    def test_an_empty_change_set_marks_nothing(self, sync_repo):
        factory, session = sync_repo
        repo = factory()
        message = add_message(session, repo, cited=["src/a.py"])

        _mark_stale_answers(session, repo.id, set(), HEAD)

        assert reload(session, message).stale_at is None

    def test_an_unknown_change_set_marks_every_answer_with_cited_files(self, sync_repo):
        factory, session = sync_repo
        repo = factory()
        cited = add_message(session, repo, cited=["src/b.py", "src/a.py"])
        uncited = add_message(session, repo, cited=[])

        _mark_stale_answers(session, repo.id, None, HEAD)

        row = reload(session, cited)
        assert row.stale_paths == ["src/a.py", "src/b.py"]
        assert row.stale_commit_sha == HEAD
        assert reload(session, uncited).stale_at is None

    def test_a_path_with_a_quote_or_brace_is_matched_literally(self, sync_repo):
        factory, session = sync_repo
        repo = factory()
        odd = "src/it's {here}.py"
        message = add_message(session, repo, cited=[odd])

        _mark_stale_answers(session, repo.id, {odd}, HEAD)

        assert reload(session, message).stale_paths == [odd]


class TestAFailureNeverReachesTheSync:
    def test_a_failing_update_is_swallowed_and_the_session_stays_usable(
        self, sync_repo, monkeypatch
    ):
        factory, session = sync_repo
        repo = factory()
        message = add_message(session, repo, cited=["src/a.py"])

        def broken(*_args, **_kwargs):
            raise RuntimeError("the update failed")

        monkeypatch.setattr(sync_module, "mark_stale_answers", broken)

        _mark_stale_answers(session, repo.id, {"src/a.py"}, HEAD)

        assert reload(session, message).stale_at is None
        assert session.get(Repository, repo.id) is not None

    def test_a_database_error_rolls_back_only_the_marking(self, sync_repo, monkeypatch):
        from sqlalchemy import text

        factory, session = sync_repo
        repo = factory()
        message = add_message(session, repo, cited=["src/a.py"])

        def bad_sql(db, *_args, **_kwargs):
            db.execute(text("SELECT * FROM table_that_does_not_exist"))

        monkeypatch.setattr(sync_module, "mark_stale_answers", bad_sql)

        _mark_stale_answers(session, repo.id, {"src/a.py"}, HEAD)

        assert reload(session, message).stale_at is None
        # The session can still be used afterwards.
        assert session.get(Repository, repo.id) is not None


class TestChangedPaths:
    def test_lists_both_sides_of_a_rename(self, two_comm_working):
        root = two_comm_working

        paths = _changed_paths(root, _rev(root, "HEAD~1"), _rev(root, "HEAD"))

        assert paths == {sample_repo.RENAMED_FROM, sample_repo.RENAMED_TO, "src/late.py"}

    def test_an_unknown_base_gives_none(self, two_comm_working):
        root = two_comm_working

        assert _changed_paths(root, "f" * 40, _rev(root, "HEAD")) is None
        assert _changed_paths(root, None, _rev(root, "HEAD")) is None


class TestEndToEnd:
    def test_an_incremental_sync_marks_the_answers_that_cited_a_changed_file(
        self, cloner_stubbed_to_local, stubbed_openai, sync_repo
    ):
        factory, session = sync_repo
        repo = factory()
        root = cloner_stubbed_to_local
        base = _rev(root, "HEAD~1")
        head = sample_repo.head_sha(root)
        _write_row(
            session,
            repo,
            ingested_commit_sha=base,
            analysis_commit_sha=base,
            sync_lease_expires_at=None,
        )
        stale = add_message(session, repo, cited=["src/late.py", "src/unrelated.py"], answered=base)
        fresh = add_message(session, repo, cited=["src/unrelated.py"], answered=base)

        result = sync_repository.apply(args=[str(repo.id), None])
        assert result.successful()

        marked = reload(session, stale)
        assert marked.stale_paths == ["src/late.py"]
        assert marked.stale_commit_sha == head
        assert marked.answered_commit_sha == base
        assert reload(session, fresh).stale_at is None
