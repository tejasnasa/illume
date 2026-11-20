"""Headless ingestion of a pinned repository at its base commit.

This composes the existing pipeline pieces instead of running the Celery task, because
the task fetches pull requests from GitHub (the most recently updated ones, which in an
active repository are almost all newer than the base commit) and the harness needs
control over exactly which pull requests become history.

The order matters:

1. Create the evaluation user and a fresh ``Repository`` row.
2. Clone and check out the base commit.
3. Insert the most recent cached pull requests whose merge commit is an ancestor of the
   base commit. Doing this before analysis means the embedder indexes them with
   everything else, and nothing after the base commit ever enters the index.
4. Run the analysis stages.
5. Mark the repository ready at the base commit.
6. Verify no later data leaked in, on both rows and embeddings.

Commits and co-change pairs are safe by construction (the clone is detached at the base
commit and ``git log`` walks ancestors only); pull requests are the only leak path, which
is why the guard exists and is callable on its own.
"""

import logging
import secrets
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import Commit, Embedding, PullRequest, Repository, User
from app.services.cloner import cleanup_clone, clone_repository
from app.services.llm_config import LLMConfig
from app.services.pipeline import run_full_analysis
from app.services.pr_fetcher import _bulk_insert_pull_requests
from evals.corpus.corpus import CorpusRepo
from evals.corpus.report import corpus_counts
from evals.mining.github_cache import CachedPR, load_prs

logger = logging.getLogger(__name__)

GIT_TIMEOUT_SECONDS = 120


class LeakError(AssertionError):
    """Raised when data from after the base commit is present in an ingested repository."""


@dataclass(frozen=True)
class IngestResult:
    """What one ingestion produced.

    Attributes:
        repo_id: The new ``Repository`` row's id.
        user_id: The evaluation user's id.
        base_commit: The commit the repository was ingested at.
        inserted_pr_numbers: Pull request numbers inserted as history, ascending.
        considered_prs: How many cached pull requests were looked at before enough
            ancestors of the base commit were found.
        counts: Row counts as returned by ``corpus_counts``.
    """

    repo_id: object
    user_id: object
    base_commit: str
    inserted_pr_numbers: tuple[int, ...]
    considered_prs: int
    counts: dict = field(default_factory=dict)


def _git(clone_path: Path, *args: str) -> subprocess.CompletedProcess:
    """Run git in a clone and return the finished process without raising."""
    return subprocess.run(
        ["git", "-C", str(clone_path), *args],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )


def is_ancestor(clone_path: Path, sha: str, base_commit: str) -> bool:
    """Whether ``sha`` is an ancestor of, or equal to, ``base_commit``.

    Uses ``git merge-base --is-ancestor``, which is immune to the timestamp skew that
    rebases and clock drift introduce. A SHA the clone does not contain counts as not an
    ancestor.

    Args:
        clone_path: A clone that contains ``base_commit``.
        sha: The commit to test.
        base_commit: The pinned commit.

    Returns:
        ``True`` only when git exits 0.
    """
    if not sha:
        return False
    return _git(clone_path, "merge-base", "--is-ancestor", sha, base_commit).returncode == 0


def select_history_prs(
    prs: list[CachedPR], clone_path: Path, base_commit: str, limit: int
) -> tuple[list[CachedPR], int]:
    """Choose the most recent pull requests merged before the base commit.

    Args:
        prs: Every cached pull request.
        clone_path: A clone that contains ``base_commit``.
        base_commit: The pinned commit.
        limit: How many to keep.

    Returns:
        The chosen pull requests, newest first, and how many candidates were examined.
    """
    ordered = sorted(prs, key=lambda pr: (pr.merged_at, pr.number), reverse=True)
    chosen: list[CachedPR] = []
    examined = 0
    for pr in ordered:
        if len(chosen) >= limit:
            break
        examined += 1
        if is_ancestor(clone_path, pr.merge_commit_sha, base_commit):
            chosen.append(pr)
    return chosen, examined


def _normalise(pr: CachedPR) -> dict:
    """Map a cached pull request to the dict ``_bulk_insert_pull_requests`` expects."""
    return {
        "number": pr.number,
        "title": pr.title.strip(),
        "description": pr.body.strip(),
        "author": pr.author,
        "reviewers": [],
        "files_changed": len(pr.files) if pr.files is not None else 0,
        "merged_at": pr.merged_at,
    }


def assert_no_leak(
    db: Session,
    repo_id,
    clone_path: Path,
    base_commit: str,
    inserted_pr_numbers,
    *,
    merge_shas: Mapping[int, str] | None = None,
) -> None:
    """Fail when anything newer than the base commit is present for a repository.

    Checks, in order: every ``PullRequest`` row's number was one the harness inserted;
    every ``Commit`` row's hash is an ancestor of (or equal to) the base commit; every
    pull-request ``Embedding`` points at one of the inserted rows; and, when given, every
    inserted pull request's merge commit is an ancestor of the base commit.

    Args:
        db: A sync session.
        repo_id: The repository to check.
        clone_path: A clone that contains ``base_commit``.
        base_commit: The pinned commit.
        inserted_pr_numbers: The numbers the harness inserted.
        merge_shas: Optional map from pull request number to merge commit SHA, for the
            defence-in-depth ancestry check.

    Raises:
        LeakError: On the first violation found, naming what leaked.
    """
    allowed = set(inserted_pr_numbers)

    pr_rows = db.execute(
        select(PullRequest.id, PullRequest.number).where(PullRequest.repository_id == repo_id)
    ).all()
    stray = sorted(number for _, number in pr_rows if number not in allowed)
    if stray:
        raise LeakError(f"pull request rows not inserted by the harness: {stray[:10]}")
    allowed_ids = {row_id for row_id, _ in pr_rows}

    listing = _git(clone_path, "rev-list", base_commit)
    if listing.returncode != 0:
        raise LeakError(f"cannot list history at {base_commit}: {listing.stderr.strip()}")
    reachable = set(listing.stdout.split())
    hashes = db.execute(select(Commit.hash).where(Commit.repository_id == repo_id)).scalars()
    later = sorted(h for h in hashes if h not in reachable)
    if later:
        raise LeakError(f"commits that are not ancestors of {base_commit[:12]}: {later[:5]}")

    source_ids = db.execute(
        select(Embedding.source_id).where(
            Embedding.repository_id == repo_id, Embedding.source_type == "pull_request"
        )
    ).scalars()
    orphans = sorted(str(s) for s in source_ids if s not in allowed_ids)
    if orphans:
        raise LeakError(f"pull request embeddings with no inserted row: {orphans[:5]}")

    for number, sha in (merge_shas or {}).items():
        if not is_ancestor(clone_path, sha, base_commit):
            raise LeakError(f"pull request #{number} merge commit is not an ancestor of the base")


def _get_or_create_user(db: Session, email: str) -> User:
    """Return the evaluation user, creating it with an unguessable password if needed."""
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is not None:
        return user
    user = User(
        email=email,
        name="Eval Harness",
        password=hash_password(secrets.token_urlsafe(32)),
    )
    db.add(user)
    db.commit()
    return user


def _noop_publish(event: str, message: str, **kwargs) -> None:
    """Swallow the pipeline's higher-level frames; nothing listens during an eval."""


def ingest_at_base(
    db: Session,
    *,
    corpus_repo: CorpusRepo,
    user_email: str,
    cache_dir: Path,
    llm_config: LLMConfig | None,
    clone_override: Path | None = None,
) -> IngestResult:
    """Ingest one corpus repository at its base commit with no later data.

    Args:
        db: A sync session on the database to ingest into.
        corpus_repo: The pinned repository.
        user_email: Email of the owning user; created on first use.
        cache_dir: Root of the GitHub cache that supplies history pull requests.
        llm_config: Credentials for the generation stages; ``None`` uses the server key.
        clone_override: An existing full clone to use instead of cloning ``corpus_repo.url``.
            It is checked out at the base commit and left in place afterwards.

    Returns:
        The repository id, the pull requests inserted and the resulting row counts.

    Raises:
        LeakError: If anything newer than the base commit made it into the database.
    """
    base = corpus_repo.base_commit
    user = _get_or_create_user(db, user_email)
    repo = Repository(
        user_id=user.id,
        github_url=corpus_repo.url,
        name=corpus_repo.name,
        status="pending",
    )
    db.add(repo)
    db.commit()
    repo_id, user_id = repo.id, user.id

    owned_clone = clone_override is None
    clone_path: Path | None = None
    try:
        if clone_override is None:
            clone_path, _, _ = clone_repository(
                db, None, repo, commit_sha=base, manage_status=False
            )
        else:
            clone_path = Path(clone_override)
            checkout = _git(clone_path, "checkout", "--detach", base)
            if checkout.returncode != 0:
                raise RuntimeError(f"cannot check out {base}: {checkout.stderr.strip()}")

        chosen, examined = select_history_prs(
            load_prs(cache_dir, corpus_repo.slug), clone_path, base, corpus_repo.history_prs
        )
        _bulk_insert_pull_requests(db, repo_id, [_normalise(pr) for pr in chosen])
        inserted = tuple(sorted(pr.number for pr in chosen))

        run_full_analysis(
            db,
            repo,
            clone_path,
            None,
            _noop_publish,
            manage_status=False,
            overlap_llm=False,
            llm_config=llm_config,
        )

        repo.status = "ready"
        repo.ingested_commit_sha = base
        repo.ingested_branch = "detached"
        db.commit()

        assert_no_leak(
            db,
            repo_id,
            clone_path,
            base,
            inserted,
            merge_shas={pr.number: pr.merge_commit_sha for pr in chosen},
        )
        return IngestResult(
            repo_id=repo_id,
            user_id=user_id,
            base_commit=base,
            inserted_pr_numbers=inserted,
            considered_prs=examined,
            counts=corpus_counts(db, repo_id),
        )
    except Exception:
        db.rollback()
        try:
            failed = db.get(Repository, repo_id)
            if failed is not None:
                failed.status = "failed"
                db.commit()
        except Exception:
            db.rollback()
            logger.exception("could not mark repository %s failed", repo_id)
        raise
    finally:
        if owned_clone and clone_path is not None:
            cleanup_clone(clone_path)


__all__ = [
    "IngestResult",
    "LeakError",
    "assert_no_leak",
    "ingest_at_base",
    "is_ancestor",
    "select_history_prs",
]
