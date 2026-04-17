import logging
import uuid
from pathlib import Path

from app.api.deps import get_current_user
from app.core.database import get_async_db
from app.models import OnboardingGuide, Repository, User
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
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


class ArchitectureBrief(BaseModel):
    detected_stack: dict | None = None
    entry_points: list[str] | None = None
    directory_summary: dict | None = None
    external_integrations: list[str] | None = None
    data_flow: list[str] | str | None = None
    summary: str | None = None


class GuideResponse(BaseModel):
    repository_id: uuid.UUID
    reading_order: list[ReadingOrderItem]
    critical_files: list[CriticalFile]
    architecture_brief: ArchitectureBrief | None
    pdf_ready: bool

    model_config = ConfigDict(from_attributes=True)


async def _get_repo_for_user(
    repo_id: uuid.UUID,
    user: User,
    db: AsyncSession,
) -> Repository:
    result = await db.execute(
        select(Repository).where(
            Repository.id == repo_id,
            Repository.user_id == user.id,
        )
    )
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


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
                file_path=entry.get("file_path", ""),
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
                file_path=entry.get("file_path", ""),
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
        detected_stack=raw.get("detected_stack"),
        entry_points=raw.get("entry_points"),
        directory_summary=raw.get("directory_summary"),
        external_integrations=raw.get("external_integrations"),
        data_flow=raw.get("data_flow"),
        summary=raw.get("summary"),
    )


@router.get("/{repo_id}/guide", response_model=GuideResponse)
async def get_onboarding_guide(
    repo_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> GuideResponse:
    await _get_repo_for_user(repo_id, current_user, db)
    guide = await _get_guide(repo_id, db)

    return GuideResponse(
        repository_id=repo_id,
        reading_order=_parse_reading_order(guide.reading_order),
        critical_files=_parse_critical_files(guide.critical_files),
        architecture_brief=_parse_architecture_brief(guide.architecture_brief),
        pdf_ready=guide.pdf_path is not None and Path(guide.pdf_path).exists(),
    )
