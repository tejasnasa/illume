"""Loading and reading the stored onboarding guide, shared by the API and the MCP server."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OnboardingGuide


@dataclass(frozen=True)
class ReadingOrderEntry:
    """One file in the suggested reading order.

    Attributes:
        position: 1-based place in the order.
        file_path: Repository-relative path.
        annotation: Why the file is worth reading at that point.
        fan_in: How many files import it.
    """

    position: int
    file_path: str
    annotation: str
    fan_in: int


async def find_guide(db: AsyncSession, repo_id: uuid.UUID) -> OnboardingGuide | None:
    """Load the stored guide of a repository.

    Args:
        db: Async database session.
        repo_id: The repository whose guide to load.

    Returns:
        The guide, or ``None`` if ingestion has not produced one.
    """
    result = await db.execute(
        select(OnboardingGuide).where(OnboardingGuide.repository_id == repo_id)
    )
    return result.scalar_one_or_none()


def parse_reading_order(raw: list | None) -> list[ReadingOrderEntry]:
    """Parse the stored reading-order JSON into entries sorted by position.

    Args:
        raw: The stored list, which may be missing or hold malformed entries.

    Returns:
        The well-formed entries, in reading order.
    """
    if not raw:
        return []
    items = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        items.append(
            ReadingOrderEntry(
                position=entry.get("position", 0),
                file_path=entry.get("path", ""),
                annotation=entry.get("annotation", ""),
                fan_in=entry.get("fan_in", 0),
            )
        )
    return sorted(items, key=lambda x: x.position)


async def get_reading_order(db: AsyncSession, repo_id: uuid.UUID) -> list[ReadingOrderEntry] | None:
    """Load and parse a repository's reading order.

    Args:
        db: Async database session.
        repo_id: The repository to read.

    Returns:
        The entries, or ``None`` if the repository has no guide yet.
    """
    guide = await find_guide(db, repo_id)
    return None if guide is None else parse_reading_order(guide.reading_order)
