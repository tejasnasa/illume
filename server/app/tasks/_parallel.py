"""Helpers that run ingest stages on their own threads and sessions.

The ingest task overlaps I/O work: ``fetch_pull_requests`` runs while
the parser is walking the cloned tree, and the glossary + reading-order
builders run side-by-side. Each helper here:

* opens its own sync session (``SyncSessionLocal``), so the main task
  session is never shared across threads;
* accepts only scalar inputs (``UUID``, ``str``), so no ORM instance
  bound to the main thread's identity map leaks into a worker.

``GitHubClientError`` raised inside :func:`run_pr_fetch_in_thread` is
propagated to the caller via ``future.result()`` -- the existing
``TestFailurePath`` asserts this still surfaces as a retryable task
exception.
"""

from __future__ import annotations

from uuid import UUID

from app.core.database import SyncSessionLocal
from app.models.repository import Repository
from app.services.glossary_builder import build_glossary
from app.services.onboarding import build_reading_order
from app.services.pr_fetcher import fetch_pull_requests


def run_pr_fetch_in_thread(
    repo_id: UUID,
    github_url: str,
    access_token: str | None,
    redis_client,
) -> int:
    """Run ``fetch_pull_requests`` on its own sync session.

    Args:
        repo_id: Repository row id, captured as a scalar before the parse
            stage so this function does not touch the main session.
        github_url: ``Repository.github_url``; passed in for the same
            reason -- the function reads only this string and never
            reaches back into the parent session's ORM instances.
        access_token: Optional GitHub token.
        redis_client: Redis client for the standard progress log stream.

    Returns:
        Number of PR rows written (matches ``fetch_pull_requests``'s return).

    Raises:
        GitHubClientError: Propagated unchanged -- the outer thread
            re-raises it after ``future.result()``.
    """
    session = SyncSessionLocal()
    try:
        # ``fetch_pull_requests`` reads ``repo.id`` and ``repo.github_url``
        # only; constructing a transient object here lets us keep the
        # existing function signature without leaking the main session.
        repo = Repository(id=repo_id, github_url=github_url)
        return fetch_pull_requests(repo, access_token, session, redis_client)
    finally:
        session.close()


def run_glossary_in_thread(
    repo_id: UUID,
    github_url: str,
) -> int:
    """Run ``build_glossary`` on its own sync session.

    The glossary deletes and inserts ``GlossaryEntry`` rows, which is
    independent of the reading-order builder's writes to
    ``OnboardingGuide``.
    """
    session = SyncSessionLocal()
    try:
        repo = Repository(id=repo_id, github_url=github_url)
        return build_glossary(session, repo)
    finally:
        session.close()


def run_reading_order_in_thread(
    repo_id: UUID,
    github_url: str,
) -> None:
    """Run ``build_reading_order`` on its own sync session."""
    session = SyncSessionLocal()
    try:
        repo = Repository(id=repo_id, github_url=github_url)
        build_reading_order(session, repo)
    finally:
        session.close()
