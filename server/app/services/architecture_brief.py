"""Architecture brief generation.

Aggregates structural signals about a repository (key modules, critical
files, module-level dependency edges, data flow from entry points, and
external integrations), asks the LLM for a narrative architecture summary,
and stores the resulting sections on the repository's OnboardingGuide.
"""

import logging
from collections import defaultdict
from typing import Sequence, cast
from uuid import UUID

from openai import OpenAI
from openai.types.responses import ResponseInputParam
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    AstSymbol,
    CodeOwner,
    Dependency,
    File,
    GlossaryEntry,
    OnboardingGuide,
    Repository,
)
from app.services.file_graph import build_dep_path_map
from app.services.onboarding import _upsert_guide

logger = logging.getLogger(__name__)


TOP_KEY_MODULES = 10  # how many high-fan-in files to surface
DATA_FLOW_HOPS = 2  # how deep to trace from entry points
EXTERNAL_INTEGRATION_PREFIXES = (
    "stripe",
    "twilio",
    "sendgrid",
    "mailgun",
    "boto3",
    "botocore",
    "s3",
    "openai",
    "anthropic",
    "pinecone",
    "weaviate",
    "elasticsearch",
    "sentry_sdk",
    "datadog",
    "segment",
    "mixpanel",
    "firebase",
    "supabase",
    "google.cloud",
    "azure",
    "slack_sdk",
    "shopify",
    "hubspot",
    "digitalocean",
)


class _FileProxy:
    """Read-only stand-in for a ``File`` carrying only the brief's columns."""

    __slots__ = (
        "id",
        "path",
        "language",
        "fan_in",
        "fan_out",
        "criticality",
        "criticality_reasons",
    )

    def __init__(self, row) -> None:
        self.id = row.id
        self.path = row.path
        self.language = row.language
        self.fan_in = row.fan_in
        self.fan_out = row.fan_out
        self.criticality = row.criticality
        self.criticality_reasons = row.criticality_reasons


class _SymbolProxy:
    """Read-only stand-in for an ``AstSymbol`` carrying only the brief's columns."""

    __slots__ = ("id", "file_id", "kind", "name", "start_line")

    def __init__(self, row) -> None:
        self.id = row.id
        self.file_id = row.file_id
        self.kind = row.kind
        self.name = row.name
        self.start_line = row.start_line


class _DepProxy:
    """Read-only stand-in for a ``Dependency`` carrying only source/target ids."""

    __slots__ = ("source_symbol_id", "target_symbol_id")

    def __init__(self, row) -> None:
        self.source_symbol_id = row.source_symbol_id
        self.target_symbol_id = row.target_symbol_id


def _file_proxy(row) -> _FileProxy:
    return _FileProxy(row)


def _symbol_proxy(row) -> _SymbolProxy:
    return _SymbolProxy(row)


def _dep_proxy(row) -> _DepProxy:
    return _DepProxy(row)


def _get_key_modules(files: Sequence[File]) -> Sequence[dict]:
    """Return the top fan-in files as compact dicts."""
    sorted_files = sorted(files, key=lambda f: f.fan_in or 0, reverse=True)
    return [
        {
            "path": f.path,
            "fan_in": f.fan_in or 0,
            "fan_out": f.fan_out or 0,
            "language": f.language,
            "criticality": f.criticality,
        }
        for f in sorted_files[:TOP_KEY_MODULES]
    ]


def _get_critical_files(files: Sequence[File]) -> list[dict]:
    """Return files flagged critical/caution, critical first then by fan-in."""
    critical = [f for f in files if f.criticality in ("critical", "caution")]
    critical.sort(key=lambda f: (0 if f.criticality == "critical" else 1, -(f.fan_in or 0)))
    return [
        {
            "path": f.path,
            "criticality": f.criticality,
            "reasons": f.criticality_reasons or [],
            "fan_in": f.fan_in or 0,
        }
        for f in critical
    ]


def _trace_data_flow(
    entry_paths: Sequence[str],
    files_by_path: dict[str, File],
    deps: dict[UUID, list[str]],
    hops: int = DATA_FLOW_HOPS,
) -> Sequence[dict]:
    """BFS from entry points collecting file-to-file edges up to ``hops`` deep."""
    flow: list[dict] = []
    seen: set[tuple[str, str]] = set()

    # Cap entry points so a repo with many mains doesn't dominate the trace.
    for entry in entry_paths[:5]:
        file = files_by_path.get(entry)
        if not file:
            continue
        queue = [(entry, file.id, 0)]
        while queue:
            current_path, current_id, hop = queue.pop(0)
            if hop >= hops:
                continue
            for target_path in deps.get(current_id, []):
                edge = (current_path, target_path)
                # Dedup across entries: an edge reached via several paths is shown once.
                if edge in seen:
                    continue
                seen.add(edge)
                flow.append({"from": current_path, "to": target_path, "hop": hop + 1})
                target_file = files_by_path.get(target_path)
                if target_file:
                    queue.append((target_path, target_file.id, hop + 1))
                if len(flow) >= 40:
                    # Hard cap keeps the LLM prompt section bounded.
                    return flow
    return flow


def _detect_external_integrations(symbols: Sequence[AstSymbol]) -> Sequence[str]:
    """Find external services referenced by import symbols."""
    found: set[str] = set()
    for sym in symbols:
        if sym.kind != "import":
            continue
        name_lower = (sym.name or "").lower()
        # Match on dotted import prefix (e.g. "google.cloud"), then report
        # only the vendor root so variants collapse to one integration.
        for prefix in EXTERNAL_INTEGRATION_PREFIXES:
            if name_lower.startswith(prefix):
                found.add(prefix.split(".")[0])
                break
    return sorted(found)


def _get_ownership_summary(db: Session, file_ids: list[UUID]) -> list[dict]:
    """Summarize code ownership records for the given files."""
    owners = db.execute(select(CodeOwner).where(CodeOwner.file_id.in_(file_ids))).scalars().all()
    return [
        {
            "file_id": str(o.file_id),
            "primary_owner": o.primary_owner,
            "bus_factor": o.bus_factor,
            "is_knowledge_silo": o.is_knowledge_silo,
        }
        for o in owners
    ]


def _get_glossary_preview(db: Session, repo_id: UUID, limit: int = 10) -> list[dict]:
    """Fetch a small preview of the repo's glossary entries."""
    entries = (
        db.execute(select(GlossaryEntry).where(GlossaryEntry.repository_id == repo_id).limit(limit))
        .scalars()
        .all()
    )
    return [{"term": e.name, "definition": e.definition, "file_path": e.file_path} for e in entries]


def _build_file_dep_map(
    symbols: Sequence[AstSymbol],
    dependencies: Sequence[Dependency],
    files_by_id: dict[UUID, File],
) -> dict[UUID, list[str]]:
    """Map each file to the paths of files it depends on (deduplicated)."""
    # Reuse the shared symbol->file edge collapse instead of a local join.
    sym_to_file: dict[UUID, UUID] = {s.id: s.file_id for s in symbols}
    edges = [
        (sym_to_file.get(d.source_symbol_id), sym_to_file.get(d.target_symbol_id))
        for d in dependencies
    ]
    return build_dep_path_map(edges, files_by_id)


def _build_module_edges(
    dependencies: Sequence[Dependency],
    sym_to_file: dict[UUID, UUID],
    file_to_module: dict[UUID, str],
) -> list[tuple[str, str]]:
    """Collapse file dependencies into unique module-to-module edges."""
    edges: set[tuple[str, str]] = set()
    for dep in dependencies:
        src_file = sym_to_file.get(dep.source_symbol_id)
        tgt_file = sym_to_file.get(dep.target_symbol_id)
        if not src_file or not tgt_file:
            continue
        src_mod = file_to_module.get(src_file)
        tgt_mod = file_to_module.get(tgt_file)
        if src_mod and tgt_mod and src_mod != tgt_mod:
            edges.add((src_mod, tgt_mod))
    return list(edges)


def _group_symbols_by_module(
    symbols: Sequence[AstSymbol], files_by_id: dict[UUID, File]
) -> dict[str, list[str]]:
    """Group function/class/method symbols under their top-level module directory."""
    modules: dict[str, list[str]] = defaultdict(list)
    for sym in symbols:
        file = files_by_id.get(sym.file_id)
        if not file or sym.kind not in ("function", "class", "method"):
            continue
        # A module is just the first path segment; single-segment paths are top-level.
        parts = file.path.replace("\\", "/").split("/")
        module = parts[0] if len(parts) > 1 else "root"
        modules[module].append(f"{sym.kind} `{sym.name}` ({file.path}:{sym.start_line})")
    return modules


def _build_narrative_prompt(
    repo_name: str,
    detected_stack: dict,
    entry_points: list[str],
    key_modules: list[dict],
    module_edges: list[tuple[str, str]],
    module_symbols: dict[str, list[str]],
    external_integrations: list[str],
    data_flow: list[dict],
    total_files: int,
    readme_content: str | None = None,
) -> str:
    """Render the LLM prompt describing repo structure and the summary task."""

    lines = [
        f"You are analyzing a software repository called '{repo_name}'.",
        f"It contains {total_files} source files.",
        "",
    ]

    if readme_content:
        lines += [
            "## README",
            readme_content[:3000],
            "",
        ]

    lines += [
        "## Tech Stack",
        f"Languages: {', '.join(detected_stack.get('languages', ['unknown']))}",
        f"Frameworks: {', '.join(detected_stack.get('frameworks', ['none detected']))}",
        f"Databases: {', '.join(detected_stack.get('databases', ['none detected']))}",
        f"Infrastructure: {', '.join(detected_stack.get('infrastructure', ['none detected']))}",
        f"CI/CD: {', '.join(detected_stack.get('ci_cd', ['none detected']))}",
        "",
        "## Entry Points",
    ]

    if entry_points:
        for ep in entry_points[:8]:
            lines.append(f"  - {ep}")
    else:
        lines.append("  - None detected")

    lines += ["", "## Key Modules (highest fan-in)"]
    for km in key_modules:
        lines.append(
            f"  - {km['path']} (imported by {km['fan_in']} files, criticality: {km['criticality'] or 'unknown'})"
        )

    lines += ["", "## Module Structure"]
    for module, syms in sorted(module_symbols.items()):
        preview = syms[:8]
        lines.append(f"\n### {module}/")
        for s in preview:
            lines.append(f"  - {s}")
        if len(syms) > 8:
            lines.append(f"  ... and {len(syms) - 8} more")

    if module_edges:
        lines += ["", "## Module-Level Dependencies"]
        for src, tgt in sorted(module_edges)[:20]:
            lines.append(f"  - {src}/ → {tgt}/")

    if data_flow:
        lines += ["", "## Data Flow (traced from entry points)"]
        for step in data_flow[:20]:
            lines.append(f"  - hop {step['hop']}: {step['from']} → {step['to']}")

    if external_integrations:
        lines += ["", "## External Integrations Detected"]
        for integration in external_integrations:
            lines.append(f"  - {integration}")

    lines += [
        "",
        "## Task",
        "Write a concise architecture summary (5-8 sentences) covering:",
        "1. What this repository does at a high level",
        "2. How the modules are structured and what each major one does",
        "3. The key data/control flow between modules",
        "4. Any notable architectural patterns (layered, event-driven, pipeline, etc.)",
        "5. External services it integrates with",
        "",
        "Be specific — use actual module and file names from above. Do not speculate beyond what the structure shows.",
    ]
    return "\n".join(lines)


def _call_llm_narrative(prompt: str) -> str:
    """Call the LLM for a narrative; returns empty string on failure."""
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    try:
        response = client.responses.create(
            model=settings.AI_MODEL,
            input=cast(
                ResponseInputParam,
                [
                    {
                        "role": "system",
                        "content": (
                            "You are a senior software architect. Analyze repository structure "
                            "and write clear, accurate architecture summaries for new engineers."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            ),
            max_output_tokens=1200,
            reasoning={"effort": "low"},
        )
        content = response.output_text
        return content.strip() if content else ""
    except Exception as exc:
        logger.error("architecture_brief: LLM narrative call failed: %s", exc)
        return ""


def generate_brief(
    db: Session, repo: Repository, readme_content: str | None = None
) -> OnboardingGuide:
    """Generate an architecture brief for a repository.

    Aggregates key modules (highest fan-in), critical files, module-level
    dependency edges, a data-flow trace from detected entry points, external
    integrations, ownership and glossary previews, then prompts the LLM for a
    narrative summary. The narrative is stored on the repository and all
    sections are persisted on the OnboardingGuide's ``architecture_brief``.

    Args:
        db: SQLAlchemy database session.
        repo: The repository to summarize.
        readme_content: Optional README text included in the LLM prompt.

    Returns:
        The upserted OnboardingGuide with populated architecture sections.

    Raises:
        ValueError: If ``repo`` is falsy.
    """
    logger.info("architecture_brief: starting for repo %s", repo.id)

    if not repo:
        raise ValueError(f"Repository {repo.id} not found")

    # Project (id, path, language, fan_in, fan_out, criticality, criticality_reasons)
    # -- the columns the brief actually reads. ``select(File)`` would
    # materialise ORM instances carrying every other column too.
    file_rows = db.execute(
        select(
            File.id,
            File.path,
            File.language,
            File.fan_in,
            File.fan_out,
            File.criticality,
            File.criticality_reasons,
        ).where(File.repository_id == repo.id)
    ).all()
    files_by_id: dict[UUID, File] = {row.id: _file_proxy(row) for row in file_rows}
    files_by_path: dict[str, File] = {row.path: _file_proxy(row) for row in file_rows}
    file_ids = [row.id for row in file_rows]

    if not file_rows:
        logger.warning("architecture_brief: no files found for repo %s", repo.id)
        return _upsert_guide(db, repo.id)

    # Symbols: only id, file_id, kind, name. ``select(AstSymbol)`` would
    # also load source_code and docstring, neither of which the brief uses.
    symbol_rows = db.execute(
        select(
            AstSymbol.id,
            AstSymbol.file_id,
            AstSymbol.kind,
            AstSymbol.name,
            AstSymbol.start_line,
        ).where(AstSymbol.file_id.in_(file_ids))
    ).all()
    symbols: Sequence[AstSymbol] = [_symbol_proxy(row) for row in symbol_rows]

    dependencies: list[tuple[UUID, UUID]] = []
    if symbols:
        # Only source/target ids are read; ``dep_type`` is unused by the brief.
        symbol_ids = [s.id for s in symbols]
        for row in db.execute(
            select(Dependency.source_symbol_id, Dependency.target_symbol_id).where(
                Dependency.source_symbol_id.in_(symbol_ids)
            )
        ):
            dependencies.append(_dep_proxy(row))

    detected_stack: dict = repo.detected_stack or {}
    entry_points: list[str] = list(repo.entry_points or [])

    key_modules = _get_key_modules(list(files_by_id.values()))
    critical_files = _get_critical_files(list(files_by_id.values()))

    sym_to_file: dict[UUID, UUID] = {s.id: s.file_id for s in symbols}
    # Module identity = first path segment; files without a directory go to "root".
    file_to_module: dict[UUID, str] = {
        row.id: (
            row.path.replace("\\", "/").split("/")[0]
            if "/" in row.path.replace("\\", "/")
            else "root"
        )
        for row in file_rows
    }

    module_symbols = _group_symbols_by_module(symbols, files_by_id)
    module_edges = _build_module_edges(dependencies, sym_to_file, file_to_module)
    file_dep_map = _build_file_dep_map(symbols, dependencies, files_by_id)
    data_flow = _trace_data_flow(entry_points, files_by_path, file_dep_map)
    external_integrations = _detect_external_integrations(symbols)

    key_module_ids = [
        files_by_path[km["path"]].id for km in key_modules if km["path"] in files_by_path
    ]
    ownership_summary = _get_ownership_summary(db, key_module_ids)
    glossary_preview = _get_glossary_preview(db, repo.id)

    guide = (
        db.execute(select(OnboardingGuide).where(OnboardingGuide.repository_id == repo.id))
        .scalars()
        .first()
    )
    reading_order_preview = (guide.reading_order or [])[:10] if guide else []

    prompt = _build_narrative_prompt(
        repo_name=repo.name,
        detected_stack=detected_stack,
        entry_points=list(entry_points),
        key_modules=list(key_modules),
        module_edges=module_edges,
        module_symbols=module_symbols,
        external_integrations=list(external_integrations),
        data_flow=list(data_flow),
        total_files=len(file_rows),
        readme_content=readme_content,
    )

    narrative = _call_llm_narrative(prompt)
    # Persist a placeholder rather than failing the whole brief when the LLM is down.
    if not narrative:
        narrative = "Architecture summary could not be generated."

    logger.info("architecture_brief: narrative generated (%d chars)", len(narrative))

    architecture_sections = {
        "narrative": narrative,
        "tech_stack": detected_stack,
        "entry_points": entry_points,
        "key_modules": key_modules,
        "critical_files": critical_files,
        "data_flow": data_flow,
        "external_integrations": external_integrations,
        "module_edges": [{"from": s, "to": t} for s, t in module_edges[:30]],
        "ownership_summary": ownership_summary,
        "glossary_preview": glossary_preview,
        "reading_order_preview": reading_order_preview,
        "total_files": len(file_rows),
        "total_symbols": len(symbols),
    }

    repo.architecture_summary = narrative
    db.add(repo)

    guide = _upsert_guide(
        db,
        repo.id,
        architecture_brief=architecture_sections,
        critical_files=critical_files,
    )
    logger.info("architecture_brief: done for repo %s", repo.id)
    return guide
