from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Literal

from app.models.ast_symbol import AstSymbol
from app.models.dependency import Dependency
from app.models.file import File
from app.models.health_metric import HealthMetric
from sqlalchemy.orm import Session


def build_graph(
    db: Session,
    repo_id: uuid.UUID,
    level: Literal["file", "symbol"] = "file",
) -> dict:
    if level == "file":
        return _build_file_graph(db, repo_id)
    return _build_symbol_graph(db, repo_id)


def _build_file_graph(db: Session, repo_id: uuid.UUID) -> dict:
    files = db.query(File).filter_by(repository_id=repo_id).all()
    if not files:
        return {
            "nodes": [],
            "links": [],
            "metadata": {"total_nodes": 0, "total_edges": 0, "clusters": 0},
        }

    file_ids = {f.id for f in files}

    metrics = (
        db.query(HealthMetric)
        .filter(
            HealthMetric.repository_id == repo_id,
            HealthMetric.file_id.isnot(None),
        )
        .all()
    )
    health_by_file: dict[uuid.UUID, float] = {
        m.file_id: m.overall_score for m in metrics
    }

    nodes = [
        {
            "id": str(f.id),
            "label": f.path.split("/")[-1],
            "path": f.path,
            "group": _parent_dir(f.path),
            "kind": "file",
            "loc": f.loc or 0,
            "health": round(health_by_file.get(f.id, 50.0), 1),
            "language": f.language or "unknown",
        }
        for f in files
    ]

    SourceSymbol = AstSymbol.__table__.alias("src_sym")
    TargetSymbol = AstSymbol.__table__.alias("tgt_sym")

    rows = (
        db.query(
            Dependency.dep_type,
            SourceSymbol.c.file_id.label("src_file_id"),
            TargetSymbol.c.file_id.label("tgt_file_id"),
        )
        .join(SourceSymbol, Dependency.source_symbol_id == SourceSymbol.c.id)
        .join(TargetSymbol, Dependency.target_symbol_id == TargetSymbol.c.id)
        .filter(SourceSymbol.c.file_id.in_(file_ids))
        .filter(TargetSymbol.c.file_id.in_(file_ids))
        .all()
    )

    edge_map: dict[tuple[str, str], dict] = {}
    type_counter: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    for dep_type, src_file_id, tgt_file_id in rows:
        if src_file_id == tgt_file_id:
            continue  # skip intra-file edges
        key = (str(src_file_id), str(tgt_file_id))
        type_counter[key][dep_type] += 1

    for key, type_counts in type_counter.items():
        dominant_type = max(type_counts, key=type_counts.__getitem__)
        total_weight = sum(type_counts.values())
        edge_map[key] = {"type": dominant_type, "weight": total_weight}

    links = [
        {"source": src, "target": tgt, **meta} for (src, tgt), meta in edge_map.items()
    ]

    cluster_count = len({_top_dir(f.path) for f in files})

    return {
        "nodes": nodes,
        "links": links,
        "metadata": {
            "total_nodes": len(nodes),
            "total_edges": len(links),
            "clusters": cluster_count,
        },
    }


def _build_symbol_graph(db: Session, repo_id: uuid.UUID) -> dict:
    # Load function + class symbols for NODES
    node_symbols = (
        db.query(AstSymbol)
        .join(File, AstSymbol.file_id == File.id)
        .filter(File.repository_id == repo_id)
        .filter(AstSymbol.kind.in_(["function", "class"]))
        .all()
    )
    if not node_symbols:
        return {
            "nodes": [],
            "links": [],
            "metadata": {"total_nodes": 0, "total_edges": 0, "clusters": 0},
        }

    all_symbols = (
        db.query(AstSymbol)
        .join(File, AstSymbol.file_id == File.id)
        .filter(File.repository_id == repo_id)
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
    files = db.query(File).filter(File.id.in_(file_ids)).all()
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
            "health": _complexity_to_health(s.cyclomatic_complexity or 1),
        }
        for s in node_symbols
    ]

    deps = (
        db.query(Dependency)
        .filter(Dependency.source_symbol_id.in_(all_symbol_ids))
        .filter(Dependency.target_symbol_id.in_(all_symbol_ids))
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

        links.append({
            "source": str(src_id),
            "target": str(tgt_id),
            "type": d.dep_type,
            "weight": 1,
        })

    cluster_count = len(
        {
            _top_dir(file_map[s.file_id].path)
            for s in node_symbols
            if s.file_id in file_map
        }
    )

    return {
        "nodes": nodes,
        "links": links,
        "metadata": {
            "total_nodes": len(nodes),
            "total_edges": len(links),
            "clusters": cluster_count,
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


def _complexity_to_health(cyclomatic: int) -> float:
    score = max(0.0, 100.0 - (cyclomatic - 1) * 5.0)
    return round(score, 1)
