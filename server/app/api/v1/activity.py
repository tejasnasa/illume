"""Recent activity route: the latest merged pull requests and commits.

The repository overview shows what has been changing lately, so a newcomer
sees where work is happening before reading any code. Both sources are the
rows ingestion already stored; nothing here calls GitHub.
"""

import re
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_repo_for_user
from app.core.database import get_async_db
from app.models import Commit, PullRequest

router = APIRouter(prefix="/api/v1/repository", tags=["activity"])

# Merge commits repeat the pull request they merged, so they are left out.
_MERGE_COMMIT = re.compile(r"^Merge (pull request|branch|remote-tracking branch)\b")


class ActivityItem(BaseModel):
    """One merged pull request or commit.

    Attributes:
        kind: ``pull_request`` or ``commit``.
        title: The pull request's title, or the first line of the commit message.
        author: Who wrote it.
        at: When it was merged or authored.
        number: The pull request number.
        hash: The full commit hash.
        files_changed: Files it touched.
    """

    kind: Literal["pull_request", "commit"]
    title: str
    author: str
    at: datetime
    number: int | None = None
    hash: str | None = None
    files_changed: int = 0


class ActivityResponse(BaseModel):
    """The most recent activity, newest first."""

    items: list[ActivityItem]


@router.get("/{repo_id}/activity", response_model=ActivityResponse)
async def get_recent_activity(
    request: Request,
    repo_id: uuid.UUID,
    limit: int = Query(default=6, ge=1, le=30),
    db: AsyncSession = Depends(get_async_db),
) -> ActivityResponse:
    """Return the latest merged pull requests and commits, newest first.

    Args:
        request: Request carrying the authenticated user ID in state.
        repo_id: ID of the repository.
        limit: The most items to return.
        db: Async database session.

    Returns:
        Up to ``limit`` items. Merge commits are left out, since the pull
        request they merged is listed itself.

    Raises:
        HTTPException: 401 if unauthenticated, 404 if the repo is not found.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    await get_repo_for_user(repo_id, user_id, db)

    pulls = (
        await db.execute(
            select(PullRequest)
            .where(PullRequest.repository_id == repo_id, PullRequest.merged_at.is_not(None))
            .order_by(PullRequest.merged_at.desc())
            .limit(limit)
        )
    ).scalars()
    # Read a few extra commits, since merge commits are filtered out after.
    commits = (
        await db.execute(
            select(Commit)
            .where(Commit.repository_id == repo_id)
            .order_by(Commit.authored_at.desc())
            .limit(limit * 3)
        )
    ).scalars()

    items = [
        ActivityItem(
            kind="pull_request",
            title=pull.title,
            author=pull.author,
            at=pull.merged_at,
            number=pull.number,
            files_changed=pull.files_changed or 0,
        )
        for pull in pulls
        if pull.merged_at is not None
    ]
    for commit in commits:
        title = (commit.message or "").strip().splitlines()[0] if commit.message else ""
        if not title or _MERGE_COMMIT.match(title):
            continue
        items.append(
            ActivityItem(
                kind="commit",
                title=title,
                author=commit.author_name,
                at=commit.authored_at,
                hash=commit.hash,
                files_changed=commit.files_changed or 0,
            )
        )

    items.sort(key=lambda item: item.at, reverse=True)
    return ActivityResponse(items=items[:limit])
