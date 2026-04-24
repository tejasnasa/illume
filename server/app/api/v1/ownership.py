import logging
import uuid

from app.api.deps import get_repo_for_user
from app.core.database import get_async_db
from app.models.code_owner import CodeOwner
from app.models.file import File
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/repository", tags=["ownership"])


class Contributor(BaseModel):
    name: str
    email: str | None
    percentage: float | None
    last_commit: str | None


class FileOwnershipResponse(BaseModel):
    file_id: uuid.UUID
    file_path: str
    primary_owner: str | None
    contributors: list[Contributor]
    bus_factor: int
    is_knowledge_silo: bool

    model_config = ConfigDict(from_attributes=True)


class OwnershipMapResponse(BaseModel):
    files: list[FileOwnershipResponse]
    total: int


class SilosResponse(BaseModel):
    silos: list[FileOwnershipResponse]
    total: int


def _build_file_ownership(owner: CodeOwner, file: File) -> FileOwnershipResponse:
    raw_contributors: list[dict] = owner.contributors or []
    contributors = [
        Contributor(
            name=c.get("name", ""),
            email=c.get("email"),
            percentage=c.get("percentage"),
            last_commit=c.get("last_commit"),
        )
        for c in raw_contributors
    ]
    return FileOwnershipResponse(
        file_id=file.id,
        file_path=file.path,
        primary_owner=owner.primary_owner,
        contributors=contributors,
        bus_factor=owner.bus_factor,
        is_knowledge_silo=owner.is_knowledge_silo,
    )


@router.get("/{repo_id}/ownership", response_model=OwnershipMapResponse)
async def get_ownership_map(
    request: Request,
    repo_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    file_path: str | None = Query(None),
    db: AsyncSession = Depends(get_async_db),
) -> OwnershipMapResponse:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    await get_repo_for_user(repo_id, user_id, db)

    stmt = (
        select(CodeOwner, File)
        .join(File, File.id == CodeOwner.file_id)
        .where(File.repository_id == repo_id)
    )
    if file_path:
        stmt = stmt.where(File.path == file_path)
    
    stmt = stmt.order_by(File.path).offset((page - 1) * page_size).limit(page_size)
    
    result = await db.execute(stmt)
    rows = result.all()

    count_stmt = (
        select(CodeOwner)
        .join(File, File.id == CodeOwner.file_id)
        .where(File.repository_id == repo_id)
    )
    if file_path:
        count_stmt = count_stmt.where(File.path == file_path)
    
    count_result = await db.execute(count_stmt)
    total = len(count_result.scalars().all())

    files = [_build_file_ownership(owner, file) for owner, file in rows]

    return OwnershipMapResponse(files=files, total=total)


@router.get("/{repo_id}/ownership/silos", response_model=SilosResponse)
async def get_knowledge_silos(
    request: Request,
    repo_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
) -> SilosResponse:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    await get_repo_for_user(repo_id, user_id, db)

    stmt = (
        select(CodeOwner, File)
        .join(File, File.id == CodeOwner.file_id)
        .where(
            File.repository_id == repo_id,
            CodeOwner.is_knowledge_silo == True,  # noqa: E712
        )
        .order_by(File.path)
    )
    result = await db.execute(stmt)
    rows = result.all()

    silos = [_build_file_ownership(owner, file) for owner, file in rows]

    return SilosResponse(silos=silos, total=len(silos))
