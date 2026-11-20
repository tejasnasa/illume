"""Tests for pinned ingestion and the leak guard.

Each test drives ``ingest_at_base`` against the branchy sample repository with a local
path standing in for the GitHub URL, the LLM and embeddings faked, and the database the
shared test stack.
"""

import subprocess
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import AstSymbol, Commit, Embedding, File, PullRequest, Repository
from evals.corpus import ingest as ingest_module
from evals.corpus.ingest import LeakError, assert_no_leak, is_ancestor
from tests.evals.conftest import (
    EARLY_TEXT,
    HISTORY_TEXT,
    POST_BASE_TEXT,
    UNKNOWN_SHA,
)
from tests.fixtures import sample_repo


def _git(root, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout


def _paths(db, repo_id) -> set[str]:
    return set(db.execute(select(File.path).where(File.repository_id == repo_id)).scalars())


def _numbers(db, repo_id) -> set[int]:
    return set(
        db.execute(select(PullRequest.number).where(PullRequest.repository_id == repo_id)).scalars()
    )


def _chunks(db, repo_id) -> list[str]:
    return list(
        db.execute(select(Embedding.chunk_text).where(Embedding.repository_id == repo_id)).scalars()
    )


@pytest.mark.unit
class TestAncestry:
    def test_an_ancestor_and_the_commit_itself_pass(self, history):
        assert is_ancestor(history.root, history.first, history.base)
        assert is_ancestor(history.root, history.base, history.base)

    def test_a_later_commit_fails(self, history):
        assert not is_ancestor(history.root, history.pr_b_merge, history.base)

    def test_an_unknown_object_counts_as_not_an_ancestor(self, history):
        assert not is_ancestor(history.root, UNKNOWN_SHA, history.base)
        assert not is_ancestor(history.root, "", history.base)

    def test_the_early_dated_merge_is_not_an_ancestor_despite_its_timestamp(self, history):
        stamp = _git(history.root, "show", "-s", "--format=%ct", history.pr_early_merge)
        base_stamp = _git(history.root, "show", "-s", "--format=%ct", history.base)
        assert int(stamp) < int(base_stamp)
        assert not is_ancestor(history.root, history.pr_early_merge, history.base)


@pytest.mark.integration
class TestIngestAtBase:
    def test_ingesting_at_the_second_commit_leaves_exactly_that_commits_state(
        self, ingest, db, history
    ):
        result = ingest(history.second)

        tree = set(
            _git(history.root, "ls-tree", "-r", "-z", "--name-only", history.second).split("\0")
        )
        paths = _paths(db, result.repo_id)
        assert paths <= tree
        assert "src/pkg/nested.py" in paths and "src/late.py" in paths
        assert "src/nested.py" not in paths

        # `later` still lives in late.py at this commit; the move comes afterwards.
        owner = db.execute(
            select(File.path)
            .join(AstSymbol, AstSymbol.file_id == File.id)
            .where(File.repository_id == result.repo_id, AstSymbol.name == "later")
        ).scalar_one()
        assert owner == "src/late.py"

        hashes = set(
            db.execute(select(Commit.hash).where(Commit.repository_id == result.repo_id)).scalars()
        )
        assert hashes == {history.first, history.second}

    def test_ingesting_at_the_base_sees_the_moved_function_and_only_ancestor_commits(
        self, ingest, db, history
    ):
        result = ingest()

        owner = db.execute(
            select(File.path)
            .join(AstSymbol, AstSymbol.file_id == File.id)
            .where(File.repository_id == result.repo_id, AstSymbol.name == "later")
        ).scalar_one()
        assert owner == "src/util.py"

        reachable = set(_git(history.root, "rev-list", history.base).split())
        hashes = set(
            db.execute(select(Commit.hash).where(Commit.repository_id == result.repo_id)).scalars()
        )
        assert hashes <= reachable
        assert {history.whitespace, history.moved} <= hashes
        assert history.pr_b_merge not in hashes
        assert history.pr_early_merge not in hashes

    def test_the_repository_is_marked_ready_at_the_base(self, ingest, db, history):
        result = ingest()
        repo = db.get(Repository, result.repo_id)
        assert (repo.status, repo.ingested_commit_sha, repo.ingested_branch) == (
            "ready",
            history.base,
            "detached",
        )

    def test_a_pr_merged_after_the_base_is_never_inserted_or_embedded(self, ingest, db):
        result = ingest()

        assert sample_repo.PR_B_NUMBER not in _numbers(db, result.repo_id)
        chunks = _chunks(db, result.repo_id)
        assert not any(POST_BASE_TEXT in chunk for chunk in chunks)
        # Positive control: ordinary history did reach the index, so the absence above
        # is the filter's doing and not an index that never held PRs.
        assert any(HISTORY_TEXT in chunk for chunk in chunks)

    def test_a_pr_with_an_earlier_timestamp_but_no_ancestry_is_excluded(self, ingest, db):
        result = ingest()

        assert sample_repo.PR_EARLY_NUMBER not in _numbers(db, result.repo_id)
        assert not any(EARLY_TEXT in chunk for chunk in _chunks(db, result.repo_id))

    def test_only_ancestor_prs_become_history(self, ingest, db):
        result = ingest()
        assert result.inserted_pr_numbers == (sample_repo.PR_A_NUMBER,)
        assert _numbers(db, result.repo_id) == {sample_repo.PR_A_NUMBER}
        assert result.counts["prs"] == 1
        assert result.counts["embeddings"]["pull_request"] == 1

    def test_a_base_before_every_pr_has_no_pr_history(self, ingest, db, history):
        result = ingest(history.second)
        assert result.inserted_pr_numbers == ()
        assert _numbers(db, result.repo_id) == set()

    def test_history_prs_keeps_the_most_recent_ancestors(self, ingest, history, cache_dir, db):
        from evals.mining.github_cache import CachedPR, save_pr
        from tests.evals.conftest import corpus_repo_for

        # A second ancestor merged earlier than #101; with a limit of one only #101 stays.
        older = CachedPR(
            number=90,
            title="older",
            body="older body",
            author="ada",
            merged_at=datetime(2026, 1, 20, tzinfo=UTC),
            merge_commit_sha=history.first,
            files=None,
            labels=(),
            user_type="User",
        )
        save_pr(cache_dir, corpus_repo_for(history).slug, older)

        result = ingest(history_prs=1)
        assert result.inserted_pr_numbers == (sample_repo.PR_A_NUMBER,)

        result_all = ingest()
        assert result_all.inserted_pr_numbers == (90, sample_repo.PR_A_NUMBER)

    def test_an_existing_clone_is_used_and_left_in_place(self, db, history, cache_dir, monkeypatch):
        from evals.corpus.ingest import ingest_at_base
        from tests.evals.conftest import corpus_repo_for
        from tests.fixtures import openai_stub

        openai_stub.install(monkeypatch)
        clone = history.root.parent / "existing-clone"
        _git(history.root.parent, "clone", "--quiet", str(history.root), str(clone))

        result = ingest_at_base(
            db,
            corpus_repo=corpus_repo_for(history),
            user_email=f"eval-test-{uuid.uuid4().hex[:8]}@example.com",
            cache_dir=cache_dir,
            llm_config=None,
            clone_override=clone,
        )
        assert clone.is_dir()
        assert result.inserted_pr_numbers == (sample_repo.PR_A_NUMBER,)

    def test_the_guard_runs_inside_ingestion_and_catches_an_unfiltered_selection(
        self, ingest, monkeypatch
    ):
        def no_filter(prs, clone_path, base_commit, limit):
            return sorted(prs, key=lambda pr: pr.number), len(prs)

        monkeypatch.setattr(ingest_module, "select_history_prs", no_filter)
        with pytest.raises(LeakError):
            ingest()


@pytest.mark.integration
class TestLeakGuard:
    def _clone(self, history, tmp_path):
        clone = tmp_path / "guard-clone"
        _git(tmp_path, "clone", "--quiet", str(history.root), str(clone))
        return clone

    def test_a_clean_ingest_passes(self, ingest, db, history, tmp_path):
        result = ingest()
        assert_no_leak(
            db,
            result.repo_id,
            self._clone(history, tmp_path),
            history.base,
            result.inserted_pr_numbers,
        )

    def test_a_post_base_pr_row_fails_the_guard(self, ingest, db, history, tmp_path):
        result = ingest()
        db.add(
            PullRequest(
                repository_id=result.repo_id,
                number=sample_repo.PR_B_NUMBER,
                title="late",
                description=POST_BASE_TEXT,
                author="ada",
            )
        )
        db.commit()
        with pytest.raises(LeakError, match="pull request rows"):
            assert_no_leak(
                db,
                result.repo_id,
                self._clone(history, tmp_path),
                history.base,
                result.inserted_pr_numbers,
            )

    def test_a_stray_pr_embedding_fails_the_guard(self, ingest, db, history, tmp_path):
        result = ingest()
        db.add(
            Embedding(
                source_id=uuid.uuid4(),
                repository_id=result.repo_id,
                chunk_text=f"PR #102: late\n{POST_BASE_TEXT}",
                embedding=[0.0] * 1536,
                source_type="pull_request",
            )
        )
        db.commit()
        with pytest.raises(LeakError, match="embeddings"):
            assert_no_leak(
                db,
                result.repo_id,
                self._clone(history, tmp_path),
                history.base,
                result.inserted_pr_numbers,
            )

    def test_a_commit_newer_than_the_base_fails_the_guard(self, ingest, db, history, tmp_path):
        result = ingest()
        db.add(
            Commit(
                repository_id=result.repo_id,
                hash=history.pr_b_merge,
                author_name="Ada",
                author_email="ada@example.com",
                message="later",
                authored_at=datetime(2026, 5, 1, tzinfo=UTC),
            )
        )
        db.commit()
        with pytest.raises(LeakError, match="ancestors"):
            assert_no_leak(
                db,
                result.repo_id,
                self._clone(history, tmp_path),
                history.base,
                result.inserted_pr_numbers,
            )

    def test_a_merge_sha_that_is_not_an_ancestor_fails_the_guard(
        self, ingest, db, history, tmp_path
    ):
        result = ingest()
        with pytest.raises(LeakError, match="not an ancestor"):
            assert_no_leak(
                db,
                result.repo_id,
                self._clone(history, tmp_path),
                history.base,
                result.inserted_pr_numbers,
                merge_shas={sample_repo.PR_EARLY_NUMBER: history.pr_early_merge},
            )
