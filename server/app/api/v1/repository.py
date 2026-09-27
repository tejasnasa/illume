"""Repository ingestion and management routes.

Handles creating repositories (which queues a Celery ingestion task),
re-ingesting, fetching/listing, deleting, and exporting the ``.illume``
bundle for ready repositories.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select

from app.api.deps import get_current_user, get_repo_for_user
from app.api.validation import FreeText, OptionalFreeText
from app.core.database import AsyncSession, get_async_db
from app.models import Repository, User
from app.services.entitlements import aclaim_free_ingestion
from app.services.illume_exporter import generate_illume_file
from app.services.llm_config import LLMConfig
from app.tasks.autoupdate import AUTO_UPDATE_ENABLED
from app.tasks.ingest import ingest_repository

# Aliased: the route handler below is itself named ``sync_repository``, so a
# plain import would be shadowed by the ``def`` and dispatch the handler
# instead of the Celery task.
from app.tasks.sync import sync_repository as sync_repository_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/repository", tags=["repository"])


# The cadence choices the PATCH endpoint accepts. Anything outside the set is a
# 422 -- the picker renders these as the only options, so silently mapping an
# out-of-set value would be hiding a UI bug behind a backend default.
ALLOWED_AUTO_UPDATE_INTERVALS: tuple[int, ...] = (1, 3, 6, 12, 24)


class RepositoryCreate(BaseModel):
    """Payload for ingesting a new repository at an optional ref."""

    github_url: FreeText
    branch: OptionalFreeText = None
    commit_sha: OptionalFreeText = None


class RepositoryReingest(BaseModel):
    """Payload for re-ingesting an existing repository at an optional ref."""

    branch: OptionalFreeText = None
    commit_sha: OptionalFreeText = None


class AutoUpdatePatch(BaseModel):
    """Payload for toggling auto-update and changing the sync cadence."""

    enabled: bool | None = Field(
        default=None,
        description="Set True to enable, False to disable, omit to leave the current value alone.",
    )
    interval_hours: int | None = Field(
        default=None,
        description="One of 1, 3, 6, 12, or 24. Omit to leave the current value alone.",
    )


class RepositoryResponse(BaseModel):
    """Serialized repository with analysis status and detected metadata."""

    id: uuid.UUID
    github_url: str
    name: str
    status: str
    architecture_summary: str | None
    repo_number: int
    primary_language: str | None
    detected_stack: dict | None
    entry_points: dict | list | None
    ingested_branch: str | None = None
    ingested_commit_sha: str | None = None
    analysis_commit_sha: str | None = None
    created_at: datetime
    updated_at: datetime
    auto_update_enabled: bool = False
    auto_update_interval_hours: int = 6
    next_sync_at: datetime | None = None
    last_synced_at: datetime | None = None
    sync_status: str = "idle"
    last_sync_error: str | None = None
    consecutive_sync_failures: int = 0
    last_sync_summary: dict | None = None
    # ``sync_available`` is user-level state surfaced on a repo DTO. The
    # keyless free tier cannot pay for auto-update or a manual sync, so the
    # UI disables the toggle + interval picker + ``Sync now`` button when
    # this is False. The flag is computed from the owning user's stored
    # credential -- the source of truth -- and populated by the route
    # handlers below. Threading it through here (rather than separately
    # in the navbar) keeps one GET /repository response feeding every
    # component.
    sync_available: bool = False

    model_config = ConfigDict(from_attributes=True)


def _extract_repo_name(github_url: str) -> str:
    """Derive the repo name from its GitHub URL's trailing segment."""
    return github_url.rstrip("/").split("/")[-1]


async def _user_has_ai_key(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Whether the user has a stored BYOK credential.

    Surfaces user-level state on a repo DTO (``RepositoryResponse.sync_available``).
    The keyless free tier cannot pay for auto-update or a manual sync -- this
    is the single source of truth for "may this repo sync at all?", and it
    matches the route-level gate in :func:`_require_user_key`.
    """
    from sqlalchemy import exists

    from app.models.user import User

    has_key = await db.execute(
        select(exists().where(User.id == user_id, User.ai_api_key.isnot(None)))
    )
    return bool(has_key.scalar())


# The exact text of the 402. Single source so every quota gate renders the
# same message and a future wording tweak is one edit, not five.
QUOTA_EXHAUSTED_DETAIL = (
    "Add your own API key to ingest another repository. Configure one in your account settings."
)


async def _require_quota_for_creation(db: AsyncSession, user: User) -> None:
    """Raise 402 if ``user`` cannot ingest another repository.

    BYOK users are admitted immediately -- their stored key is the
    authorisation. Keyless users must still have their one free ingestion;
    if it has already been spent, a freshly-keyless request gets a 402
    rather than a silent free pass.

    The free-tier claim and the ``Repository`` insert run inside the same
    transaction: a failed insert rolls the claim back, so a flaky
    downstream write does not burn the user's allowance. The claim
    function does **not** commit by design; the caller owns the commit.
    """
    config = LLMConfig.from_user(user)
    if config is not None:
        return

    if not await aclaim_free_ingestion(db, user.id):
        raise HTTPException(status_code=402, detail=QUOTA_EXHAUSTED_DETAIL)


def _require_user_key(user: User) -> None:
    """Raise 402 if ``user`` has no stored API key.

    Auto-update, manual sync, and re-ingest are never free: a keyless
    user who already had their free ingestion should not be able to keep
    the artefact set current on the operator's bill. The free-tier gate
    is at :func:`_require_quota_for_creation`; this gate covers the paths
    a free repo cannot reach while it is alive.
    """
    if LLMConfig.from_user(user) is None:
        raise HTTPException(status_code=402, detail=QUOTA_EXHAUSTED_DETAIL)


@router.post("", status_code=202)
async def create_repository(
    payload: RepositoryCreate,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """Create a repository record and queue background ingestion.

    Args:
        payload: GitHub URL plus optional branch/commit to ingest.
        request: Incoming request (unused beyond auth).
        db: Async database session.
        current_user: Owner the new repository is attributed to.

    Returns:
        Dict with the new ``repo_id`` and ``repo_num``.
    """
    await _require_quota_for_creation(db, current_user)

    # Free-ingestion repos deliberately ship with auto-update off: the
    # server key stops paying the moment the free ingestion ends. A user
    # who later saves a key can re-enable it from the settings screen;
    # until then the sweep's claim predicate never sees the row.
    repo = Repository(
        github_url=payload.github_url,
        name=_extract_repo_name(payload.github_url),
        user_id=current_user.id,
        auto_update_enabled=False,
        next_sync_at=None,
    )
    db.add(repo)
    await db.commit()
    await db.refresh(repo)

    ingest_repository.delay(
        str(repo.id),
        current_user.github_access_token,
        branch=payload.branch,
        commit_sha=payload.commit_sha,
    )
    logger.info(
        "Queued ingestion for repo %s (branch=%s, commit_sha=%s)",
        repo.id,
        payload.branch,
        payload.commit_sha,
    )

    return {"repo_id": str(repo.id), "repo_num": repo.repo_number}


@router.put("/{repo_id}/reingest", status_code=202)
async def reingest_repository(
    repo_id: uuid.UUID,
    payload: RepositoryReingest | None = None,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """Delete and recreate a repository to re-run full ingestion.

    Only repositories in ``ready`` or ``failed`` state can be re-ingested;
    the replacement row keeps the same ID and repo number.

    Args:
        repo_id: ID of the repository to re-ingest.
        payload: Optional branch/commit overrides.
        db: Async database session.
        current_user: Owner of the repository.

    Returns:
        Dict with the reused ``repo_id`` and ``repo_num``.

    Raises:
        HTTPException: 404 if not found, 400 if ingestion is still in
            progress, 402 if the owner has no stored API key.
    """
    _require_user_key(current_user)

    result = await db.execute(
        select(Repository).where(
            Repository.id == repo_id,
            Repository.user_id == current_user.id,
        )
    )
    repo = result.scalar_one_or_none()

    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    if repo.status not in ("ready", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Repository cannot be re-ingested while in status '{repo.status}'",
        )

    await db.execute(delete(Repository).where(Repository.id == repo_id))
    await db.commit()

    branch = payload.branch if payload else None
    commit_sha = payload.commit_sha if payload else None

    new_repo = Repository(
        id=repo_id,
        repo_number=repo.repo_number,
        github_url=repo.github_url,
        name=repo.name,
        user_id=repo.user_id,
        status="pending",
        # ``server_default`` populates these on a fresh insert; copy the
        # previous values through so a reingest does not silently switch off
        # auto-update the user explicitly enabled.
        auto_update_enabled=repo.auto_update_enabled,
        auto_update_interval_hours=repo.auto_update_interval_hours,
        next_sync_at=repo.next_sync_at,
    )

    db.add(new_repo)
    await db.commit()

    ingest_repository.delay(
        str(repo_id),
        current_user.github_access_token,
        branch=branch,
        commit_sha=commit_sha,
    )
    logger.info(
        "Re-ingestion queued for repo %s (branch=%s, commit_sha=%s)", repo_id, branch, commit_sha
    )

    return {"repo_id": str(repo_id), "repo_num": repo.repo_number}


@router.patch("/{repo_id}/auto-update", response_model=RepositoryResponse)
async def update_auto_update(
    repo_id: uuid.UUID,
    payload: AutoUpdatePatch,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    """Toggle auto-update for a repository and change its sync cadence.

    Enabling auto-update sets ``next_sync_at`` to ``now()`` so the first sync
    lands within one sweep rather than the user waiting an entire interval to
    find out whether it works. Disabling NULLs ``next_sync_at`` -- the sweep
    predicate filters on ``next_sync_at <= now()``, so a NULL row is never
    claimed.

    Args:
        repo_id: ID of the repository to update.
        payload: Optional ``enabled`` and ``interval_hours``. Either may be
            omitted to leave the current value alone.
        request: Request carrying the authenticated user ID in state.
        db: Async database session.

    Returns:
        The updated repository.

    Raises:
        HTTPException: 404 if not found, 422 if the interval is not one of
            the allowed cadences.
    """
    user_id = getattr(request.state, "user_id", None)
    repo = await get_repo_for_user(repo_id, user_id, db)

    owner = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if owner is not None:
        _require_user_key(owner)

    if (
        payload.interval_hours is not None
        and payload.interval_hours not in ALLOWED_AUTO_UPDATE_INTERVALS
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"interval_hours must be one of {list(ALLOWED_AUTO_UPDATE_INTERVALS)}; "
                f"got {payload.interval_hours}"
            ),
        )

    if payload.enabled is not None:
        repo.auto_update_enabled = payload.enabled
        if payload.enabled:
            # Schedule the first sync immediately. The sweep will see this repo
            # on its next tick (within ``SWEEP_INTERVAL_MINUTES``) and claim it.
            repo.next_sync_at = datetime.now(UTC)
        else:
            # NULL puts the row outside the sweep's claim predicate. Any in-flight
            # sync is left to finish -- ``sync_lease_expires_at`` is what stops
            # it being reclaimed.
            repo.next_sync_at = None
            repo.consecutive_sync_failures = 0
            repo.last_sync_error = None

    if payload.interval_hours is not None:
        repo.auto_update_interval_hours = payload.interval_hours

    await db.commit()
    await db.refresh(repo)
    return repo


@router.post("/{repo_id}/sync", status_code=202)
async def sync_repository(
    repo_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    """Force a sync to run for a repository right now.

    Sets ``sync_status='queued'`` and ``next_sync_at=now()`` so the sweep picks
    the repo up on its next tick. Refuses (409) while a sync is already in
    flight, signalled by an unexpired ``sync_lease_expires_at``.

    Args:
        repo_id: ID of the repository to sync.
        request: Request carrying the authenticated user ID in state.
        db: Async database session.

    Returns:
        Dict with ``sync_status`` and ``next_sync_at``.

    Raises:
        HTTPException: 404 if not found, 409 if a sync lease is active.
    """
    user_id = getattr(request.state, "user_id", None)
    repo = await get_repo_for_user(repo_id, user_id, db)

    owner = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if owner is not None:
        _require_user_key(owner)

    if not AUTO_UPDATE_ENABLED:
        raise HTTPException(
            status_code=409,
            detail="Auto-update is disabled by the deployment.",
        )

    now = datetime.now(UTC)
    if repo.sync_lease_expires_at is not None and repo.sync_lease_expires_at > now:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A sync is already in flight (lease expires at "
                f"{repo.sync_lease_expires_at.isoformat()})."
            ),
        )

    # A sync diffs the repository against ``ingested_commit_sha``. Repositories
    # ingested before that watermark existed have none, and the worker's own
    # guard skips them -- so without this the request would queue a job that can
    # never run, leaving the panel reporting a sync in flight forever.
    if not repo.ingested_commit_sha:
        raise HTTPException(
            status_code=409,
            detail=(
                "This repository has no recorded baseline commit, so there is "
                "nothing to diff an update against. Re-ingest it to enable syncing."
            ),
        )

    repo.sync_status = "queued"
    # Pushed forward so a sweep ticking in the meantime cannot claim and
    # dispatch a second copy of the same work; ``_record_success`` overwrites it.
    repo.next_sync_at = now + timedelta(hours=repo.auto_update_interval_hours or 6)
    await db.commit()

    # Dispatched here rather than left for the sweep. The sweep only claims
    # repositories whose ``auto_update_enabled`` is set, so a manual sync
    # requested with the toggle off was marked queued and never picked up --
    # which the panel then showed as a sync that never finished.
    try:
        sync_repository_task.delay(str(repo_id))
    except Exception:
        # ``queued`` is already committed. Without putting it back, a broker
        # that refused the task would leave the row mid-flight forever and the
        # settings panel polling it forever.
        repo.sync_status = "idle"
        repo.next_sync_at = None
        await db.commit()
        logger.exception("Failed to queue manual sync for repo %s", repo_id)
        # ``from None``: the broker error is already logged, and chaining it
        # into the response would only add noise to an expected failure mode.
        raise HTTPException(
            status_code=503,
            detail="Could not queue the sync. Please try again.",
        ) from None

    logger.info("Manual sync requested for repo %s", repo_id)

    return {
        "repo_id": str(repo_id),
        "sync_status": repo.sync_status,
        "next_sync_at": repo.next_sync_at,
    }


@router.get("/{repo_num}", response_model=RepositoryResponse)
async def get_repository(
    repo_num: int,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    """Fetch one repository by its user-scoped repo number.

    Args:
        repo_num: Human-friendly per-user repository number.
        request: Request carrying the authenticated user ID in state.
        db: Async database session.

    Returns:
        The matching repository.

    Raises:
        HTTPException: 404 if not found or owned by another user.
    """
    user_id = getattr(request.state, "user_id", None)
    repo = (
        await db.execute(
            select(Repository).filter(
                Repository.repo_number == repo_num, Repository.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    data = RepositoryResponse.model_validate(repo)
    data.sync_available = await _user_has_ai_key(db, user_id)
    return data


@router.get("", response_model=list[RepositoryResponse])
async def list_repositories(request: Request, db: AsyncSession = Depends(get_async_db)):
    """List the caller's repositories newest-first with truncated summaries.

    Args:
        request: Request carrying the authenticated user ID in state.
        db: Async database session.

    Returns:
        List of the user's repositories; long architecture summaries are
        truncated to 200 characters for the list view.
    """
    user_id = getattr(request.state, "user_id", None)

    repositories = (
        (
            await db.execute(
                select(Repository)
                .filter(Repository.user_id == user_id)
                .order_by(Repository.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    sync_available = await _user_has_ai_key(db, user_id) if user_id else False

    results = []

    for repo in repositories:
        data = RepositoryResponse.model_validate(repo)
        data.sync_available = sync_available
        if data.architecture_summary and len(data.architecture_summary) > 200:
            data.architecture_summary = data.architecture_summary[:200] + "..."
        results.append(data)

    return results


@router.delete("/{repo_id}", status_code=204)
async def delete_repository(
    repo_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    """Delete a repository owned by the caller.

    Args:
        repo_id: ID of the repository to delete.
        request: Request carrying the authenticated user ID in state.
        db: Async database session.

    Returns:
        None (204 No Content).

    Raises:
        HTTPException: 401 if unauthenticated, 404 if not found.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    result = await db.execute(
        select(Repository).where(
            Repository.id == repo_id,
            Repository.user_id == user_id,
        )
    )
    repo = result.scalar_one_or_none()

    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    await db.delete(repo)
    await db.commit()

    return None


@router.get("/{repo_id}/export/illume", response_class=PlainTextResponse)
async def export_repository_illume(
    repo_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """Export a ready repository as a downloadable ``.illume`` bundle.

    Args:
        repo_id: ID of the repository to export.
        request: Incoming request (unused beyond auth).
        db: Async database session.
        current_user: Owner of the repository.

    Returns:
        Plain-text bundle with a download filename header.

    Raises:
        HTTPException: 404 if not found, 400 if ingestion is incomplete.
    """
    result = await db.execute(
        select(Repository).where(
            Repository.id == repo_id,
            Repository.user_id == current_user.id,
        )
    )
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    if repo.status != "ready":
        raise HTTPException(
            status_code=400,
            detail=f"Repository is not ready (current status: {repo.status})",
        )

    content = await generate_illume_file(db, repo_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Repository details not found")

    headers = {"Content-Disposition": f'attachment; filename="{repo.name}.illume"'}
    return PlainTextResponse(content, headers=headers)
