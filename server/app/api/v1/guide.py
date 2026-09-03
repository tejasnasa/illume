"""Onboarding guide route serving reading order and architecture brief.

Parses the stored OnboardingGuide JSON blobs (reading order, critical
files, architecture brief) into typed response models for the frontend.
"""

import logging
import uuid
from pathlib import Path

from app.api.deps import get_repo_for_user
from app.core.database import get_async_db
from app.models import OnboardingGuide
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/repository", tags=["guide"])


class ReadingOrderItem(BaseModel):
    """One file in suggested reading order with its annotation."""

    position: int
    file_path: str
    annotation: str
    fan_in: int


class CriticalFile(BaseModel):
    """File flagged by criticality scoring with reasons."""

    file_path: str
    criticality: str
    reasons: list[str]
    fan_in: int
    change_frequency: float | None
    has_tests: bool


class DataFlowStep(BaseModel):
    """Single directed edge in the architecture data-flow trace."""

    from_: str = Field(alias="from")
    to: str
    step: int | None = None


class ArchitectureBrief(BaseModel):
    """Narrative architecture summary sections produced by the LLM."""

    entry_points: list[str] | None = None
    directory_summary: dict | None = None
    external_integrations: list[str] | None = None
    data_flow: list[DataFlowStep] | None = None
    module_edges: list[dict] | None
    key_modules: list[dict] | None
    ownership_summary: list[dict] | None


class GuideResponse(BaseModel):
    """Full onboarding guide payload for a repository."""

    repository_id: uuid.UUID
    reading_order: list[ReadingOrderItem]
    critical_files: list[CriticalFile]
    architecture_brief: ArchitectureBrief | None
    pdf_ready: bool

    model_config = ConfigDict(from_attributes=True)


async def _get_guide(repo_id: uuid.UUID, db: AsyncSession) -> OnboardingGuide:
    """Load the stored guide or raise 404 if ingestion hasn't produced one."""
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
    """Parse stored reading-order JSON into sorted response items."""
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
    """Parse stored critical-file JSON, sorted critical-first."""
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
    # Most severe files first so the riskiest changes stand out.
    order = {"critical": 0, "caution": 1, "safe": 2}
    return sorted(items, key=lambda x: order.get(x.criticality, 3))


def _parse_architecture_brief(raw: dict | None) -> ArchitectureBrief | None:
    """Parse the stored architecture-brief JSON blob, if present."""
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
    """Return the parsed onboarding guide for a repository.

    Args:
        request: Request carrying the authenticated user ID in state.
        repo_id: ID of the repository whose guide to fetch.
        db: Async database session.

    Returns:
        Reading order, critical files, architecture brief, and PDF readiness.

    Raises:
        HTTPException: 401 if unauthenticated, 404 if repo or guide missing.
    """
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



