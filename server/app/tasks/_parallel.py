"""Helpers that run ingest stages on their own threads and sessions.

The ingest task overlaps I/O work: ``fetch_pull_requests`` runs while
the parser is walking the cloned tree, the glossary + reading-order
builders run side-by-side, and the architecture brief runs alongside
the embedder. Each helper here:

* opens its own sync session (``SyncSessionLocal``), so the main task
  session is never shared across threads;
* accepts only scalar inputs (``UUID``, ``str``), so no ORM instance
  bound to the main thread's identity map leaks into a worker.

Every helper also carries its own ``stage`` timer with
``measure_memory=False``: each runs concurrently with another stage in the
same process, and ``tracemalloc``/``VmHWM`` are process-global, so a
memory delta measured across a concurrent window would be unattributable.
Wall-clock *is* per-thread correct, and comparing a helper's wall against
the wall of the join that collects it is what shows the overlap paid off.

``GitHubClientError`` raised inside :func:`run_pr_fetch_in_thread` is
propagated to the caller via ``future.result()`` -- the existing
``TestFailurePath`` asserts this still surfaces as a retryable task
exception.
"""

from __future__ import annotations

from uuid import UUID

from app.core.database import SyncSessionLocal
from app.models.repository import Repository
from app.services._stage_timer import stage
from app.services.architecture_brief import generate_brief
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
        with stage("pr_fetch", measure_memory=False):
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
        with stage("glossary", measure_memory=False):
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
        with stage("reading_order", measure_memory=False):
            build_reading_order(session, repo)
    finally:
        session.close()


def run_brief_in_thread(
    repo_id: UUID,
    readme_content: str | None,
) -> None:
    """Run ``generate_brief`` on its own sync session.

    Overlapped with the embedder, which is the longest remaining stage. The
    two are genuinely independent: the brief reads files, symbols,
    dependencies, code owners, glossary entries and the guide's reading
    order, and ``architecture_brief`` contains no reference to ``Embedding``
    at all -- verified, not assumed. Their writes do not collide either: the
    brief writes ``Repository.architecture_summary`` and the guide's
    ``architecture_brief``/``critical_files``, while the embedder writes
    ``Embedding`` rows and reads ``reading_order``. ``_upsert_guide`` only
    touches the columns it is passed, so the brief cannot clobber
    ``reading_order`` underneath the embedder.

    The repository is **loaded** rather than constructed transiently, unlike
    the other helpers here. ``generate_brief`` assigns
    ``repo.architecture_summary`` and calls ``db.add(repo)``; on a transient
    instance that marks it pending and inserts, so the row must be persistent
    in this session for the write to be a real ``UPDATE``.

    Args:
        repo_id: Repository row id, captured as a scalar by the caller.
        readme_content: README text for the prompt, read before the clone is
            cleaned up.

    Raises:
        ValueError: If the repository row no longer exists -- the task's
            outcome is then already decided and failing loudly beats writing
            nothing.
    """
    session = SyncSessionLocal()
    try:
        repo = session.get(Repository, repo_id)
        if repo is None:
            raise ValueError(f"Repository {repo_id} not found for brief generation")
        with stage("brief", measure_memory=False):
            generate_brief(session, repo, readme_content=readme_content)
    finally:
        session.close()
