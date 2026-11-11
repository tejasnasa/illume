"""Telling when a chat answer's cited files have changed since it was given.

An answer is stored with the commit it was answered against and the files it
cited. When a background sync lands a set of changed files, every answer that
cited any of them is marked stale: :func:`mark_stale_answers` records when, which
of the cited files changed, and the new head. Nothing is rewritten or deleted;
the mark is a hint that the answer may no longer match the code.

Marking is a single ``UPDATE`` on the sync session. It is best-effort at the call
site: a failure is the caller's to log, and never reaches the sync.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Collection, Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.github_http import parse_github_url

logger = logging.getLogger(__name__)

# Paths that changed, matched against the cited paths with the JSONB ``?|``
# operator. An answer already given at the new head reflects the new code, so it
# is never marked. The new stale paths are the intersection, unioned with any that an
# earlier sync already recorded, so a second sync adds to the list.
_MARK_CHANGED = text(
    """
    UPDATE chat_messages AS m
    SET stale_at = COALESCE(m.stale_at, now()),
        stale_commit_sha = :head_sha,
        stale_paths = (
            SELECT COALESCE(jsonb_agg(DISTINCT p.path ORDER BY p.path), '[]'::jsonb)
            FROM (
                SELECT jsonb_array_elements_text(COALESCE(m.stale_paths, '[]'::jsonb)) AS path
                UNION
                SELECT c.path
                FROM jsonb_array_elements_text(m.cited_paths) AS c(path)
                WHERE c.path = ANY(CAST(:changed AS text[]))
            ) AS p
        )
    WHERE m.repository_id = :repository_id
      AND m.answered_commit_sha IS DISTINCT FROM :head_sha
      AND m.cited_paths ?| CAST(:changed AS text[])
    """
)

# The change set is unknown (a rebuild whose base commit is gone), so every
# cited file counts as changed.
_MARK_ALL = text(
    """
    UPDATE chat_messages AS m
    SET stale_at = COALESCE(m.stale_at, now()),
        stale_commit_sha = :head_sha,
        stale_paths = (
            SELECT COALESCE(jsonb_agg(DISTINCT p.path ORDER BY p.path), '[]'::jsonb)
            FROM (
                SELECT jsonb_array_elements_text(COALESCE(m.stale_paths, '[]'::jsonb)) AS path
                UNION
                SELECT jsonb_array_elements_text(m.cited_paths) AS path
            ) AS p
        )
    WHERE m.repository_id = :repository_id
      AND m.answered_commit_sha IS DISTINCT FROM :head_sha
      AND jsonb_typeof(m.cited_paths) = 'array'
      AND jsonb_array_length(m.cited_paths) > 0
    """
)


def cited_file_paths(paths: Iterable[str | None]) -> list[str]:
    """The distinct, non-empty file paths among ``paths``, in first-seen order."""
    return list(dict.fromkeys(path for path in paths if path))


def mark_stale_answers(
    db: Session,
    repository_id: uuid.UUID,
    changed_paths: Collection[str] | None,
    head_sha: str,
) -> int:
    """Marks every answer that cited a changed file.

    Args:
        db: The sync session. The caller commits.
        repository_id: The repository that was synced.
        changed_paths: Repository-relative paths added, modified or deleted by
            the sync. ``None`` means the change set is unknown, and every answer
            with cited files is marked against all of them.
        head_sha: The commit the sync landed.

    Returns:
        How many answers were marked.
    """
    if changed_paths is None:
        result = db.execute(_MARK_ALL, {"repository_id": repository_id, "head_sha": head_sha})
    else:
        if not changed_paths:
            return 0
        result = db.execute(
            _MARK_CHANGED,
            {
                "repository_id": repository_id,
                "head_sha": head_sha,
                "changed": sorted(set(changed_paths)),
            },
        )
    return result.rowcount or 0


def compare_url(github_url: str, base_sha: str | None, head_sha: str | None) -> str | None:
    """GitHub's compare page between two commits, or ``None`` when it cannot be built."""
    if not base_sha or not head_sha:
        return None
    try:
        owner, name = parse_github_url(github_url)
    except ValueError:
        return None
    return f"https://github.com/{owner}/{name}/compare/{base_sha}...{head_sha}"
