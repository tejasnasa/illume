"""Small reads shared by several tools."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import File
from app.services.agent.tools.context import NodeEvent
from app.services.retrieval.citations import normalize_path


@dataclass(frozen=True)
class FileRef:
    """A file of the repository, copied out of its row."""

    id: UUID
    path: str


def no_such_file(path: str) -> str:
    """The note for a path that is not in the repository."""
    return (
        f"No file at `{path}` in this repository. Check the spelling with list_files "
        "or search_symbols; paths are relative to the repository root."
    )


async def find_file(db: AsyncSession, repository_id: UUID, path: str) -> FileRef | None:
    """The file at ``path`` in one repository, or ``None``.

    The path is matched exactly after a leading ``./`` or ``/`` is dropped.
    """
    wanted = normalize_path(path)
    row = (
        await db.execute(
            select(File.id, File.path).where(
                File.repository_id == repository_id, File.path == wanted
            )
        )
    ).first()
    return FileRef(id=row.id, path=row.path) if row else None


async def paths_of(
    db: AsyncSession, repository_id: UUID, file_ids: Collection[UUID]
) -> dict[UUID, str]:
    """Paths for file ids, restricted to the repository."""
    if not file_ids:
        return {}
    rows = await db.execute(
        select(File.id, File.path).where(
            File.repository_id == repository_id, File.id.in_(list(file_ids))
        )
    )
    return {row.id: row.path for row in rows}


def touched(*paths: str | None, action: str = "touched") -> NodeEvent | None:
    """A node event for the given paths, or ``None`` when there are none."""
    unique = tuple(dict.fromkeys(path for path in paths if path))
    return NodeEvent(paths=unique, action=action) if unique else None
