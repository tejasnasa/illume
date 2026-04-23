import uuid
from collections import defaultdict
from typing import Literal

from app.models.ast_symbol import AstSymbol
from app.models.dependency import Dependency
from app.models.file import File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_CRITICALITY_SCORE: dict[str | None, float] = {
    "critical": 100.0,
    "caution": 75.0,
    "safe": 25.0,
    None: 50.0,
}


async def build_graph(
    db: AsyncSession,
    repo_id: uuid.UUID,
    level: Literal["file", "symbol"] = "file",
) -> dict:
    if level == "file":
        return await _build_file_graph(db, repo_id)
    return await _build_symbol_graph(db, repo_id)


async def _build_file_graph(db: AsyncSession, repo_id: uuid.UUID) -> dict:
    files = (
        (await db.execute(select(File).filter(File.repository_id == repo_id)))
        .scalars()
        .all()
    )

    if not files:
        return {
            "nodes": [],
            "links": [],
            "metadata": {"total_nodes": 0, "total_edges": 0, "clusters": 0},
        }

    file_ids = {f.id for f in files}

    nodes = [
        {
            "id": str(f.id),
            "label": f.path.split("/")[-1],
            "path": f.path,
            "group": _parent_dir(f.path),
            "kind": "file",
            "loc": f.loc or 0,
            "criticality": f.criticality or "medium",
            "criticality_score": _CRITICALITY_SCORE.get(
                (f.criticality or "medium").lower().strip(),
                50.0,
            ),
            "language": f.language or "unknown",
            "fan_in": f.fan_in or 0,
            "fan_out": f.fan_out or 0,
        }
        for f in files
    ]

    SourceSymbol = AstSymbol.__table__.alias("src_sym")
    TargetSymbol = AstSymbol.__table__.alias("tgt_sym")

    rows = (
        await db.execute(
            select(
                Dependency.dep_type,
                SourceSymbol.c.file_id.label("src_file_id"),
                TargetSymbol.c.file_id.label("tgt_file_id"),
            )
            .join(SourceSymbol, Dependency.source_symbol_id == SourceSymbol.c.id)
            .join(TargetSymbol, Dependency.target_symbol_id == TargetSymbol.c.id)
            .filter(SourceSymbol.c.file_id.in_(file_ids))
            .filter(TargetSymbol.c.file_id.in_(file_ids))
        )
    ).all()

    type_counter: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    for dep_type, src_file_id, tgt_file_id in rows:
        if src_file_id == tgt_file_id:
            continue
        type_counter[(str(src_file_id), str(tgt_file_id))][dep_type] += 1

    links = [
        {
            "source": src,
            "target": tgt,
            "type": max(type_counts, key=type_counts.__getitem__),
            "weight": sum(type_counts.values()),
        }
        for (src, tgt), type_counts in type_counter.items()
    ]

    return {
        "nodes": nodes,
        "links": links,
        "metadata": {
            "total_nodes": len(nodes),
            "total_edges": len(links),
            "clusters": len({_top_dir(f.path) for f in files}),
        },
    }


async def _build_symbol_graph(db: AsyncSession, repo_id: uuid.UUID) -> dict:
    node_symbols = (
        (
            await db.execute(
                select(AstSymbol)
                .join(File, AstSymbol.file_id == File.id)
                .filter(File.repository_id == repo_id)
                .filter(AstSymbol.kind.in_(["function", "class"]))
            )
        )
        .scalars()
        .all()
    )

    if not node_symbols:
        return {
            "nodes": [],
            "links": [],
            "metadata": {"total_nodes": 0, "total_edges": 0, "clusters": 0},
        }

    all_symbols = (
        (
            await db.execute(
                select(AstSymbol)
                .join(File, AstSymbol.file_id == File.id)
                .filter(File.repository_id == repo_id)
            )
        )
        .scalars()
        .all()
    )

    all_symbol_ids = {s.id for s in all_symbols}
    node_symbol_ids = {s.id for s in node_symbols}

    file_to_node_ids: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for s in node_symbols:
        file_to_node_ids[s.file_id].append(s.id)

    import_symbol_to_file: dict[uuid.UUID, uuid.UUID] = {
        s.id: s.file_id for s in all_symbols if s.kind == "import"
    }

    file_ids = {s.file_id for s in node_symbols}
    files = (
        (await db.execute(select(File).filter(File.id.in_(file_ids)))).scalars().all()
    )
    file_map = {f.id: f for f in files}

    nodes = [
        {
            "id": str(s.id),
            "label": s.name,
            "path": file_map[s.file_id].path if s.file_id in file_map else "unknown",
            "group": _parent_dir(file_map[s.file_id].path)
            if s.file_id in file_map
            else "unknown",
            "kind": s.kind,
            "loc": (s.end_line - s.start_line + 1)
            if s.start_line and s.end_line
            else 0,
            "complexity": s.cyclomatic_complexity or 0,
            "criticality": file_map[s.file_id].criticality or "medium"
            if s.file_id in file_map
            else "medium",
            "criticality_score": _CRITICALITY_SCORE.get(
                file_map[s.file_id].criticality if s.file_id in file_map else None,
                50.0,
            ),
        }
        for s in node_symbols
    ]

    deps = (
        (
            await db.execute(
                select(Dependency)
                .filter(Dependency.source_symbol_id.in_(all_symbol_ids))
                .filter(Dependency.target_symbol_id.in_(all_symbol_ids))
            )
        )
        .scalars()
        .all()
    )

    seen_edges: set[tuple[str, str]] = set()
    links = []

    for d in deps:
        src_id = d.source_symbol_id
        tgt_id = d.target_symbol_id

        if src_id not in node_symbol_ids:
            src_file_id = import_symbol_to_file.get(src_id)
            if not src_file_id:
                continue
            candidates = file_to_node_ids.get(src_file_id, [])
            if not candidates:
                continue
            src_id = candidates[0]

        if tgt_id not in node_symbol_ids:
            tgt_file_id = import_symbol_to_file.get(tgt_id)
            if not tgt_file_id:
                continue
            candidates = file_to_node_ids.get(tgt_file_id, [])
            if not candidates:
                continue
            tgt_id = candidates[0]

        if src_id == tgt_id:
            continue

        key = (str(src_id), str(tgt_id))
        if key in seen_edges:
            continue
        seen_edges.add(key)

        links.append(
            {
                "source": str(src_id),
                "target": str(tgt_id),
                "type": d.dep_type,
                "weight": 1,
            }
        )

    return {
        "nodes": nodes,
        "links": links,
        "metadata": {
            "total_nodes": len(nodes),
            "total_edges": len(links),
            "clusters": len(
                {
                    _top_dir(file_map[s.file_id].path)
                    for s in node_symbols
                    if s.file_id in file_map
                }
            ),
        },
    }


def _parent_dir(path: str) -> str:
    path = path.replace("\\", "/")
    parts = path.split("/")
    return "/".join(parts[:-1]) if len(parts) > 1 else "root"


def _top_dir(path: str) -> str:
    path = path.replace("\\", "/")
    parts = path.split("/")
    return parts[0] if len(parts) > 1 else "root"
