import logging
import uuid
from pathlib import Path

from app.api.deps import get_repo_for_user
from app.core.database import get_async_db
from app.models import AstSymbol, CodeOwner, Dependency, File, OnboardingGuide
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/repository", tags=["guide"])


class ReadingOrderItem(BaseModel):
    position: int
    file_path: str
    annotation: str
    fan_in: int


class CriticalFile(BaseModel):
    file_path: str
    criticality: str
    reasons: list[str]
    fan_in: int
    change_frequency: float | None
    has_tests: bool


class DataFlowStep(BaseModel):
    from_: str = Field(alias="from")
    to: str
    step: int | None = None


class ArchitectureBrief(BaseModel):
    entry_points: list[str] | None = None
    directory_summary: dict | None = None
    external_integrations: list[str] | None = None
    data_flow: list[DataFlowStep] | None = None
    module_edges: list[dict] | None
    key_modules: list[dict] | None
    ownership_summary: list[dict] | None


class GuideResponse(BaseModel):
    repository_id: uuid.UUID
    reading_order: list[ReadingOrderItem]
    critical_files: list[CriticalFile]
    architecture_brief: ArchitectureBrief | None
    pdf_ready: bool

    model_config = ConfigDict(from_attributes=True)


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


async def _get_guide(repo_id: uuid.UUID, db: AsyncSession) -> OnboardingGuide:
    result = await db.execute(
        select(OnboardingGuide).where(OnboardingGuide.repository_id == repo_id)
    )
    guide = result.scalar_one_or_none()
    if not guide:
        raise HTTPException(
            status_code=404,
            detail="Onboarding guide not generated yet. Check repository status.",
        )
    return guide


def _parse_reading_order(raw: list | None) -> list[ReadingOrderItem]:
    if not raw:
        return []
    items = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        items.append(
            ReadingOrderItem(
                position=entry.get("position", 0),
                file_path=entry.get("path", ""),
                annotation=entry.get("annotation", ""),
                fan_in=entry.get("fan_in", 0),
            )
        )
    return sorted(items, key=lambda x: x.position)


def _parse_critical_files(raw: list | None) -> list[CriticalFile]:
    if not raw:
        return []
    items = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        items.append(
            CriticalFile(
                file_path=entry.get("path", ""),
                criticality=entry.get("criticality", "safe"),
                reasons=entry.get("reasons", []),
                fan_in=entry.get("fan_in", 0),
                change_frequency=entry.get("change_frequency"),
                has_tests=entry.get("has_tests", False),
            )
        )
    order = {"critical": 0, "caution": 1, "safe": 2}
    return sorted(items, key=lambda x: order.get(x.criticality, 3))


def _parse_architecture_brief(raw: dict | None) -> ArchitectureBrief | None:
    if not raw:
        return None
    return ArchitectureBrief(
        entry_points=raw.get("entry_points"),
        directory_summary=raw.get("directory_summary"),
        external_integrations=raw.get("external_integrations"),
        data_flow=raw.get("data_flow"),
        module_edges=raw.get("module_edges"),
        key_modules=raw.get("key_modules"),
        ownership_summary=raw.get("ownership_summary"),
    )


@router.get("/{repo_id}/guide", response_model=GuideResponse)
async def get_onboarding_guide(
    request: Request,
    repo_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
) -> GuideResponse:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    await get_repo_for_user(repo_id, user_id, db)

    guide = await _get_guide(repo_id, db)

    return GuideResponse(
        repository_id=repo_id,
        reading_order=_parse_reading_order(guide.reading_order),
        critical_files=_parse_critical_files(guide.critical_files),
        architecture_brief=_parse_architecture_brief(guide.architecture_brief),
        pdf_ready=guide.pdf_path is not None and Path(guide.pdf_path).exists(),
    )


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
