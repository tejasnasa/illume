import logging
import uuid
from collections import defaultdict

from app.models import AstSymbol, Dependency, File
from app.services.import_resolver import load_ts_paths, load_workspace_map, resolve_import
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def resolve_dependencies(db: Session, repo_id: uuid.UUID, repo_root: str) -> int:
    files = db.query(File).filter(File.repository_id == repo_id).all()

    full_stem_map: dict[str, File] = {}
    short_stem_map: dict[str, list[File]] = {}

    for f in files:
        normalized = f.path.replace("\\", "/")
        stem = normalized.rsplit(".", 1)[0]
        full_stem_map[stem] = f

        parts = stem.split("/")
        if len(parts) > 1:
            alt_stem = "/".join(parts[1:])
            full_stem_map.setdefault(alt_stem, f)

        filename_stem = stem.split("/")[-1]
        short_stem_map.setdefault(filename_stem, []).append(f)

    index_map: dict[str, File] = {}
    for f in files:
        normalized = f.path.replace("\\", "/")
        stem = normalized.rsplit(".", 1)[0]
        if stem.split("/")[-1] in ("index", "__init__"):
            dir_path = "/".join(stem.split("/")[:-1])
            index_map[dir_path] = f

            dir_parts = dir_path.split("/")
            if len(dir_parts) > 1:
                alt_dir = "/".join(dir_parts[1:])
                index_map.setdefault(alt_dir, f)

    ts_paths = load_ts_paths(repo_root)
    workspace_map = load_workspace_map(repo_root)

    file_language: dict[uuid.UUID, str] = {f.id: (f.language or "") for f in files}

    file_id_to_path: dict[uuid.UUID, str] = {f.id: f.path for f in files}

    imports = (
        db.query(AstSymbol)
        .join(File, AstSymbol.file_id == File.id)
        .filter(File.repository_id == repo_id)
        .filter(AstSymbol.kind == "import")
        .all()
    )

    symbols = (
        db.query(AstSymbol)
        .join(File, AstSymbol.file_id == File.id)
        .filter(File.repository_id == repo_id)
        .filter(AstSymbol.kind.in_(["function", "class", "method"]))
        .all()
    )

    file_id_to_symbols: dict[uuid.UUID, list[AstSymbol]] = {}
    symbol_name_map: dict[tuple[uuid.UUID, str], AstSymbol] = {}
    for s in symbols:
        file_id_to_symbols.setdefault(s.file_id, []).append(s)
        if s.name:
            symbol_name_map[(s.file_id, s.name)] = s

    file_id_to_import_symbols: dict[uuid.UUID, list[AstSymbol]] = {}
    for imp_sym in imports:
        file_id_to_import_symbols.setdefault(imp_sym.file_id, []).append(imp_sym)

    deps_to_insert = []
    seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
    count = 0

    for imp in imports:
        if not imp.name or imp.name in ("<anonymous>", ""):
            continue

        language = file_language.get(imp.file_id, "")
        importing_file = file_id_to_path.get(imp.file_id)
        if not importing_file:
            continue

        resolved = resolve_import(
            language=language,
            import_name=imp.name,
            importing_file=importing_file,
            repo_root=repo_root,
            ts_paths=ts_paths,
            workspace_map=workspace_map,
        )

        if not resolved:
            continue

        matched_file: File | None = full_stem_map.get(resolved)

        if not matched_file:
            matched_file = index_map.get(resolved)

        if not matched_file:
            short_stem = resolved.split("/")[-1]
            candidates = short_stem_map.get(short_stem, [])
            if len(candidates) == 1:
                matched_file = candidates[0]
            elif len(candidates) > 1:
                lang = language.lower()
                if lang == "python":
                    filtered = [c for c in candidates if (c.language or "") == "python"]
                elif lang in ("javascript", "typescript", "tsx", "jsx"):
                    filtered = [
                        c
                        for c in candidates
                        if (c.language or "")
                        in ("javascript", "typescript", "tsx", "jsx")
                    ]
                else:
                    filtered = candidates

                if not filtered:
                    filtered = candidates

                if len(filtered) == 1:
                    matched_file = filtered[0]
                elif len(filtered) > 1:
                    best: File | None = None
                    best_score = 0
                    for c in filtered:
                        c_stem = c.path.replace("\\", "/").rsplit(".", 1)[0]
                        if c_stem.endswith(resolved):
                            matched_file = c
                            break
                        r_parts = resolved.split("/")
                        c_parts = c_stem.split("/")
                        score = 0
                        for rp, cp in zip(reversed(r_parts), reversed(c_parts)):
                            if rp == cp:
                                score += 1
                            else:
                                break
                        if score > best_score:
                            best_score = score
                            best = c
                    if not matched_file and best and best_score > 0:
                        matched_file = best

        if not matched_file or matched_file.id == imp.file_id:
            continue

        targets = file_id_to_symbols.get(matched_file.id, [])
        if not targets:
            barrel_imports = file_id_to_import_symbols.get(matched_file.id, [])
            if not barrel_imports:
                logger.debug(
                    "Dropping dependency edge to %s — no symbols at all",
                    matched_file.path,
                )
                continue

            edge = (imp.file_id, matched_file.id)
            if edge in seen:
                continue
            seen.add(edge)

            deps_to_insert.append(
                Dependency(
                    source_symbol_id=imp.id,
                    target_symbol_id=barrel_imports[0].id,
                    dep_type="imports",
                )
            )
            count += 1
            continue

        last_segment = imp.name.split("/")[-1]
        imported_name = last_segment.split(".")[-1].strip("_")
        target_symbol = symbol_name_map.get((matched_file.id, imported_name))
        if not target_symbol:
            logger.debug(
                "No symbol match for '%s' in %s, falling back to first symbol",
                imported_name,
                matched_file.path,
            )
            target_symbol = targets[0]

        edge = (imp.file_id, matched_file.id)
        if edge in seen:
            continue
        seen.add(edge)

        deps_to_insert.append(
            Dependency(
                source_symbol_id=imp.id,
                target_symbol_id=target_symbol.id,
                dep_type="imports",
            )
        )
        count += 1

    db.bulk_save_objects(deps_to_insert)
    db.commit()
    logger.info("Resolved %d internal dependencies for repo %s", count, repo_id)
    return count


def compute_fan_metrics(db: Session, repo_id: uuid.UUID) -> None:
    fan_in: dict[uuid.UUID, int] = defaultdict(int)
    fan_out: dict[uuid.UUID, int] = defaultdict(int)

    deps = (
        db.query(Dependency)
        .join(AstSymbol, Dependency.source_symbol_id == AstSymbol.id)
        .join(File, AstSymbol.file_id == File.id)
        .filter(File.repository_id == repo_id)
        .all()
    )

    symbol_to_file: dict[uuid.UUID, uuid.UUID] = {}
    files = db.query(File).filter(File.repository_id == repo_id).all()
    file_ids = {f.id for f in files}

    symbols = (
        db.query(AstSymbol)
        .join(File, AstSymbol.file_id == File.id)
        .filter(File.repository_id == repo_id)
        .all()
    )
    for s in symbols:
        symbol_to_file[s.id] = s.file_id

    for dep in deps:
        src_file = (
            symbol_to_file.get(dep.source_symbol_id) if dep.source_symbol_id else None
        )
        tgt_file = (
            symbol_to_file.get(dep.target_symbol_id) if dep.target_symbol_id else None
        )
        if (
            src_file
            and tgt_file
            and src_file in file_ids
            and tgt_file in file_ids
            and src_file != tgt_file
        ):
            fan_out[src_file] += 1
            fan_in[tgt_file] += 1

    for f in files:
        f.fan_in = fan_in[f.id]
        f.fan_out = fan_out[f.id]

    db.commit()
