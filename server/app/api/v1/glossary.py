import logging
import uuid

from app.api.deps import get_current_user, get_repo_for_user
from app.core.database import get_async_db
from app.models import GlossaryEntry, User
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/repository", tags=["glossary"])


class GlossaryEntryResponse(BaseModel):
    id: uuid.UUID
    name: str
    definition: str
    file_path: str | None
    line_number: int | None
    symbol_id: uuid.UUID | None

    model_config = ConfigDict(from_attributes=True)


class GlossaryListResponse(BaseModel):
    entries: list[GlossaryEntryResponse]
    total: int
    page: int
    page_size: int


@router.get("/{repo_id}/glossary", response_model=GlossaryListResponse)
async def browse_glossary(
    repo_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    file_path: str | None = Query(
        None, description="Filter entries by file path (exact match)"
    ),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> GlossaryListResponse:
    await get_repo_for_user(repo_id, current_user, db)

    base_query = select(GlossaryEntry).where(GlossaryEntry.repository_id == repo_id)

    if file_path is not None:
        base_query = base_query.where(GlossaryEntry.file_path == file_path)

    count_result = await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total: int = count_result.scalar_one()

    rows_result = await db.execute(
        base_query.order_by(GlossaryEntry.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    entries = rows_result.scalars().all()

    return GlossaryListResponse(
        entries=[GlossaryEntryResponse.model_validate(e) for e in entries],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{repo_id}/glossary/search", response_model=GlossaryListResponse)
async def search_glossary(
    repo_id: uuid.UUID,
    q: str = Query(
        ...,
        min_length=1,
        description="Search term (matched against name and definition)",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> GlossaryListResponse:
    await get_repo_for_user(repo_id, current_user, db)

    pattern = f"%{q}%"

    base_query = select(GlossaryEntry).where(
        GlossaryEntry.repository_id == repo_id,
        or_(
            GlossaryEntry.name.ilike(pattern),
            GlossaryEntry.definition.ilike(pattern),
        ),
    )

    count_result = await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total: int = count_result.scalar_one()

    rows_result = await db.execute(
        base_query.order_by(GlossaryEntry.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    entries = rows_result.scalars().all()

    return GlossaryListResponse(
        entries=[GlossaryEntryResponse.model_validate(e) for e in entries],
        total=total,
        page=page,
        page_size=page_size,
    )
