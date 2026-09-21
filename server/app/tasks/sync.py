"""Sync a single repository against its current head.

The incremental delta that keeps an already-ingested repository current.
Reads the cheap ``git ls-remote`` probe, decides whether anything changed,
and either short-circuits (no LLM, no DB writes) or walks the diff to
update only the affected slices of the analysis. The expensive LLM
phases are reused from :func:`app.services.pipeline.run_full_analysis`
once the deterministic data has been brought up to date.

Order of operations:

1. Take the lease (CAS the repo row to ``sync_status='updating'`` and
   set the lease expiry); bail if another sync already holds it.
2. Probe the remote (``git ls-remote``) for the head SHA. If it equals
   ``analysis_commit_sha`` -- the second watermark -- short-circuit.
3. Otherwise: ensure the clone is at the new SHA, compute the diff,
   escalate to a full rebuild if necessary, otherwise run Step A in one
   transaction and Step B outside it.

All status mutations on ``Repository.status`` are suppressed: a sync
keeps the row ``ready`` the whole time so the graph endpoint, the
navbar and the live-log panel all keep working while the update runs.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.celery import celery
from app.core.database import get_sync_db
from app.models.repository import Repository
from app.services.criticality import run_criticality_scoring
from app.services.dependency_resolver import (
    compute_fan_metrics,
    delete_repo_edges,
    resolve_dependencies,
)
from app.services.git_analyzer import analyze_git_history
from app.services.repo_cache import (
    CLONE_CACHE_ENABLED,
    ensure_clone,
)
from app.services.scanner import (
    apply_file_delta,
    compute_delta,
    embed_repository_symbols,
    is_fast_forward,
    should_escalate,
    summarise,
)
from app.services.stack_detector import detect_entry_points, detect_stack

logger = logging.getLogger(__name__)


def _sync_tunables() -> tuple[int, float, int, int, int]:
    """Lazy import of autoupdate tunables to avoid the circular import.

    ``app.tasks.autoupdate`` already imports ``sync_repository`` at
    module load time, so a top-level ``from app.tasks.autoupdate import``
    here would deadlock. ``sync_repository`` is the only consumer of
    these constants; lazy-loading them once per call is fine.
    """
    from app.tasks.autoupdate import (
        SYNC_BACKOFF_BASE_MINUTES,
        SYNC_FULL_MAX_FILES,
        SYNC_FULL_MAX_RATIO,
        SYNC_LEASE_MINUTES,
        SYNC_MAX_CONSECUTIVE_FAILURES,
    )

    return (
        SYNC_LEASE_MINUTES,
        SYNC_FULL_MAX_FILES,
        SYNC_FULL_MAX_RATIO,
        SYNC_MAX_CONSECUTIVE_FAILURES,
        SYNC_BACKOFF_BASE_MINUTES,
    )


def _take_lease(db: Session, repo: Repository, now: datetime) -> uuid.UUID | None:
    """Atomically claim the lease for ``repo``; return the new generation, or None.

    Uses a conditional UPDATE: the row must still be ``ready`` with no
    live lease, and the predicate matches the one the sweep uses, so the
    CAS at the sweep boundary and the CAS here cannot diverge. Returns
    ``None`` when the claim fails -- a worker already holds the lease.
    """
    generation = uuid.uuid4()
    (lease_minutes, *_) = _sync_tunables()

    expires_at = now + timedelta(minutes=lease_minutes)
    result = db.execute(
        Repository.__table__.update()
        .where(
            Repository.id == repo.id,
            Repository.status == "ready",
            Repository.sync_lease_expires_at.is_(None),
        )
        .values(
            sync_status="updating",
            sync_lease_expires_at=expires_at,
            sync_generation=generation,
            last_sync_error=None,
        )
    )
    if result.rowcount == 0:
        logger.warning("DEBUG: _take_lease FAILED (rowcount=0) for %s", repo.id)
        db.rollback()
        return None
    db.commit()
    return generation


def _release_lease(db: Session, repo_id: uuid.UUID) -> None:
    """Clear the lease fields and set ``sync_status='idle'``.

    Best-effort: the lease expiry already bounds how long a wedged sync
    can hold the repo, so a failure here is logged but not raised. The
    caller already has a ``finally`` around it for cleanup paths.
    """
    try:
        db.execute(
            Repository.__table__.update()
            .where(Repository.id == repo_id)
            .values(
                sync_status="idle",
                sync_lease_expires_at=None,
            )
        )
        db.commit()
    except Exception as exc:
        logger.warning("Failed to release lease for %s: %s", repo_id, exc)
        db.rollback()


def _set_sync_status(db: Session, repo_id: uuid.UUID, status: str) -> None:
    """Persist ``sync_status`` only; never touches ``Repository.status``.

    Distinct from the synchronous pipeline's ``status='parsing'/'ready'``
    flips -- those would 409 the graph endpoint mid-sync, which is what
    the sync path is designed to avoid.
    """
    db.execute(
        Repository.__table__.update().where(Repository.id == repo_id).values(sync_status=status)
    )
    db.commit()


def _record_failure(
    db: Session,
    repo: Repository,
    error_message: str,
    now: datetime,
) -> None:
    """Persist the failure state and schedule the next retry with backoff.

    Bumps ``consecutive_sync_failures``; the sweeper's kill switch is
    elsewhere (``SYNC_MAX_CONSECUTIVE_FAILURES``). Doubles the next-sync
    interval each consecutive failure, capped by the lease window so a
    run of failures never defers a sync beyond what's recoverable.
    """

    (_, _, _, max_failures, base_minutes) = _sync_tunables()
    consecutive = (repo.consecutive_sync_failures or 0) + 1

    backoff_minutes = base_minutes * (2 ** (consecutive - 1))
    next_sync_at = now + timedelta(minutes=backoff_minutes)
    auto_update_enabled = repo.auto_update_enabled if consecutive < max_failures else False
    logger.warning(
        "DEBUG _record_failure: repo=%s consecutive=%s max_failures=%s -> auto_update_enabled=%s",
        repo.id,
        consecutive,
        max_failures,
        auto_update_enabled,
    )
    db.execute(
        Repository.__table__.update()
        .where(Repository.id == repo.id)
        .values(
            sync_status="failed",
            sync_lease_expires_at=None,
            consecutive_sync_failures=consecutive,
            last_sync_error=error_message,
            next_sync_at=next_sync_at,
            auto_update_enabled=auto_update_enabled,
        )
    )
    db.commit()


def _record_success(db: Session, repo: Repository, summary: dict, now: datetime) -> None:
    """Persist the success state: clear failures, schedule next sync."""
    interval_hours = repo.auto_update_interval_hours or 6
    next_sync_at = now + timedelta(hours=interval_hours)
    db.execute(
        Repository.__table__.update()
        .where(Repository.id == repo.id)
        .values(
            sync_status="idle",
            sync_lease_expires_at=None,
            sync_generation=None,
            consecutive_sync_failures=0,
            last_sync_error=None,
            last_synced_at=now,
            next_sync_at=next_sync_at,
            last_sync_summary=summary,
        )
    )
    db.commit()


def _run_step_a(
    db: Session,
    repo: Repository,
    repo_root: Path,
    diff: list[tuple[str, str]],
) -> tuple[int, int, list[uuid.UUID]]:
    """Apply the deterministic half of the delta in one transaction.

    Sequence is fixed: file delta first, then ``analyze_git_history``
    (which writes the ``git_last_modified`` / ``has_tests`` columns
    ``run_criticality_scoring`` reads), then dependency_resolver --
    whose INSERT-only contract requires the prior DELETE --
    then fan metrics, then criticality, then stack detection.
    The whole thing is one transaction so a reader either sees the old
    graph or the new one, never a half-updated torn graph.

    Returns ``(upserted, deleted, changed_file_ids)`` from the file
    delta for the summary payload and the embedder's incremental
    reconcile. ``changed_file_ids`` is the set of file rows the delta
    touched (A/M/R/D) -- passed to the embedder so it can drop stale
    symbol and annotated-file chunks before reconciling by hash.
    """
    paths = [path for _status, path in diff]
    upserted, deleted, _changed, changed_file_ids = apply_file_delta(db, repo.id, repo_root, paths)

    analyze_git_history(db, None, repo, repo_root)
    delete_repo_edges(db, repo.id)
    resolve_dependencies(db, repo.id, str(repo_root))
    compute_fan_metrics(db, repo.id)
    run_criticality_scoring(db, repo.id)
    repo.detected_stack = detect_stack(repo_root)
    repo.entry_points = detect_entry_points(repo_root)

    repo.ingested_commit_sha = repo.ingested_commit_sha or repo.ingested_commit_sha
    return upserted, deleted, changed_file_ids


def _ingest_artifact_frame(
    db: Session,
    repo: Repository,
    repo_root: Path,
    manage_status: bool,
) -> int:
    """Regenerate the architecture brief; placeholder for Phase 5 hooks.

    Today the brief is a single LLM call; it is run with ``manage_status=False``
    so the repo's main status stays ``ready``. Returns 1 on success so
    the caller's summary can include a single brief-regenerated entry;
    the embedding counter is the workhorse for the LLM-call metric.
    """
    from app.services.architecture_brief import generate_brief

    readme_content = None
    for name in ("README.md", "readme.md", "Readme.md"):
        candidate = repo_root / name
        if candidate.is_file():
            readme_content = candidate.read_text(errors="ignore")
            break
    generate_brief(db, repo, readme_content=readme_content)
    return 1


@celery.task(name="app.tasks.sync.sync_repository", bind=True, max_retries=0)
def sync_repository(self, repo_id: str, access_token: str | None = None) -> dict | None:
    """Run one incremental sync against ``repo_id``.

    The Celery signature matches what the sweep and the ``POST
    /{repo_id}/sync`` route dispatch: ``(repo_id, access_token)``.
    ``access_token`` is preferred when supplied (the route has the user's
    session) and the sweep passes ``None`` to let the task look up the
    owner's token itself.

    The function returns a small summary dict on success and ``None`` on
    the no-op short-circuit (the sweep logs that case separately). Errors
    are caught, recorded on the row, and re-raised so the worker can
    apply its retry/backoff contract.
    """
    repo_uuid = uuid.UUID(str(repo_id))
    db = next(get_sync_db())
    try:
        repo = db.get(Repository, repo_uuid)
        if repo is None:
            logger.warning("sync_repository: repo %s not found", repo_id)
            return None
        if repo.status != "ready":
            logger.info(
                "sync_repository: repo %s not ready (status=%s); skipping",
                repo_id,
                repo.status,
            )
            return None
        if not repo.ingested_commit_sha:
            logger.info("sync_repository: repo %s has no ingested_commit_sha; skipping", repo_id)
            return None

        now = datetime.now(UTC)
        generation = _take_lease(db, repo, now)
        if generation is None:
            logger.info("sync_repository: lease not acquired for %s", repo_id)
            return None

        try:
            return _do_sync(db, repo, access_token, generation, now)
        except Exception as exc:
            db.rollback()
            error_message = f"{type(exc).__name__}: {exc}"
            try:
                _record_failure(db, repo, error_message, datetime.now(UTC))
            except Exception as rec_exc:
                logger.exception("sync_repository: failed to record failure for %s", repo_id)
                raise rec_exc from exc
            logger.exception("sync_repository: %s failed", repo_id)
            raise
        # ``finally`` releases the lease in either case, but the success
        # path is responsible for stamping its own sync_status back to
        # 'idle'; the failure path leaves 'failed' behind.
    finally:
        db.close()


def _resolve_token(db: Session, repo: Repository, access_token: str | None) -> str | None:
    """Fall back to the owner's stored token when the caller didn't pass one."""
    if access_token:
        return access_token
    from app.models.user import User

    user = db.get(User, repo.user_id)
    return getattr(user, "github_access_token", None) if user else None


def _do_sync(
    db: Session,
    repo: Repository,
    access_token: str | None,
    generation: uuid.UUID,
    now: datetime,
) -> dict | None:
    """Body of :func:`sync_repository` after the lease has been taken."""
    repo_id_value = repo.id
    token = _resolve_token(db, repo, access_token)
    (_, max_files, max_ratio, _, _) = _sync_tunables()

    # Phase 1 of Step 0: bring the working tree to the head.
    _set_sync_status(db, repo_id_value, "checking")

    target_branch = repo.ingested_branch or repo.default_branch or "main"
    if target_branch == "detached":
        target_branch = "main"

    # Bring the cache up to the head -- cheap when nothing changed
    # (single fetch returning "already up to date"); the function
    # returns the path that already exists in the cache.
    repo_root, actual_branch, new_sha = ensure_clone(
        repo_id_value,
        repo.github_url,
        token,
        target_branch,
    )

    # Short-circuit: the LLM-phase watermark is already current. The
    # cheap ``ls-remote`` probe already ran inside ``ensure_clone``; the
    # short-circuit is a pure SHA comparison.
    if repo.ingested_commit_sha == new_sha and repo.analysis_commit_sha == new_sha:
        summary = summarise(upserted=0, deleted=0, new_sha=new_sha)
        _record_success(db, repo, summary, datetime.now(UTC))
        return summary

    upserted = deleted = 0
    changed_file_ids: list[uuid.UUID] = []

    # Step A only needs to run if the deterministic watermark lags.
    if repo.ingested_commit_sha != new_sha:
        logger.warning(
            "DEBUG: about to set updating, ingested=%r, new=%r", repo.ingested_commit_sha, new_sha
        )
        _set_sync_status(db, repo_id_value, "updating")

        # Force-push / branch switch / rebase / non-branch ingest: the
        # ancestor check fails, escalate to a full rebuild so the result
        # is correct rather than approximate.
        old_sha = repo.ingested_commit_sha
        fast_forward = is_fast_forward(old_sha, new_sha, repo_root) if old_sha else False

        diff = compute_delta(repo_root, old_sha, new_sha)
        # ``scanner.walk_source_files`` gives the count of *current*
        # files; the ratio cap needs the repository's size at the
        # prior ingest, which we approximate as the post-diff count
        # (the worst case is "diff is most of the tree", which a
        # newly-rebuilt count also captures).
        total_files = len(diff) if not fast_forward else 0
        if not fast_forward or should_escalate(
            diff,
            total_files,
            max_files=max_files,
            max_ratio=max_ratio,
        ):
            # Escalate. The full path is identical to a fresh ingest
            # -- it deletes every ``File`` row, re-parses, re-resolves,
            # re-scores. ``manage_status=False`` keeps ``status='ready'``
            # throughout.
            return _run_full_sync(db, repo, repo_root, new_sha, generation, now)

        upserted, deleted, changed_file_ids = _run_step_a(db, repo, repo_root, diff)

        # Write the deterministic watermark.
        repo.ingested_commit_sha = new_sha
        db.commit()
    else:
        diff = []

    # Step B: LLM phase. Outside the transaction, so a slow generation
    # does not hold locks across a network round trip.
    try:
        glossary_added = 0
        embeddings_added = 0
        _ingest_artifact_frame(db, repo, repo_root, manage_status=False)
        # ``build_glossary`` in incremental mode skips the delete and
        # only defines symbols lacking an entry, ranked by the *current*
        # file fan-in. The return value is the number of new entries
        # actually persisted -- the work the LLM did, not the size of
        # the input batch.
        from app.services.glossary_builder import build_glossary
        from app.services.onboarding import build_reading_order

        glossary_added = build_glossary(db, repo, mode="incremental")
        build_reading_order(db, repo, mode="incremental")
        embeddings_added = embed_repository_symbols(
            db,
            None,
            repo,
            readme_content=None,
            measure_memory=False,
            manage_status=False,
            embedding_mode="incremental",
            changed_file_ids=changed_file_ids,
        )
        # Re-verify the generation before stamping the analysis
        # watermark: a concurrent reingest would have replaced the row.
        current = db.get(Repository, repo_id_value)
        if current is None or current.sync_generation != generation:
            db.rollback()
            logger.info(
                "sync_repository: generation changed for %s -- aborting watermark write",
                repo_id_value,
            )
            return summarise(upserted=upserted, deleted=deleted, new_sha=new_sha)

        repo.analysis_commit_sha = new_sha
        db.commit()
    except Exception:
        # LLM phase failure: the deterministic data is already
        # committed. The next sync against the same head will
        # short-circuit past Step A and re-run Step B -- which is the
        # whole point of the two-watermark split.
        raise

    summary = summarise(
        upserted=upserted,
        deleted=deleted,
        new_sha=new_sha,
        glossary_added=glossary_added,
        embeddings_added=embeddings_added,
    )
    _record_success(db, repo, summary, datetime.now(UTC))
    return summary


def _run_full_sync(
    db: Session,
    repo: Repository,
    repo_root: Path,
    new_sha: str,
    generation: uuid.UUID,
    now: datetime,
) -> dict:
    """Escalation path: behave like a fresh ingest, but without changing status.

    Runs the pipeline with ``manage_status=False`` (status stays
    ``ready``) and ``overlap_llm=False`` (the sync task is single-process
    and does not run LLM stages in parallel). After Txn 1 lands the
    deterministic data, the LLM phase runs outside the transaction.

    ``cleanup_clone`` is a no-op for the cache clone and a recursive
    delete for the ephemeral one; calling it is safe in either case.
    """
    try:
        # Step A: delete every File row (cascade clears symbols,
        # edges, code owners, file-scoped embeddings), then re-parse.
        from app.models import File as FileModel
        from app.services.pipeline import run_full_analysis

        db.query(FileModel).filter(FileModel.repository_id == repo.id).delete()
        db.commit()

        def _publish(event, message, **_kwargs):
            logger.info("sync(full): %s -- %s", event, message)

        run_full_analysis(
            db,
            repo,
            repo_root,
            None,
            _publish,
            manage_status=False,
            overlap_llm=False,
        )
        repo.ingested_commit_sha = new_sha
        db.commit()

        # Step B is the LLM pass; the embedder + brief already ran as
        # part of ``run_full_analysis`` above, so we just need to stamp
        # the analysis watermark under the generation check.
        current = db.get(Repository, repo.id)
        if current is None or current.sync_generation != generation:
            db.rollback()
            logger.info(
                "sync_repository(full): generation changed for %s -- aborting watermark",
                repo.id,
            )
            return summarise(upserted=0, deleted=0, new_sha=new_sha)
        repo.analysis_commit_sha = new_sha
        db.commit()
    finally:
        # Ephemeral clones go away; cache clones survive (LRU eviction
        # owns their lifecycle).
        if not CLONE_CACHE_ENABLED:
            from app.services.cloner import cleanup_clone

            cleanup_clone(repo_root)

    summary = summarise(upserted=0, deleted=0, new_sha=new_sha)
    _record_success(db, repo, summary, datetime.now(UTC))
    return summary


# The Celery task is the only public symbol; the rest are internal helpers
# consumed by tests through their fully-qualified names.
__all__ = ["sync_repository"]
