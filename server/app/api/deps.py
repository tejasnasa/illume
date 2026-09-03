"""Shared FastAPI dependencies for authentication and ownership checks.

Provides helpers that resolve the current user from the request state
(populated by AuthMiddleware) and verify that a repository belongs to
that user before route handlers touch it.
"""

import uuid

from app.core.database import get_async_db
from app.models import User, Repository
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
) -> User:
    """Resolve the authenticated user from the request state.

    Args:
        request: Incoming request whose ``state.user_id`` was set by AuthMiddleware.
        db: Async database session.

    Returns:
        The authenticated User row.

    Raises:
        HTTPException: 401 if no user_id is present or the user no longer exists.
    """
    # AuthMiddleware decodes the cookie token into request.state; routes using
    # this dependency therefore require the middleware to have run first.
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def get_repo_for_user(
    repo_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> Repository:
    """Load a repository scoped to its owner.

    Args:
        repo_id: ID of the repository to load.
        user_id: ID of the requesting user; must own the repository.
        db: Async database session.

    Returns:
        The matching Repository row.

    Raises:
        HTTPException: 404 if the repo does not exist or belongs to another user.
    """
    result = await db.execute(
        select(Repository).where(
            Repository.id == repo_id,
            Repository.user_id == user_id,
        )
    )
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo
