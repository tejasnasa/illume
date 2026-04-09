import logging
import uuid
from typing import Literal

from app.core.database import get_sync_db
from app.models.repository import Repository
from app.services.graph_builder import build_graph
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/repository", tags=["graph"])


@router.get("/{repo_id}/graph")
def get_graph(
    repo_id: uuid.UUID,
    level: Literal["file", "symbol"] = Query("file", enum=["file", "symbol"]),
    db: Session = Depends(get_sync_db),
):
    repo = db.query(Repository).filter_by(id=repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    if repo.status != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"Repository is not ready yet (status: {repo.status})",
        )

    try:
        graph = build_graph(db, repo_id, level=level)
    except Exception:
        logger.exception("Graph build failed for repo %s", repo_id)
        raise HTTPException(status_code=500, detail="Failed to build graph")

    return graph
