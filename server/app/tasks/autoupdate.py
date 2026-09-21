"""
Auto-update sweep tunables and dispatch glue.

The beat schedule dispatches ``sweep_due_repositories`` every
``SWEEP_INTERVAL_MINUTES`` minutes; the sweep itself runs in a worker
process as a Celery task. The constants below are declared here from day
one so every other module that needs them imports from a stable location
rather than reading them off the codebase piecemeal.

Constants are module-level, not ``Settings`` fields, on purpose: every
field of ``Settings`` is required and ``.env`` is gitignored, so a new
field is another way for a fresh checkout or a standalone script to fail
to instantiate. A code change plus a deploy is the intent for every value
below.
"""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime, timedelta
from typing import Iterable

from celery.schedules import schedule as celery_schedule
from sqlalchemy import or_, select, update

from app.core.celery import celery
from app.core.database import SyncSessionLocal
from app.models.repository import Repository
from app.models.user import User
from app.tasks.sync import sync_repository

logger = logging.getLogger(__name__)

# Global kill switch. When False, the sweep returns without enqueuing anything.
# Set False to disable auto-update across the whole deployment without touching
# any individual repository's toggle.
AUTO_UPDATE_ENABLED: bool = True

# How often the beat process wakes and asks the database which repos are due.
# 10 minutes gives a 6-hour-interval repo a six-tick window of latency without
# dominating the database with sweeps.
SWEEP_INTERVAL_MINUTES: int = 10

# How long a sync holds its lease before another sync (or the next sweep on a
# crashed worker) may reclaim the repo. Picked generously above the slowest
# realistic sync (large repo, full LLM pass) so a still-running sync is never
# stolen, but tight enough that a SIGKILL'd worker hands control back within a
# reasonable window.
SYNC_LEASE_MINUTES: int = 60

# Maximum repositories a single sweep tick can claim. Bounds the worst-case
# fan-out from one beat tick -- a runaway claim storm from a misbeating
# scheduler cannot flood the worker queue.
SWEEP_BATCH_LIMIT: int = 50

# Seconds of random jitter added on top of ``auto_update_interval_hours`` when
# the sweep bumps ``next_sync_at``. Without jitter, every 6-hour-interval repo
# syncs on the same boundary; the cluster goes from "everyone idle" to
# "everyone syncing" once per cycle, multiplying peak memory by the active
# sync count.
SWEEP_OFFSET_JITTER_SECONDS: float = 60.0

# Thresholds at which an incremental update gives up and falls back to a full
# re-ingest. Cheap deterministic work scales linearly with the diff, but past
# some size the bookkeeping is more expensive than rebuilding from scratch.

# Hard cap on changed-file count. Above this, full rebuild -- correct and the
# only safe option.
SYNC_FULL_MAX_FILES: int = 500

# Soft cap: changed files as a fraction of the repo's total file count. A change
# that touches most of the repo is a re-ingest in all but name.
SYNC_FULL_MAX_RATIO: float = 0.5

# Failure isolation: after this many consecutive sync failures the auto-update
# toggle flips itself off, the UI shows "paused after N failures", and the user
# is expected to investigate rather than have the worker keep hammering.
SYNC_MAX_CONSECUTIVE_FAILURES: int = 3

# Backoff base for ``next_sync_at`` after a sync failure, in minutes. Doubles on
# each consecutive failure up to ``SYNC_MAX_CONSECUTIVE_FAILURES`` -- so a repo
# that fails once waits 5 minutes, fails twice waits 10, fails three times
# pauses outright.
SYNC_BACKOFF_BASE_MINUTES: int = 5


def _claim_predicate(now: datetime):
    """Build the WHERE clause the sweep uses to find claimable rows.

    A repo is claimable when *all* of these hold:

    * its ``status`` is ``ready`` -- never re-claim a row mid-ingest;
      that's how two workers would step on the same data;
    * ``auto_update_enabled`` is true -- the user-toggle (or the per-repo
      auto-pause after ``SYNC_MAX_CONSECUTIVE_FAILURES``) is on;
    * its ``next_sync_at`` is due -- either unset (``NULL`` for repos
      never synchronised) or in the past;
    * its ``sync_lease_expires_at`` is *not* a live one -- either unset
      or already expired. A live lease means an in-flight sync, which
      the sweep must never preempt.

    Centralising the predicate makes it possible to reuse the same
    expression in tests (whose matcher wants the booleans broken out)
    rather than re-deriving it from the SQL.
    """
    return (
        Repository.status == "ready",
        Repository.auto_update_enabled.is_(True),
        or_(
            Repository.next_sync_at.is_(None),
            Repository.next_sync_at <= now,
        ),
        or_(
            Repository.sync_lease_expires_at.is_(None),
            Repository.sync_lease_expires_at < now,
        ),
    )


def _next_offset_seconds() -> float:
    """Random jitter in seconds for a single claim's ``next_sync_at``.

    Pulled out so tests can replace it with a fixed value, keeping their
    expected timestamps exact.
    """
    return random.uniform(0.0, SWEEP_OFFSET_JITTER_SECONDS)


@celery.task(name="app.tasks.autoupdate.sweep_due_repositories")
def sweep_due_repositories() -> int:
    """Claim every repo the database says is due, dispatch a sync for each.

    Each beat tick the sweep:

    1. Respects the deployment-wide ``AUTO_UPDATE_ENABLED`` kill switch.
    2. Reads the current time once and reuses it throughout the run --
       freezegun-pinned tests get a deterministic wall clock.
    3. SELECTs candidates ordered by ``next_sync_at`` (oldest-due first,
       ``NULL`` treated as "due immediately"), capped at
       ``SWEEP_BATCH_LIMIT``.
    4. For each candidate, atomically bumps ``next_sync_at`` with a
       ``WHERE`` predicate that includes the same claim predicate as
       the SELECT -- so a worker that picked the same row loses the
       race without ever setting ``next_sync_at`` forward twice.
    5. Looks up each claimed repo's owner token in a single query, then
       dispatches ``sync_repository.delay(...)`` for the claimed rows
       only.

    Returned to beat: the number of repos dispatched. Beat itself does
    not act on the integer; logging it from the same process makes the
    sweep visible in worker output.

    Returns:
        Number of sync tasks the sweep successfully dispatched.
    """
    if not AUTO_UPDATE_ENABLED:
        return 0

    now = datetime.now(UTC)
    session = SyncSessionLocal()
    try:
        candidates = session.scalars(
            select(Repository)
            .where(*_claim_predicate(now))
            .order_by(Repository.next_sync_at.asc().nulls_first())
            .limit(SWEEP_BATCH_LIMIT)
        ).all()

        claimed: list[Repository] = []
        for repo in candidates:
            new_next = now + timedelta(
                hours=repo.auto_update_interval_hours,
                seconds=_next_offset_seconds(),
            )
            # ``_claim_predicate`` returns a tuple of expressions; reusing
            # them inside the UPDATE makes the CAS guard match the SELECT
            # to the byte. ``rowcount`` lets the loop skip a row that
            # another sweep claimed first.
            result = session.execute(
                update(Repository)
                .where(Repository.id == repo.id, *_claim_predicate(now))
                .values(next_sync_at=new_next)
            )
            if result.rowcount == 1:
                claimed.append(repo)

        if not claimed:
            session.commit()
            return 0

        token_for_user = _lookup_owner_tokens(session, (r.user_id for r in claimed))

        dispatched = 0
        for repo in claimed:
            sync_repository.delay(str(repo.id), token_for_user.get(repo.user_id))
            dispatched += 1
        session.commit()
        if dispatched:
            logger.info(
                "Sweep dispatched %d sync task(s) at %s",
                dispatched,
                now.isoformat(),
            )
        return dispatched
    finally:
        session.close()


def _lookup_owner_tokens(session, user_ids: Iterable) -> dict:
    """Return a ``{user_id: github_access_token}`` map for the given ids.

    Users without a stored token (e.g. accounts that never linked GitHub)
    appear in the dict with ``None`` -- ``sync_repository`` treats ``None``
    as "public repo, no auth".
    """
    rows = session.execute(
        select(User.id, User.github_access_token).where(User.id.in_(list(user_ids)))
    ).all()
    return {row[0]: row[1] for row in rows}


# Register the beat schedule here, where the cadence constant lives.
# ``celery.py`` cannot declare the entry itself -- importing the constant
# from this module creates a circular import -- so the entry is added
# once this module has finished importing, when ``celery`` is already a
# fully-built Celery instance with the rest of its configuration.
celery.conf.beat_schedule = {
    "sweep-due-repositories": {
        "task": "app.tasks.autoupdate.sweep_due_repositories",
        "schedule": celery_schedule(run_every=SWEEP_INTERVAL_MINUTES * 60.0),
    },
}
