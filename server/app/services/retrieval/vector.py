"""pgvector tuning shared by every repository-filtered vector search."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# pgvector 0.8 added iterative index scans. Below it, a filtered HNSW query
# returns the global ``ef_search`` nearest rows and applies ``repository_id``
# afterwards, so a small repository on a large instance can come back with too
# few hits. The extension version is fixed for the life of a process, so the
# answer is cached rather than re-read on every search.
_ITERATIVE_SCAN_MIN_VERSION = (0, 8)
_pgvector_supports_iterative_scan: bool | None = None


def _version_tuple(raw: str | None) -> tuple[int, ...]:
    """Parses a dotted version string into its numeric components."""
    if not raw:
        return ()
    parts: list[int] = []
    for chunk in raw.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


async def prepare_filtered_vector_search(db: AsyncSession) -> None:
    """Tunes pgvector for a repository-filtered HNSW search.

    ``hnsw.ef_search`` is raised from its 40-row default to 200 so the walk has
    a wider candidate pool, and ``hnsw.iterative_scan`` is set to
    ``strict_order`` so the scan keeps going until the filter has produced
    enough rows instead of stopping at the global top of the index.
    ``strict_order`` rather than ``relaxed_order`` because the diversity caps
    take hits in the order they arrive, and ``relaxed_order`` may return them
    slightly out of distance order.

    Both settings are transactional (``SET LOCAL``), which is why they are
    issued on the search's own session rather than on a connection pool. On a
    pgvector older than 0.8 ``iterative_scan`` does not exist and is skipped;
    the index is still used there, so a small repository on a large instance
    can come back with fewer hits than asked for.
    """
    global _pgvector_supports_iterative_scan
    if _pgvector_supports_iterative_scan is None:
        raw_version = (
            await db.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
        ).scalar_one_or_none()
        _pgvector_supports_iterative_scan = (
            _version_tuple(raw_version)[:2] >= _ITERATIVE_SCAN_MIN_VERSION
        )

    await db.execute(text("SET LOCAL hnsw.ef_search = 200"))
    if _pgvector_supports_iterative_scan:
        await db.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
