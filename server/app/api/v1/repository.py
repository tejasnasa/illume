import logging
import uuid
from datetime import datetime

from app.core.database import AsyncSession, get_async_db
from app.models.repository import Repository
from app.tasks.ingest import ingest_repository
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/repository", tags=["repository"])


class RepositoryCreate(BaseModel):
    github_url: str


class RepositoryResponse(BaseModel):
    id: uuid.UUID
    github_url: str
    name: str
    status: str
    architecture_summary: str | None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


def _extract_repo_name(github_url: str) -> str:
    return github_url.rstrip("/").split("/")[-1]


@router.post("", status_code=202)
async def create_repository(
    payload: RepositoryCreate,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    repo = Repository(
        github_url=payload.github_url,
        name=_extract_repo_name(payload.github_url),
        user_id=user_id,
    )
    db.add(repo)
    await db.commit()
    await db.refresh(repo)

    ingest_repository.delay(str(repo.id))
    logger.info("Queued ingestion for repo %s", repo.id)

    return {"repo_id": str(repo.id)}


@router.get("/{repo_id}", response_model=RepositoryResponse)
async def get_repository(
    repo_id: uuid.UUID,
    request: Request,
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
    return repo


@router.get("", response_model=list[RepositoryResponse])
async def list_repositories(request: Request, db: AsyncSession = Depends(get_async_db)):
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

    results = []

    for repo in repositories:
        data = RepositoryResponse.model_validate(repo)
        if data.architecture_summary and len(data.architecture_summary) > 200:
            data.architecture_summary = data.architecture_summary[:200] + "..."
        results.append(data)

    return results
