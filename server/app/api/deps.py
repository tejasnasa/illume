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
    user: User,
    db: AsyncSession,
) -> Repository:
    result = await db.execute(
        select(Repository).where(
            Repository.id == repo_id,
            Repository.user_id == user.id,
        )
    )
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo
