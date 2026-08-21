import logging
import uuid
from datetime import datetime

from app.api.deps import get_current_user
from app.core.database import AsyncSession, get_async_db
from app.models import Repository, User
from app.services.illume_exporter import generate_illume_file
from app.tasks.ingest import ingest_repository
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/repository", tags=["repository"])


class RepositoryCreate(BaseModel):
    github_url: str
    branch: str | None = None
    commit_sha: str | None = None


class RepositoryReingest(BaseModel):
    branch: str | None = None
    commit_sha: str | None = None


class RepositoryResponse(BaseModel):
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
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


def _extract_repo_name(github_url: str) -> str:
    return github_url.rstrip("/").split("/")[-1]


@router.post("", status_code=202)
async def create_repository(
    payload: RepositoryCreate,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    repo = Repository(
        github_url=payload.github_url,
        name=_extract_repo_name(payload.github_url),
        user_id=current_user.id,
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
    logger.info("Queued ingestion for repo %s (branch=%s, commit_sha=%s)", repo.id, payload.branch, payload.commit_sha)

    return {"repo_id": str(repo.id), "repo_num": repo.repo_number}


@router.put("/{repo_id}/reingest", status_code=202)
async def reingest_repository(
    repo_id: uuid.UUID,
    payload: RepositoryReingest | None = None,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
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
    )

    db.add(new_repo)
    await db.commit()

    ingest_repository.delay(
        str(repo_id),
        current_user.github_access_token,
        branch=branch,
        commit_sha=commit_sha,
    )
    logger.info("Re-ingestion queued for repo %s (branch=%s, commit_sha=%s)", repo_id, branch, commit_sha)

    return {"repo_id": str(repo_id), "repo_num": repo.repo_number}


@router.get("/{repo_num}", response_model=RepositoryResponse)
async def get_repository(
    repo_num: int,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
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


@router.delete("/{repo_id}", status_code=204)
async def delete_repository(
    repo_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
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

    headers = {
        "Content-Disposition": f'attachment; filename="{repo.name}.illume"'
    }
    return PlainTextResponse(content, headers=headers)

