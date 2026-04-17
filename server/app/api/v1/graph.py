import logging
import uuid
from typing import Literal

from app.core.database import get_async_db
from app.models.repository import Repository
from app.services.graph_builder import build_graph
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/repository", tags=["graph"])


@router.get("/{repo_id}/graph")
async def get_graph(
    repo_id: uuid.UUID,
    request: Request,
    level: Literal["file", "symbol"] = Query("file", enum=["file", "symbol"]),
    db: AsyncSession = Depends(get_async_db),
):
    user_id = getattr(request.state, "user_id", None)
    repo = (
        await db.execute(
            select(Repository).filter(
                Repository.id == repo_id, Repository.user_id == user_id
            )
        )
    ).scalar_one_or_none()

    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    if repo.status != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"Repository is not ready yet (status: {repo.status})",
        )

    try:
        graph = await build_graph(db, repo_id, level=level)
    except Exception:
        logger.exception("Graph build failed for repo %s", repo_id)
        raise HTTPException(status_code=500, detail="Failed to build graph")

    return graph
