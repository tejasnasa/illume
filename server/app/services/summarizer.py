from collections import defaultdict
from typing import Sequence, cast
from uuid import UUID

from app.core.config import settings
from app.models.ast_symbol import AstSymbol
from app.models.dependency import Dependency
from app.models.file import File
from openai import OpenAI
from openai.types.responses import ResponseInputParam
from sqlalchemy import select
from sqlalchemy.orm import Session

client = OpenAI(api_key=settings.OPENAI_API_KEY)


def _group_symbols_by_module(
    symbols: Sequence[AstSymbol], files: dict[UUID, File]
) -> dict[str, list[str]]:
    modules: dict[str, list[str]] = defaultdict(list)
    for sym in symbols:
        file = files.get(sym.file_id)
        if not file:
            continue
        parts = file.path.replace("\\", "/").split("/")
        module = parts[0] if len(parts) > 1 else "root"
        if sym.kind in ("function", "class", "method"):
            modules[module].append(
                f"{sym.kind} `{sym.name}` ({file.path}:{sym.start_line})"
            )
    return modules


def _build_module_dependency_edges(
    dependencies: list[Dependency],
    symbol_to_file: dict[UUID, UUID],
    file_to_module: dict[UUID, str],
) -> list[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for dep in dependencies:
        src_file = symbol_to_file.get(dep.source_symbol_id)
        tgt_file = symbol_to_file.get(dep.target_symbol_id)
        if not src_file or not tgt_file:
            continue
        src_module = file_to_module.get(src_file)
        tgt_module = file_to_module.get(tgt_file)
        if src_module and tgt_module and src_module != tgt_module:
            edges.add((src_module, tgt_module))
    return list(edges)


def _build_prompt(
    repo_name: str,
    total_files: int,
    modules: dict[str, list[str]],
    edges: list[tuple[str, str]],
) -> str:
    lines = [
        f"You are analyzing a software repository called '{repo_name}'.",
        f"It contains {total_files} source files organized into {len(modules)} top-level modules.",
        "",
        "## Module Breakdown",
    ]

    for module, syms in sorted(modules.items()):
        preview = syms[:10]
        lines.append(f"\n### {module}/")
        for s in preview:
            lines.append(f"  - {s}")
        if len(syms) > 10:
            lines.append(f"  ... and {len(syms) - 10} more")

    if edges:
        lines += [
            "",
            "## Module-Level Dependencies",
        ]
        for src, tgt in sorted(edges):
            lines.append(f"  - {src}/ → {tgt}/")

    lines += [
        "",
        "## Task",
        "Write a concise architecture summary (4-6 sentences) that covers:",
        "1. What this repository does at a high level",
        "2. How the modules are structured and what each does",
        "3. The key data/control flow between modules",
        "4. Any notable architectural patterns (layered, event-driven, pipeline, etc.)",
        "",
        "Be specific — use the actual module and symbol names above. Do not speculate beyond what the structure shows.",
    ]

    return "\n".join(lines)


def generate_repo_summary(repo_id: UUID, repo_name: str, db: Session) -> str:
    files_result = (
        db.execute(select(File).where(File.repository_id == repo_id)).scalars().all()
    )
    files_by_id: dict[UUID, File] = {f.id: f for f in files_result}

    file_ids = list(files_by_id.keys())
    if not file_ids:
        return "No source files were found in this repository."

    symbols_result = (
        db.execute(select(AstSymbol).where(AstSymbol.file_id.in_(file_ids)))
        .scalars()
        .all()
    )

    symbol_ids = [s.id for s in symbols_result]
    dependencies: list[Dependency] = []
    if symbol_ids:
        dependencies = list(
            db.execute(
                select(Dependency).where(Dependency.source_symbol_id.in_(symbol_ids))
            )
            .scalars()
            .all()
        )

    modules = _group_symbols_by_module(symbols_result, files_by_id)

    if not modules:
        return "The repository was parsed but no recognizable symbols (functions, classes) were found."

    symbol_to_file: dict[UUID, UUID] = {s.id: s.file_id for s in symbols_result}
    file_to_module: dict[UUID, str] = {}
    for file in files_result:
        parts = file.path.replace("\\", "/").split("/")
        module = parts[0] if len(parts) > 1 else "root"
        file_to_module[file.id] = module

    edges = _build_module_dependency_edges(dependencies, symbol_to_file, file_to_module)

    prompt = _build_prompt(repo_name, len(files_result), modules, edges)

    response = client.responses.create(
        model=settings.AI_MODEL,
        input=cast(
            ResponseInputParam,
            [
                {
                    "role": "system",
                    "content": "You are a senior software architect. Analyze repository structure and write clear, accurate architecture summaries.",
                },
                {"role": "user", "content": prompt},
            ],
        ),
        max_output_tokens=1000,
        reasoning={"effort": "low"},
    )

    content = response.output_text

    return content.strip() if content else "Summary could not be generated."
