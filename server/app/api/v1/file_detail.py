"""File detail route: one file's symbols and the commits that last touched it.

The explorer's inspector lists what a file defines and where it has been
changing, so a newcomer can jump from a node to its code and its history.
Both come from rows ingestion already stored; nothing here calls GitHub.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_repo_for_user
from app.core.database import get_async_db
from app.models import AstSymbol, Commit, File

router = APIRouter(prefix="/api/v1/repository", tags=["file-detail"])

# The symbol kinds worth jumping to. Imports and variables would crowd them out.
_LISTED_KINDS = ("function", "class", "method")


class FileSymbol(BaseModel):
    """One definition in the file.

    Attributes:
        kind: ``function``, ``class`` or ``method``.
        name: The symbol's name.
        start_line: The line it starts on, when the parser recorded one.
    """

    kind: str
    name: str
    start_line: int | None = None


class FileCommit(BaseModel):
    """One commit that changed the file.

    Attributes:
        hash: The full commit hash.
        title: The first line of the commit message.
        author: Who wrote it.
        at: When it was authored.
    """

    hash: str
    title: str
    author: str
    at: datetime


class FileDetailResponse(BaseModel):
    """What a file defines, in line order, and its latest commits, newest first."""

    symbols: list[FileSymbol]
    commits: list[FileCommit]


@router.get("/{repo_id}/file", response_model=FileDetailResponse)
async def get_file_detail(
    request: Request,
    repo_id: uuid.UUID,
    path: str = Query(min_length=1, max_length=1024),
    commits: int = Query(default=3, ge=0, le=20),
    db: AsyncSession = Depends(get_async_db),
) -> FileDetailResponse:
    """Return a file's symbols and the most recent commits that touched it.

    Args:
        request: Request carrying the authenticated user ID in state.
        repo_id: ID of the repository.
        path: Repository-relative path of the file.
        commits: The most commits to return.
        db: Async database session.

    Returns:
        The file's functions, classes and methods sorted by line, and up to
        ``commits`` commits whose changed files include ``path``.

    Raises:
        HTTPException: 401 if unauthenticated, 404 if the repo or the file is
            not found.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    await get_repo_for_user(repo_id, user_id, db)

    file_id = (
        await db.execute(select(File.id).where(File.repository_id == repo_id, File.path == path))
    ).scalar_one_or_none()
    if file_id is None:
        raise HTTPException(status_code=404, detail="File not found")

    symbol_rows = (
        await db.execute(
            select(AstSymbol.kind, AstSymbol.name, AstSymbol.start_line)
            .where(AstSymbol.file_id == file_id, AstSymbol.kind.in_(_LISTED_KINDS))
            .order_by(AstSymbol.start_line.asc().nulls_last(), AstSymbol.name)
        )
    ).all()

    commit_rows = []
    if commits:
        # `changed_files_list` is a JSON array of paths, so containment of a
        # one-element array matches commits that touched this exact path.
        commit_rows = (
            (
                await db.execute(
                    select(Commit)
                    .where(
                        Commit.repository_id == repo_id,
                        Commit.changed_files_list.contains([path]),
                    )
                    .order_by(Commit.authored_at.desc())
                    .limit(commits)
                )
            )
            .scalars()
            .all()
        )

    return FileDetailResponse(
        symbols=[
            FileSymbol(kind=row.kind, name=row.name, start_line=row.start_line)
            for row in symbol_rows
        ],
        commits=[
            FileCommit(
                hash=commit.hash,
                title=(commit.message or "").strip().splitlines()[0]
                if (commit.message or "").strip()
                else "",
                author=commit.author_name,
                at=commit.authored_at,
            )
            for commit in commit_rows
        ],
    )
