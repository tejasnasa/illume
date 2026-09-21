"""The full repository analysis pipeline, factored out of the ingest task.

The single Celery task ``ingest_repository`` previously held the entire
body of a full ingest inline. That made the work unreusable: any path
that wanted to (re-)analyse a repo without deleting the row first -- the
upcoming incremental sync task, a future "recompute glossary" button,
anything else we have not built yet -- had to copy-paste the sequence
of stages and drift away from the original. This module is the single
shared sequence; the task wrapper owns the celery retry semantics and
the ``status = "ready"`` / ``status = "failed"`` transitions, and
nothing else.

Stage order, deliberately:

* ``process_repository_files`` (parse + dependency_resolver +
  compute_fan_metrics + detect_stack + entry_points)
* ``analyze_git_history`` -- must precede ``run_criticality_scoring``
  because criticality reads ``File.git_last_modified`` and ``File.has_tests``
  written only by ``_bulk_update_files``.
* ``run_criticality_scoring``.
* ``build_glossary`` and ``build_reading_order`` overlapped.
* ``embed_repository_symbols`` and ``generate_brief`` overlapped.

The ``manage_status`` parameter threads through the two ``_update_status``
call sites in ``scanner``: the initial ingest publishes the ``parsing`` /
``embedding`` frames so the client knows work is happening; the sync path
suppresses them so a ``ready`` repo never flips out of ``ready`` mid-update.
Cloning lives on the task wrapper too, so the third ``_update_status``
call site (cloner) is not threaded through here -- only the scanner sites
are, because the pipeline is invoked after the clone.

The returned README content is what the architecture brief consumes on the
parent thread. ``generate_brief`` itself runs in a worker thread; the brief
helper accepts the README as a string.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.repository import Repository
from app.services._stage_timer import stage
from app.services.criticality import run_criticality_scoring
from app.services.git_analyzer import analyze_git_history
from app.services.scanner import (
    embed_repository_symbols,
    process_repository_files,
)
from app.tasks._parallel import (
    run_brief_in_thread,
    run_glossary_in_thread,
    run_reading_order_in_thread,
)

logger = logging.getLogger(__name__)

_README_CANDIDATES = ("README.md", "readme.md", "Readme.md")


def _read_readme(repo_root: Path) -> str | None:
    """Return the first existing README in ``repo_root``, or ``None``.

    The clone is the source of truth here -- a README on the default
    branch's tip might differ from what the parser saw, but the brief
    needs the parser's view. Reading from the same on-disk tree avoids
    that drift.
    """
    for name in _README_CANDIDATES:
        candidate = repo_root / name
        if candidate.is_file():
            return candidate.read_text(errors="ignore")
    return None


def run_full_analysis(
    db: Session,
    repo: Repository,
    repo_root: Path,
    redis_client,
    publish,
    *,
    manage_status: bool = True,
    overlap_llm: bool = True,
) -> str | None:
    """Run every analysis stage for an already-cloned repository.

    Pure refactor of the body of :func:`app.tasks.ingest.ingest_repository`
    from the parse stage through the architecture brief. The task wrapper
    still owns the retry, the ``status = 'ready'`` flip, and the
    rollback-first failure handling; this function is the *work* in
    between.

    Pull-request fetching is *not* done here -- the initial-ingest task
    overlaps it with the parse stage on its own executor, and the sync
    task does not re-fetch PRs at all (PR descriptions are not refreshed).
    The GitHub OAuth token therefore lives on the task wrapper, not on
    this function.

    Args:
        db: Database session used for the sequential stages. The parallel
            helpers open their own sessions -- see :mod:`app.tasks._parallel`.
        repo: Repository row being analysed. Mutated in place (status,
            detected stack, entry points, ingested commit SHA).
        repo_root: Filesystem path to the cloned working tree. Caller owns
            its lifetime: the initial-ingest task removes it in a
            ``finally``; the sync task reuses a persistent cache clone.
        redis_client: Redis client for the standard progress log stream.
        publish: Callable matching ``publish(event, message, **kwargs)``
            used by the task wrapper to push status-update frames. The
            pipeline itself uses :func:`publish_log` for progress events;
            ``publish`` is reserved for higher-level frames the caller
            may want (``"criticality_started"``, ``"glossary_started"``,
            ``"reading_order_started"``, ``"embedding_started"``,
            ``"brief_started"``).
        manage_status: When ``False``, suppress the ``status='parsing'`` /
            ``status='embedding'`` / ``status='cloning'`` flips and their
            ``status_update`` log frames. Used by the sync path to keep a
            ``ready`` row's status alone while the update runs.
        overlap_llm: When ``True`` (default), run ``build_glossary`` and
            ``build_reading_order`` side-by-side, and run
            ``embed_repository_symbols`` alongside ``generate_brief`` --
            the same shape as the original ingest task. Set ``False`` to
            run them sequentially; the sync task does not have a parallel
            executor and uses this knob.

    Returns:
        The README content as a string, or ``None`` if no README was
        found. Returned rather than captured by the caller so the
        architecture brief (which runs in a worker thread) can be passed
        the text without the pipeline function having to know about it.

    Raises:
        Exception: Any stage failure propagates. The caller is responsible
            for catching, rolling back, and marking the repo failed --
            this function does not own that contract.
    """
    repo_id_value: UUID = repo.id
    repo_github_url: str = repo.github_url

    # ``process_repository_files`` carries its own per-stage timers
    # (parse / resolve_dependencies / compute_fan_metrics / detect_stack),
    # so it is deliberately not wrapped again here -- a nesting timer
    # would double-count their memory deltas.
    process_repository_files(db, redis_client, repo, repo_root, manage_status=manage_status)

    with stage("git_history"):
        analyze_git_history(db, redis_client, repo, repo_root)

    readme_content = _read_readme(repo_root)

    # PR fetching is intentionally NOT done here. The initial-ingest task
    # overlaps it with the parse stage in its own executor (the parse is
    # the longest single stage, and PR fetch is a pure network round-trip
    # against GitHub's API). The sync task deliberately skips it -- PR
    # descriptions are not refreshed, and ``_bulk_insert_pull_requests``'s
    # ``ON CONFLICT DO NOTHING`` means a re-fetch is a no-op, so calling it
    # here would just be a slow no-op on the sync path.

    publish("criticality_started", "Scoring file criticality...")
    with stage("criticality"):
        run_criticality_scoring(db, repo.id)

    if overlap_llm:
        publish("glossary_started", "Building project glossary...")
        publish("reading_order_started", "Generating recommended reading order...")
        parallel_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pipeline-llm")
        try:
            glossary_future = parallel_executor.submit(
                run_glossary_in_thread, repo_id_value, repo_github_url
            )
            reading_order_future = parallel_executor.submit(
                run_reading_order_in_thread, repo_id_value, repo_github_url
            )
            # Wall-clock for the overlapped pair. Comparing it against the
            # two helpers' individual walls shows whether the overlap paid
            # off: the pair should land near max(glossary, reading_order),
            # not their sum.
            with stage("glossary_and_reading_order_join", measure_memory=False):
                glossary_future.result()
                reading_order_future.result()
        finally:
            parallel_executor.shutdown(wait=True)
    else:
        from app.services.glossary_builder import build_glossary
        from app.services.onboarding import build_reading_order

        build_glossary(db, repo)
        build_reading_order(db, repo)

    publish("embedding_started", "Generating embeddings...")
    publish("brief_started", "Synthesizing AI architecture brief...")
    if overlap_llm:
        brief_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pipeline-brief")
        try:
            brief_future = brief_executor.submit(run_brief_in_thread, repo_id_value, readme_content)
            with stage("embed_and_brief_join", measure_memory=False):
                embed_repository_symbols(
                    db,
                    redis_client,
                    repo,
                    readme_content=readme_content,
                    measure_memory=False,
                    manage_status=manage_status,
                    embedding_mode="full",
                )
                # Joined before returning so a brief failure still surfaces
                # as an exception, exactly as it did when the call was
                # sequential.
                brief_future.result()
        finally:
            brief_executor.shutdown(wait=True)
    else:
        embed_repository_symbols(
            db,
            redis_client,
            repo,
            readme_content=readme_content,
            measure_memory=True,
            manage_status=manage_status,
            embedding_mode="full",
        )
        from app.services.architecture_brief import generate_brief

        generate_brief(db, repo, readme_content=readme_content)

    return readme_content
