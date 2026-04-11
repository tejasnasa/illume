import logging
import uuid

from app.core.database import get_sync_db
from app.models.file import File
from app.models.health_metric import HealthMetric
from app.models.repository import Repository
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/repository", tags=["health"])


class SubScores(BaseModel):
    complexity_score: float | None
    coupling_score: float | None
    duplication_score: float | None

    class Config:
        from_attributes = True


class RepoHealthResponse(BaseModel):
    overall_score: float
    complexity_score: float | None
    coupling_score: float | None
    duplication_score: float | None
    total_loc: int
    avg_cyclomatic: float
    circular_deps: int
    breakdown: dict
    computed_at: str

    class Config:
        from_attributes = True


class FileHealthResponse(BaseModel):
    file_id: str
    file_path: str | None
    overall_score: float
    complexity_score: float | None
    coupling_score: float | None
    duplication_score: float | None
    total_loc: int
    avg_cyclomatic: float
    circular_deps: int
    is_hotspot: bool
    breakdown: dict

    class Config:
        from_attributes = True


class FileHealthListResponse(BaseModel):
    total: int
    page: int
    limit: int
    results: list[FileHealthResponse]


class HotspotResponse(BaseModel):
    file_id: str
    file_path: str | None
    overall_score: float
    hotspot_score: float
    reasons: list[str]
    total_loc: int
    breakdown: dict


@router.get("/{repo_id}/health", response_model=RepoHealthResponse)
def get_repo_health(
    repo_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_sync_db),
):
    user_id = getattr(request.state, "user_id", None)
    repo = (
        db.query(Repository)
        .filter(Repository.id == repo_id, Repository.user_id == user_id)
        .first()
    )
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    metric = (
        db.query(HealthMetric)
        .filter(
            HealthMetric.repository_id == repo_id,
            HealthMetric.file_id == None,  # noqa: E711
        )
        .first()
    )
    if not metric:
        raise HTTPException(status_code=404, detail="Health metrics not yet computed")

    return RepoHealthResponse(
        overall_score=metric.overall_score,
        complexity_score=metric.complexity_score,
        coupling_score=metric.coupling_score,
        duplication_score=metric.duplication_score,
        total_loc=metric.total_loc,
        avg_cyclomatic=metric.avg_cyclomatic,
        circular_deps=metric.circular_deps,
        breakdown=metric.breakdown or {},
        computed_at=metric.computed_at.isoformat(),
    )


@router.get("/{repo_id}/health/files", response_model=FileHealthListResponse)
def get_file_health(
    repo_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_sync_db),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    sort_by: str = Query("overall_score"),
    order: str = Query("asc"),
):
    user_id = getattr(request.state, "user_id", None)
    repo = (
        db.query(Repository)
        .filter(Repository.id == repo_id, Repository.user_id == user_id)
        .first()
    )
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    allowed_sort_columns = {
        "overall_score",
        "complexity_score",
        "coupling_score",
        "duplication_score",
        "total_loc",
        "avg_cyclomatic",
    }
    if sort_by not in allowed_sort_columns:
        raise HTTPException(
            status_code=400, detail=f"Invalid sort_by. Allowed: {allowed_sort_columns}"
        )

    sort_col = getattr(HealthMetric, sort_by)
    sort_col = sort_col.asc() if order == "asc" else sort_col.desc()

    base_query = db.query(HealthMetric).filter(
        HealthMetric.repository_id == repo_id,
        HealthMetric.file_id != None,  # noqa: E711
    )

    total = base_query.with_entities(func.count()).scalar()

    metrics = (
        base_query.order_by(sort_col).offset((page - 1) * limit).limit(limit).all()
    )

    file_ids = [m.file_id for m in metrics]
    file_map: dict[uuid.UUID, str] = {}
    if file_ids:
        files = db.query(File).filter(File.id.in_(file_ids)).all()
        file_map = {f.id: f.path for f in files}

    results = [
        FileHealthResponse(
            file_id=str(m.file_id),
            file_path=file_map.get(m.file_id),
            overall_score=m.overall_score,
            complexity_score=m.complexity_score,
            coupling_score=m.coupling_score,
            duplication_score=m.duplication_score,
            total_loc=m.total_loc or 0,
            avg_cyclomatic=m.avg_cyclomatic or 0.0,
            circular_deps=m.circular_deps or 0,
            is_hotspot=bool((m.breakdown or {}).get("is_hotspot", False)),
            breakdown=m.breakdown or {},
        )
        for m in metrics
    ]

    return FileHealthListResponse(total=total, page=page, limit=limit, results=results)


@router.get("/{repo_id}/hotspots", response_model=list[HotspotResponse])
def get_hotspots(
    repo_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_sync_db),
):
    user_id = getattr(request.state, "user_id", None)
    repo = (
        db.query(Repository)
        .filter(Repository.id == repo_id, Repository.user_id == user_id)
        .first()
    )
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    metrics = (
        db.query(HealthMetric)
        .filter(
            HealthMetric.repository_id == repo_id,
            HealthMetric.file_id != None,  # noqa: E711
            HealthMetric.breakdown["is_hotspot"].as_boolean() == True,  # noqa: E712
        )
        .all()
    )

    metrics.sort(
        key=lambda m: (m.breakdown or {}).get("hotspot_score", 0.0),
        reverse=True,
    )

    file_ids = [m.file_id for m in metrics]
    file_map: dict[uuid.UUID, str] = {}
    if file_ids:
        files = db.query(File).filter(File.id.in_(file_ids)).all()
        file_map = {f.id: f.path for f in files}

    return [
        HotspotResponse(
            file_id=str(m.file_id),
            file_path=file_map.get(m.file_id),
            overall_score=m.overall_score,
            hotspot_score=(m.breakdown or {}).get("hotspot_score", 0.0),
            reasons=(m.breakdown or {}).get("hotspot_reasons", []),
            total_loc=m.total_loc or 0,
            breakdown=m.breakdown or {},
        )
        for m in metrics
    ]
