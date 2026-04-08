import logging
import uuid

from app.core.database import get_sync_db
from app.models.repository import Repository
from app.tasks.ingest import ingest_repository
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/repositories", tags=["repositories"])


class RepositoryCreate(BaseModel):
    github_url: str


class RepositoryResponse(BaseModel):
    github_url: str
    name: str
    status: str

    class Config:
        from_attributes = True


def _extract_repo_name(github_url: str) -> str:
    return github_url.rstrip("/").split("/")[-1]


@router.post("", status_code=202)
def create_repository(
    payload: RepositoryCreate,
    db: Session = Depends(get_sync_db),
):
    repo = Repository(
        github_url=payload.github_url,
        name=_extract_repo_name(payload.github_url),
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    ingest_repository.delay(str(repo.id))
    logger.info("Queued ingestion for repo %s", repo.id)

    return {"repo_id": str(repo.id)}


@router.get("/{repo_id}", response_model=RepositoryResponse)
def get_repository(
    repo_id: uuid.UUID,
    db: Session = Depends(get_sync_db),
):
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


@router.get("", response_model=list[RepositoryResponse])
def list_repositories(db: Session = Depends(get_sync_db)):
    return db.query(Repository).order_by(Repository.created_at.desc()).all()
