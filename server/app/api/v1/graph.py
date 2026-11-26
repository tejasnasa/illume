"""Dependency graph route for file- and symbol-level visualization.

Delegates to the graph builder service and only serves repositories that
have finished ingestion.
"""

import logging
import uuid
from typing import Literal

from app.core.database import get_async_db
from app.models.file import File
from app.models.repository import Repository
from app.services.file_graph import query_file_edges_async
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


# The files a thumbnail keeps: enough for a repository's shape to read at card
# size, few enough that a dashboard of cards stays a small download.
THUMBNAIL_MAX_FILES = 120


@router.get("/{repo_id}/graph/thumbnail")
async def get_graph_thumbnail(
    repo_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    """Return a condensed file graph for a repository card's picture.

    The busiest files are kept, ranked by fan-in plus fan-out, together with
    the import edges between them. Self-edges and repeats are collapsed, so
    each pair appears once. The shape matches the file-level graph's nodes and
    links, so the same renderer draws either.

    Args:
        repo_id: ID of the repository to picture.
        request: Request carrying the authenticated user ID in state.
        db: Async database session.

    Returns:
        ``{"nodes": [...], "links": [...]}``; both empty while the repository
        is not ready, so a card in progress has nothing to fetch twice.

    Raises:
        HTTPException: 404 if the repository is not found.
    """
    user_id = getattr(request.state, "user_id", None)
    repo = (
        await db.execute(
            select(Repository).filter(Repository.id == repo_id, Repository.user_id == user_id)
        )
    ).scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    if repo.status != "ready":
        return {"nodes": [], "links": []}

    files = (
        await db.execute(
            select(File.id, File.path, File.loc, File.criticality, File.fan_in)
            .where(File.repository_id == repo_id)
            .order_by((File.fan_in + File.fan_out).desc(), File.path)
            .limit(THUMBNAIL_MAX_FILES)
        )
    ).all()
    kept = {row.id for row in files}

    pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for _dep_type, source, target in await query_file_edges_async(db, repo_id):
        if source != target and source in kept and target in kept:
            pairs.add((source, target))

    return {
        "nodes": [
            {
                "id": str(row.id),
                "path": row.path,
                "loc": row.loc or 0,
                "criticality": row.criticality,
                "fan_in": row.fan_in or 0,
            }
            for row in files
        ],
        "links": [{"source": str(s), "target": str(t)} for s, t in sorted(pairs)],
    }
