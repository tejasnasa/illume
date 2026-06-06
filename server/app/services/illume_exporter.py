import uuid
from datetime import datetime
from collections import defaultdict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Repository,
    File,
    AstSymbol,
    Dependency,
    GlossaryEntry,
    OnboardingGuide,
)

async def generate_illume_file(db: AsyncSession, repo_id: uuid.UUID) -> str | None:
    repo = (
        await db.execute(select(Repository).where(Repository.id == repo_id))
    ).scalar_one_or_none()
    if not repo:
        return None

    files = (
        await db.execute(select(File).where(File.repository_id == repo_id))
    ).scalars().all()
    if not files:
        return None

    file_ids = [f.id for f in files]
    file_id_to_path = {f.id: f.path for f in files}

    guide = (
        await db.execute(
            select(OnboardingGuide).where(OnboardingGuide.repository_id == repo_id)
        )
    ).scalar_one_or_none()

    glossary_entries = (
        await db.execute(
            select(GlossaryEntry).where(GlossaryEntry.repository_id == repo_id)
        )
    ).scalars().all()

    symbols = (
        await db.execute(select(AstSymbol).where(AstSymbol.file_id.in_(file_ids)))
    ).scalars().all()

    file_id_to_symbols = defaultdict(list)
    file_id_to_max_cc = {}
    for s in symbols:
        if s.cyclomatic_complexity is not None:
            file_id_to_max_cc[s.file_id] = max(
                file_id_to_max_cc.get(s.file_id, 0), s.cyclomatic_complexity
            )
        if s.kind in ("function", "class", "method"):
            file_id_to_symbols[s.file_id].append(s)

    SourceSymbol = AstSymbol.__table__.alias("src_sym")
    TargetSymbol = AstSymbol.__table__.alias("tgt_sym")

    rows = (
        await db.execute(
            select(
                Dependency.dep_type,
                SourceSymbol.c.file_id.label("src_file_id"),
                TargetSymbol.c.file_id.label("tgt_file_id"),
                TargetSymbol.c.name.label("tgt_symbol_name"),
            )
            .join(SourceSymbol, Dependency.source_symbol_id == SourceSymbol.c.id)
            .join(TargetSymbol, Dependency.target_symbol_id == TargetSymbol.c.id)
            .filter(SourceSymbol.c.file_id.in_(file_ids))
            .filter(TargetSymbol.c.file_id.in_(file_ids))
        )
    ).all()

    total_edges = len(rows)

    edge_symbols = defaultdict(lambda: defaultdict(set))
    for row in rows:
        src_path = file_id_to_path.get(row.src_file_id)
        tgt_path = file_id_to_path.get(row.tgt_file_id)
        if src_path and tgt_path and src_path != tgt_path:
            edge_symbols[(src_path, tgt_path)][row.dep_type].add(row.tgt_symbol_name)

    lines = []

    lines.append("@@META")
    lines.append(f"repo={repo.name}")
    lines.append(f"url={repo.github_url or ''}")
    lines.append(f"branch={repo.default_branch or 'main'}")
    lines.append(f"lang={repo.primary_language or 'unknown'}")
    lines.append(f"generated={datetime.utcnow().strftime('%Y-%m-%d')}")
    lines.append(f"files={len(files)} symbols={len(symbols)} edges={total_edges}")

    stack_parts = []
    if repo.detected_stack:
        for category in ["languages", "frameworks", "databases", "infrastructure", "ci_cd"]:
            items = repo.detected_stack.get(category)
            if items:
                if isinstance(items, list):
                    stack_parts.extend(items)
                elif isinstance(items, dict):
                    stack_parts.extend(items.keys())
                elif isinstance(items, str):
                    stack_parts.append(items)
    stack_str = ",".join(dict.fromkeys(stack_parts))
    lines.append(f"stack={stack_str}")

    entry_list = []
    if repo.entry_points:
        if isinstance(repo.entry_points, list):
            entry_list = repo.entry_points
        elif isinstance(repo.entry_points, dict):
            entry_list = list(repo.entry_points.keys())
    entry_str = ",".join(entry_list)
    lines.append(f"entry={entry_str}")
    lines.append("")

    lines.append("@@ARCH")
    if repo.architecture_summary:
        lines.append(repo.architecture_summary.strip())
    else:
        lines.append("No architecture summary generated.")
    lines.append("")

    lines.append("@@GRAPH")
    sorted_edges = sorted(edge_symbols.items(), key=lambda x: (x[0][0], x[0][1]))
    capped_edges = sorted_edges[:500]

    for (src_path, tgt_path), dep_dict in capped_edges:
        annotations = []
        for dep_type, syms in sorted(dep_dict.items()):
            sorted_syms = sorted(syms)
            capped_syms = sorted_syms[:5]
            syms_str = ",".join(capped_syms)
            if len(sorted_syms) > 5:
                syms_str += ",..."
            annotations.append(f"{dep_type}:{syms_str}")
        anno_str = "; ".join(annotations)
        lines.append(f"{src_path} -> {tgt_path} [{anno_str}]")
    if len(sorted_edges) > 500:
        lines.append(f"... and {len(sorted_edges) - 500} more edges")
    lines.append("")

    lines.append("@@SYMBOLS")
    sorted_files_by_fan_in = sorted(files, key=lambda f: f.fan_in or 0, reverse=True)
    top_symbol_files = sorted_files_by_fan_in[:200]
    for f in top_symbol_files:
        sym_list = file_id_to_symbols.get(f.id, [])
        if not sym_list:
            continue
        formatted_syms = []
        for s in sorted(sym_list, key=lambda x: (x.kind, x.name)):
            kind_prefix = "fn" if s.kind == "function" else ("cls" if s.kind == "class" else "meth")
            formatted_syms.append(f"{kind_prefix}:{s.name}")
        capped_formatted = formatted_syms[:30]
        syms_str = " ".join(capped_formatted)
        if len(formatted_syms) > 30:
            syms_str += " ..."
        lines.append(f"{f.path}: {syms_str}")
    lines.append("")

    lines.append("@@HOTSPOTS")
    hotspot_files = [f for f in files if f.criticality and f.criticality.lower() != "safe"]
    sorted_hotspots = sorted(hotspot_files, key=lambda f: f.fan_in or 0, reverse=True)[:50]
    for h in sorted_hotspots:
        max_cc = file_id_to_max_cc.get(h.id)
        cc_str = f",cc={max_cc}" if max_cc is not None else ""
        lines.append(f"{h.path} [{h.criticality.lower()},fan_in={h.fan_in or 0}{cc_str}]")
    lines.append("")

    lines.append("@@CLUSTERS")
    clusters = defaultdict(list)
    for f in files:
        parts = f.path.replace("\\", "/").split("/")
        cluster_name = parts[0] if len(parts) > 1 else "root"
        clusters[cluster_name].append(f.path)

    for cluster_name, paths in sorted(clusters.items()):
        sorted_paths = sorted(paths)
        capped_paths = sorted_paths[:20]
        paths_str = ",".join(capped_paths)
        if len(sorted_paths) > 20:
            paths_str += ",..."
        lines.append(f"{cluster_name}: {paths_str}")
    lines.append("")

    lines.append("@@GLOSSARY")
    sorted_glossary = sorted(glossary_entries, key=lambda e: e.name)[:100]
    for entry in sorted_glossary:
        clean_def = entry.definition.replace("\n", " ").replace("\r", " ").strip()
        lines.append(f"{entry.name}: {clean_def}")
    if len(glossary_entries) > 100:
        lines.append(f"... and {len(glossary_entries) - 100} more glossary entries")
    lines.append("")

    lines.append("@@READING_ORDER")
    if guide and guide.reading_order:
        sorted_reading = sorted(guide.reading_order, key=lambda x: x.get("position", 0))[:50]
        for item in sorted_reading:
            path = item.get("path") or item.get("file_path") or ""
            annotation = item.get("annotation") or ""
            if path:
                anno_str = f" — {annotation.strip()}" if annotation else ""
                lines.append(f"{item.get('position', 0)}. {path}{anno_str}")
        if len(guide.reading_order) > 50:
            lines.append(f"... and {len(guide.reading_order) - 50} more files")
    else:
        lines.append("No reading order available.")
    lines.append("")

    return "\n".join(lines)
