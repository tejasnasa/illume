"""Shared file-level dependency graph construction.

Collapses symbol-level ``Dependency`` edges into file-to-file edges. This is
the single source of truth for that join, used by the onboarding reading
order, architecture brief, graph visualizer, and .illume exporter — each of
which previously reimplemented it with slightly different dedup/normalization
rules.
"""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, aliased

from app.models import AstSymbol, Dependency, File


def query_file_edges(db: Session, repo_id: UUID) -> list[tuple[UUID, UUID]]:
    """Query all symbol dependencies for a repo, collapsed to file pairs.

    Args:
        db: Synchronous SQLAlchemy session.
        repo_id: Repository whose dependency edges should be read.

    Returns:
        Raw ``(source_file_id, target_file_id)`` pairs — one per underlying
        symbol-level dependency, including self-edges and duplicates.
    """
    TargetSymbol = aliased(AstSymbol, name="tgt_sym")

    rows = (
        db.query(
            AstSymbol.file_id.label("src_file"),
            TargetSymbol.file_id.label("tgt_file"),
        )
        .join(Dependency, Dependency.source_symbol_id == AstSymbol.id)
        .join(TargetSymbol, Dependency.target_symbol_id == TargetSymbol.id)
        .filter(
            AstSymbol.file_id.in_(select(File.id).where(File.repository_id == repo_id))
        )
        .all()
    )
    return [(r.src_file, r.tgt_file) for r in rows]


def build_adjacency(
    edges: list[tuple[UUID, UUID]],
) -> tuple[dict[UUID, set[UUID]], dict[UUID, set[UUID]]]:
    """Build forward and reverse adjacency sets from raw file-pair edges.

    Self-edges (a file depending on itself) are dropped; duplicates collapse
    naturally via the set values.

    Args:
        edges: ``(source_file_id, target_file_id)`` pairs.

    Returns:
        ``(deps, rdeps)`` where ``deps[file]`` is the set of files it depends
        on and ``rdeps[file]`` is the set of files that depend on it.
    """
    deps: dict[UUID, set[UUID]] = defaultdict(set)
    rdeps: dict[UUID, set[UUID]] = defaultdict(set)

    for src_file, tgt_file in edges:
        if src_file == tgt_file:
            continue
        deps[src_file].add(tgt_file)
        rdeps[tgt_file].add(src_file)

    return deps, rdeps


def build_file_graph(
    db: Session,
    repo_id: UUID,
) -> tuple[dict[UUID, set[UUID]], dict[UUID, set[UUID]]]:
    """Build forward (deps) and reverse (rdeps) file-level dependency maps.

    Convenience wrapper combining :func:`query_file_edges` and
    :func:`build_adjacency` for callers that just need adjacency sets from
    the database.

    Args:
        db: Synchronous SQLAlchemy session.
        repo_id: Repository whose graph should be built.

    Returns:
        ``(deps, rdeps)`` adjacency maps as described in :func:`build_adjacency`.
    """
    return build_adjacency(query_file_edges(db, repo_id))


async def query_file_edges_async(
    db: AsyncSession,
    repo_id: UUID,
    include_target_symbol: bool = False,
):
    """Async counterpart of :func:`query_file_edges`, with optional detail.

    Args:
        db: Asynchronous SQLAlchemy session.
        repo_id: Repository whose dependency edges should be read.
        include_target_symbol: When True, each row also carries the target
            symbol's name (needed by consumers that annotate edges, e.g. the
            .illume exporter).

    Returns:
        Rows of ``(source_file_id, target_file_id)`` — plus a third element,
        or ``(dep_type, source_file_id, target_file_id[, target_symbol_name])``
        depending on ``include_target_symbol``. Self-edges and duplicates are
        NOT filtered here; callers decide how to collapse them.
    """
    SourceSymbol = AstSymbol.__table__.alias("src_sym")
    TargetSymbol = AstSymbol.__table__.alias("tgt_sym")

    columns = [Dependency.dep_type, SourceSymbol.c.file_id, TargetSymbol.c.file_id]
    if include_target_symbol:
        columns.append(TargetSymbol.c.name)

    stmt = (
        select(*columns)
        .join(SourceSymbol, Dependency.source_symbol_id == SourceSymbol.c.id)
        .join(TargetSymbol, Dependency.target_symbol_id == TargetSymbol.c.id)
        .filter(
            SourceSymbol.c.file_id.in_(
                select(File.id).where(File.repository_id == repo_id)
            )
        )
        .filter(
            TargetSymbol.c.file_id.in_(
                select(File.id).where(File.repository_id == repo_id)
            )
        )
    )
    return (await db.execute(stmt)).all()


def build_dep_path_map(
    edges: list[tuple[UUID, UUID]],
    files_by_id: dict[UUID, File],
) -> dict[UUID, list[str]]:
    """Map each file to the paths of files it depends on (deduplicated).

    Args:
        edges: ``(source_file_id, target_file_id)`` pairs.
        files_by_id: Lookup of File rows by id, used to resolve paths.

    Returns:
        Dict of source file id -> ordered list of distinct dependency paths.
    """
    result: dict[UUID, list[str]] = defaultdict(list)
    seen: set[tuple[UUID, UUID]] = set()

    for src_file_id, tgt_file_id in edges:
        if not src_file_id or not tgt_file_id or src_file_id == tgt_file_id:
            continue
        edge = (src_file_id, tgt_file_id)
        if edge in seen:
            continue
        seen.add(edge)
        tgt_file = files_by_id.get(tgt_file_id)
        if tgt_file:
            result[src_file_id].append(tgt_file.path)

    return result
