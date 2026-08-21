import logging
import uuid

from app.api.deps import get_repo_for_user
from app.core.database import get_async_db
from app.models import AstSymbol, CodeOwner, Dependency, File
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/repository", tags=["stats"])


class LanguageBreakdownItem(BaseModel):
    language: str
    file_count: int
    loc_count: int


class TopContributorItem(BaseModel):
    name: str
    files_owned: int


class StatsResponse(BaseModel):
    repository_id: uuid.UUID
    total_files: int
    total_loc: int
    language_breakdown: list[LanguageBreakdownItem]
    total_contributors: int
    top_contributors: list[TopContributorItem]
    knowledge_silo_count: int
    total_dependencies: int


@router.get("/{repo_id}/stats", response_model=StatsResponse)
async def get_repository_stats(
    request: Request,
    repo_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
) -> StatsResponse:

    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    await get_repo_for_user(repo_id, user_id, db)

    file_stats_query = await db.execute(
        select(
            func.count(File.id).label("total_files"),
            func.sum(File.loc).label("total_loc"),
        ).where(File.repository_id == repo_id)
    )
    f_stats = file_stats_query.one()
    total_files = f_stats.total_files or 0
    total_loc = int(f_stats.total_loc or 0)

    lang_stats_query = await db.execute(
        select(
            File.language,
            func.count(File.id).label("file_count"),
            func.sum(File.loc).label("loc_count"),
        )
        .where(File.repository_id == repo_id)
        .group_by(File.language)
    )
    language_breakdown = [
        LanguageBreakdownItem(
            language=row.language or "Unknown",
            file_count=row.file_count,
            loc_count=int(row.loc_count or 0),
        )
        for row in lang_stats_query.all()
    ]

    silo_stats_query = await db.execute(
        select(func.count(CodeOwner.id))
        .join(File, File.id == CodeOwner.file_id)
        .where(File.repository_id == repo_id, CodeOwner.is_knowledge_silo == True)  # noqa: E712
    )
    knowledge_silo_count = silo_stats_query.scalar_one() or 0

    owner_stats_query = await db.execute(
        select(func.count(distinct(CodeOwner.primary_owner)))
        .join(File, File.id == CodeOwner.file_id)
        .where(File.repository_id == repo_id)
    )
    total_contributors = owner_stats_query.scalar_one() or 0

    top_owner_stats_query = await db.execute(
        select(CodeOwner.primary_owner, func.count(CodeOwner.id).label("files_owned"))
        .join(File, File.id == CodeOwner.file_id)
        .where(File.repository_id == repo_id)
        .group_by(CodeOwner.primary_owner)
        .order_by(func.count(CodeOwner.id).desc())
        .limit(5)
    )
    top_contributors = [
        TopContributorItem(
            name=row.primary_owner or "Unknown", files_owned=row.files_owned
        )
        for row in top_owner_stats_query.all()
    ]

    dep_stats_query = await db.execute(
        select(func.count(Dependency.id))
        .join(AstSymbol, Dependency.source_symbol_id == AstSymbol.id)
        .join(File, AstSymbol.file_id == File.id)
        .where(File.repository_id == repo_id)
    )
    total_dependencies = dep_stats_query.scalar_one() or 0

    return StatsResponse(
        repository_id=repo_id,
        total_files=total_files,
        total_loc=total_loc,
        language_breakdown=language_breakdown,
        total_contributors=total_contributors,
        top_contributors=top_contributors,
        knowledge_silo_count=knowledge_silo_count,
        total_dependencies=total_dependencies,
    )
