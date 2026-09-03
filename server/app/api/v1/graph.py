"""Dependency graph route for file- and symbol-level visualization.

Delegates to the graph builder service and only serves repositories that
have finished ingestion.
"""

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
    """Build the dependency graph JSON for a ready repository.

    Args:
        repo_id: ID of the repository to visualize.
        request: Request carrying the authenticated user ID in state.
        level: Graph granularity, either file-level or symbol-level.
        db: Async database session.

    Returns:
        Graph payload with nodes and edges at the requested level.

    Raises:
        HTTPException: 404 if not found, 409 if ingestion is incomplete,
            500 if the graph build fails.
    """
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
        # Log the traceback server-side but return a generic error to the client.
        logger.exception("Graph build failed for repo %s", repo_id)
        raise HTTPException(status_code=500, detail="Failed to build graph")

    return graph
