"""Turning the ``repo`` argument of a tool call into one of the caller's repositories."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import Repository

_GITHUB_REF = re.compile(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
_MAX_CANDIDATES_LISTED = 10
_MAX_NUMBER_DIGITS = 9


class McpRepoError(Exception):
    """A repository reference that cannot be used, worded for the model that sent it.

    Attributes:
        message: What went wrong and what to do next.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def repo_argument(value: object) -> str | None:
    """The ``repo`` argument of a tool call as a reference string, or ``None`` if unusable.

    The schema asks for a string, but a client that sees a repository number often
    sends it as a JSON number; that is accepted as the same reference. A boolean is
    not a number here.

    Args:
        value: The raw ``repo`` argument.

    Returns:
        The stripped reference, or ``None`` when it is missing, empty or of another type.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _not_found(ref: str) -> McpRepoError:
    # One message for "no such repository" and "someone else's repository", so a
    # reference cannot be used to probe what other users have ingested.
    return McpRepoError(
        f"No repository matches {ref!r}. Call list_repositories to see the available "
        "repositories and pass its `repo` value."
    )


def _like_literal(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def resolve_repo(db: AsyncSession, user_id: uuid.UUID, ref: str) -> Repository:
    """Find the caller's repository for a ``repo`` argument and check it is usable.

    Accepts a ``repo_number`` (``"42"``), a repository UUID, or ``owner/name``
    matched case-insensitively against the GitHub URL, with or without ``.git``
    or a trailing slash. Every query filters on ``user_id``.

    Args:
        db: Async database session.
        user_id: The authenticated user.
        ref: The reference the client passed.

    Returns:
        The matching repository, which is ``ready``.

    Raises:
        McpRepoError: If nothing matches, several repositories match ``owner/name``,
            or the repository is still ingesting or its ingestion failed.
    """
    ref = (ref or "").strip()
    if not ref:
        raise _not_found(ref)

    repo: Repository | None = None
    if ref.isascii() and ref.isdigit() and len(ref) <= _MAX_NUMBER_DIGITS:
        repo = await db.scalar(
            select(Repository).where(
                Repository.user_id == user_id, Repository.repo_number == int(ref)
            )
        )
    else:
        try:
            repo_id = uuid.UUID(ref)
        except ValueError:
            repo_id = None
        if repo_id is not None:
            repo = await db.scalar(
                select(Repository).where(Repository.user_id == user_id, Repository.id == repo_id)
            )
        else:
            repo = await _by_owner_and_name(db, user_id, ref)

    if repo is None:
        raise _not_found(ref)
    if repo.status == "failed":
        raise McpRepoError(
            f"Repository {repo.name!r} (repo {repo.repo_number}) failed to ingest, so it "
            "has no data to read. It needs to be re-ingested in Illume."
        )
    if repo.status != "ready":
        raise McpRepoError(
            f"Repository {repo.name!r} (repo {repo.repo_number}) is still ingesting "
            f"(status={repo.status}). Try again in a few minutes."
        )
    return repo


async def _by_owner_and_name(db: AsyncSession, user_id: uuid.UUID, ref: str) -> Repository | None:
    match = _GITHUB_REF.match(ref)
    if match is None:
        return None
    owner, name = match.group(1).lower(), match.group(2).lower()
    # Drop any trailing slash and `.git` from the stored URL before comparing.
    normalized = func.lower(func.regexp_replace(Repository.github_url, r"(\.git)?/*$", ""))
    rows = (
        await db.scalars(
            select(Repository)
            .where(
                Repository.user_id == user_id,
                normalized.like(
                    f"%github.com/{_like_literal(owner)}/{_like_literal(name)}", escape="\\"
                ),
            )
            .order_by(Repository.repo_number)
        )
    ).all()
    if not rows:
        return None
    if len(rows) > 1:
        listed = ", ".join(
            f"{r.repo_number} ({r.status}, branch {r.ingested_branch or 'unknown'})"
            for r in rows[:_MAX_CANDIDATES_LISTED]
        )
        raise McpRepoError(
            f"{ref!r} matches {len(rows)} repositories: {listed}. "
            "Pass the repository number instead."
        )
    return rows[0]
