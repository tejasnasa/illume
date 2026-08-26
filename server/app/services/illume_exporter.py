"""Compact text export of repository analysis.

Renders a single text document with @@META, @@ARCH, @@GRAPH, @@SYMBOLS and
@@HOTSPOTS sections, suitable for feeding to an LLM or for quick inspection.
"""

import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AstSymbol,
    Dependency,
    File,
    Repository,
)
from app.services.file_graph import query_file_edges_async


async def generate_illume_file(db: AsyncSession, repo_id: uuid.UUID) -> str | None:
    """Render a compact text export of a repository's analysis data.

    Sections:
        @@META: repo identity, stack summary, entry points, counts.
        @@ARCH: stored architecture narrative.
        @@GRAPH: file-to-file dependency edges with dep types and target
            symbols (capped at 500 edges, 5 symbols per edge).
        @@SYMBOLS: function/class/method listings for the top 200 files by
            fan-in (capped at 30 symbols per file).
        @@HOTSPOTS: non-safe-criticality files sorted by fan-in (capped at 50),
            including max cyclomatic complexity per file.

    Args:
        db: Async SQLAlchemy session.
        repo_id: Repository to export.

    Returns:
        The rendered text, or None if the repo or its files are missing.
    """
    repo = (
        await db.execute(select(Repository).where(Repository.id == repo_id))
    ).scalar_one_or_none()
    if not repo:
        return None

    files = (
        (await db.execute(select(File).where(File.repository_id == repo_id)))
        .scalars()
        .all()
    )
    if not files:
        return None

    file_ids = [f.id for f in files]
    file_id_to_path = {f.id: f.path for f in files}

    symbols = (
        (await db.execute(select(AstSymbol).where(AstSymbol.file_id.in_(file_ids))))
        .scalars()
        .all()
    )

    file_id_to_symbols = defaultdict(list)
    file_id_to_max_cc = {}
    for s in symbols:
        if s.cyclomatic_complexity is not None:
            file_id_to_max_cc[s.file_id] = max(
                file_id_to_max_cc.get(s.file_id, 0), s.cyclomatic_complexity
            )
        if s.kind in ("function", "class", "method"):
            file_id_to_symbols[s.file_id].append(s)

    # Shared symbol->file edge query (with target names for annotations).
    rows = await query_file_edges_async(db, repo_id, include_target_symbol=True)

    total_edges = len(rows)

    edge_symbols = defaultdict(lambda: defaultdict(set))
    # Aggregate raw dependency rows into one entry per file pair, keyed by
    # dep_type, with the set of target symbols referenced under each type.
    # Row shape: (dep_type, src_file_id, tgt_file_id, tgt_symbol_name).
    for dep_type, src_file_id, tgt_file_id, tgt_symbol_name in rows:
        src_path = file_id_to_path.get(src_file_id)
        tgt_path = file_id_to_path.get(tgt_file_id)
        if src_path and tgt_path and src_path != tgt_path:
            edge_symbols[(src_path, tgt_path)][dep_type].add(tgt_symbol_name)

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
        # detected_stack values vary in shape depending on the detector;
        # flatten lists, dict keys, and bare strings into one token list.
        for category in [
            "languages",
            "frameworks",
            "databases",
            "infrastructure",
            "ci_cd",
        ]:
            items = repo.detected_stack.get(category)
            if items:
                if isinstance(items, list):
                    stack_parts.extend(items)
                elif isinstance(items, dict):
                    stack_parts.extend(items.keys())
                elif isinstance(items, str):
                    stack_parts.append(items)
    stack_str = ",".join(dict.fromkeys(stack_parts))  # dedupe while preserving order
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
    # Deterministic ordering + cap keeps exports comparable across runs and bounded in size.
    sorted_edges = sorted(edge_symbols.items(), key=lambda x: (x[0][0], x[0][1]))
    capped_edges = sorted_edges[:500]

    for (src_path, tgt_path), dep_dict in capped_edges:
        annotations = []
        for dep_type, syms in sorted(dep_dict.items()):
            # Anonymous imports carry no useful name; drop them unless they're all we have.
            filtered_syms = {
                s for s in syms if not (dep_type == "imports" and s == "<anonymous>")
            }
            if not filtered_syms:
                continue
            sorted_syms = sorted(filtered_syms)
            capped_syms = sorted_syms[:5]
            syms_str = ",".join(capped_syms)
            if len(sorted_syms) > 5:
                syms_str += ",..."
            annotations.append(f"{dep_type}:{syms_str}")
        if annotations:
            anno_str = "; ".join(annotations)
            lines.append(f"{src_path} -> {tgt_path} [{anno_str}]")
        else:
            lines.append(f"{src_path} -> {tgt_path}")
    if len(sorted_edges) > 500:
        lines.append(f"... and {len(sorted_edges) - 500} more edges")
    lines.append("")

    lines.append("@@SYMBOLS")
    # Prioritize widely-imported files so the cap of 200 covers the load-bearing code.
    sorted_files_by_fan_in = sorted(files, key=lambda f: f.fan_in or 0, reverse=True)
    top_symbol_files = sorted_files_by_fan_in[:200]
    for f in top_symbol_files:
        sym_list = file_id_to_symbols.get(f.id, [])
        if not sym_list:
            continue
        formatted_syms = []
        for s in sorted(sym_list, key=lambda x: (x.kind, x.name)):
            kind_prefix = (
                "fn"
                if s.kind == "function"
                else ("cls" if s.kind == "class" else "meth")
            )
            formatted_syms.append(f"{kind_prefix}:{s.name}")
        capped_formatted = formatted_syms[:30]
        syms_str = " ".join(capped_formatted)
        if len(formatted_syms) > 30:
            syms_str += " ..."
        lines.append(f"{f.path}: {syms_str}")
    lines.append("")

    lines.append("@@HOTSPOTS")
    hotspot_files = [
        f for f in files if f.criticality and f.criticality.lower() != "safe"
    ]
    # Fan-in ordering surfaces risky-but-central files first within the cap of 50.
    sorted_hotspots = sorted(hotspot_files, key=lambda f: f.fan_in or 0, reverse=True)[
        :50
    ]
    for h in sorted_hotspots:
        max_cc = file_id_to_max_cc.get(h.id)
        cc_str = f",cc={max_cc}" if max_cc is not None else ""
        lines.append(
            f"{h.path} [{h.criticality.lower()},fan_in={h.fan_in or 0}{cc_str}]"
        )
    lines.append("")

    return "\n".join(lines)
