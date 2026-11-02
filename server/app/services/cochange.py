"""Builds the file co-change table from a repository's stored commits.

Two files that keep changing in the same commits are usually coupled even when
neither imports the other. This module counts, for every pair of current files,
how many commits touched both, and keeps the strongest pairs in
``file_cochange`` for the co-change retrieval channel.

The builder is synchronous, like the rest of ingestion, and does not commit:
the caller owns the transaction, so a sync can rebuild the table in the same
transaction as the rest of the deterministic data.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from itertools import combinations
from uuid import UUID

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.models import Commit, File
from app.models.file_cochange import FileCochange

logger = logging.getLogger(__name__)

# A commit touching more files than this is a bulk change (a rename, a
# formatter run, a vendored import) and says nothing about coupling.
MAX_FILES_PER_COMMIT = 30

# A pair needs to have changed together at least this often to be kept.
MIN_TOGETHER = 2

# How many strongest partners each file keeps.
MAX_PARTNERS_PER_FILE = 50

_INSERT_BATCH = 5_000

Pair = tuple[UUID, UUID]


def _count(
    changed_lists: Iterable[list[str] | None], file_by_path: dict[str, UUID]
) -> tuple[dict[UUID, int], dict[Pair, int]]:
    """Per-file and per-pair commit counts over the usable commits.

    Pairs are keyed with the smaller ``UUID`` first. ``UUID`` objects order by
    their 128-bit integer value, which is how Postgres orders the ``uuid`` type,
    so a pair keyed here satisfies the table's ``file_a_id < file_b_id`` check.
    """
    file_counts: dict[UUID, int] = defaultdict(int)
    pair_counts: dict[Pair, int] = defaultdict(int)
    for paths in changed_lists:
        if not paths or len(paths) > MAX_FILES_PER_COMMIT:
            continue
        # A path listed twice, or a path that no longer exists, counts once or not at all.
        ids = sorted({file_by_path[path] for path in paths if path in file_by_path})
        for file_id in ids:
            file_counts[file_id] += 1
        for pair in combinations(ids, 2):
            pair_counts[pair] += 1
    return file_counts, pair_counts


def _select_pairs(
    file_counts: dict[UUID, int], pair_counts: dict[Pair, int]
) -> list[tuple[UUID, UUID, int, int, int, float]]:
    """Applies the thresholds and per-file cap, returning rows ready to store."""
    scored: dict[Pair, tuple[int, float]] = {}
    partners: dict[UUID, list[tuple[float, UUID]]] = defaultdict(list)
    for (a, b), together in pair_counts.items():
        if together < MIN_TOGETHER:
            continue
        jaccard = together / (file_counts[a] + file_counts[b] - together)
        scored[(a, b)] = (together, jaccard)
        partners[a].append((jaccard, b))
        partners[b].append((jaccard, a))

    # A pair survives when it is among the strongest partners of either of its
    # files, not both: a small utility file can be the top partner of a hub
    # without the hub keeping the utility among its own 50.
    keep: set[Pair] = set()
    for file_id, others in partners.items():
        others.sort(key=lambda item: (-item[0], item[1]))
        for _, other in others[:MAX_PARTNERS_PER_FILE]:
            keep.add((file_id, other) if file_id < other else (other, file_id))

    rows = []
    for a, b in sorted(keep):
        together, jaccard = scored[(a, b)]
        rows.append((a, b, together, file_counts[a], file_counts[b], jaccard))
    return rows


def build_cochange(db: Session, repo_id: UUID) -> int:
    """Rebuilds one repository's ``file_cochange`` rows from its stored commits.

    Commits that touch more than 30 files are ignored. Paths are matched to the
    repository's current files, and paths that no longer exist are dropped. A
    pair is kept when it changed together in at least two commits and is among
    the 50 strongest partners (by jaccard, then partner id) of either file. The
    repository's existing rows are deleted first.

    Does not commit; the caller owns the transaction.

    Args:
        db: Synchronous SQLAlchemy session.
        repo_id: Repository to rebuild.

    Returns:
        The number of pairs stored.
    """
    file_by_path: dict[str, UUID] = {
        path: file_id
        for file_id, path in db.execute(
            select(File.id, File.path).where(File.repository_id == repo_id)
        )
    }
    changed_lists = (
        row[0]
        for row in db.execute(
            select(Commit.changed_files_list)
            .where(Commit.repository_id == repo_id)
            .execution_options(yield_per=1_000)
        )
    )
    file_counts, pair_counts = _count(changed_lists, file_by_path)
    rows = _select_pairs(file_counts, pair_counts)

    db.execute(delete(FileCochange).where(FileCochange.repository_id == repo_id))
    for start in range(0, len(rows), _INSERT_BATCH):
        db.execute(
            insert(FileCochange),
            [
                {
                    "file_a_id": a,
                    "file_b_id": b,
                    "repository_id": repo_id,
                    "together": together,
                    "a_count": a_count,
                    "b_count": b_count,
                    "jaccard": jaccard,
                }
                for a, b, together, a_count, b_count, jaccard in rows[start : start + _INSERT_BATCH]
            ],
        )
    logger.info("cochange repo=%s pairs=%d", repo_id, len(rows))
    return len(rows)
