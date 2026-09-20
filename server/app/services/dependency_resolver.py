"""Internal dependency resolution between repository files.

Resolves parsed import symbols to concrete target files and inserts Dependency
edges, then computes file-level fan-in/fan-out metrics from those edges.

Memory shape (Phase B): the resolver used to load every import symbol and every
embeddable symbol into ORM instances and hold them simultaneously. Two stages
both held full tables -- the import symbols driving edge construction, and the
definitions that the edges target -- so peak memory was at least
``len(imports) + len(definitions)`` ORM rows. The functions below now read only
the columns they need (a UUID plus a name plus a kind plus a path) and never
materialise ORM rows. Edges are batched into the database rather than buffered
as a Python list until the end.
"""

import logging
import uuid
from collections import defaultdict
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import AstSymbol, Dependency, File
from app.services.import_resolver import (
    load_ts_paths,
    load_workspace_map,
    resolve_import,
)

logger = logging.getLogger(__name__)

# Batch size for the dependency edge inserts. SQLAlchemy paginates the
# ``insertmanyvalues`` for us at this size (see ``insertmanyvalues_page_size``);
# the number here is just a memory-hint, not a bind-parameter workaround.
DEPENDENCY_BATCH_SIZE = 1000


def _build_stem_indexes(
    files: Iterable[tuple[uuid.UUID, str, str]],
) -> tuple[dict[str, uuid.UUID], dict[str, list[uuid.UUID]], dict[str, uuid.UUID]]:
    """Build path-stem lookup indexes for fast import-to-file matching.

    Accepts plain ``(file_id, path, language)`` tuples rather than ``File``
    ORM rows so callers that have already projected the relevant columns do
    not have to round-trip back through the ORM to populate the maps. Each
    tuple is sufficient because nothing in the matcher reads anything else
    off the ``File``.

    Args:
        files: Iterable of ``(file_id, path, language)`` triples for every
            file in the repository.

    Returns:
        A tuple of ``(full_stem_map, short_stem_map, index_map)``:

        - ``full_stem_map``: path stem (extension stripped) -> file_id,
          including a variant with the top-level directory stripped to
          tolerate unknown src-root prefixes (``src/``, ``lib/``, ``app/``).
        - ``short_stem_map``: bare filename stem -> all file_ids with that name.
        - ``index_map``: package directory -> its ``index``/``__init__``
          entry-point file_id.
    """
    full_stem_map: dict[str, uuid.UUID] = {}
    short_stem_map: dict[str, list[uuid.UUID]] = {}
    index_map: dict[str, uuid.UUID] = {}

    for file_id, path, _language in files:
        normalized = path.replace("\\", "/")
        stem = normalized.rsplit(".", 1)[0]
        full_stem_map[stem] = file_id

        # Also index without the top-level dir so imports written relative to
        # an unknown source root still match.
        parts = stem.split("/")
        if len(parts) > 1:
            alt_stem = "/".join(parts[1:])
            full_stem_map.setdefault(alt_stem, file_id)

        filename_stem = stem.split("/")[-1]
        short_stem_map.setdefault(filename_stem, []).append(file_id)

        if filename_stem in ("index", "__init__"):
            # `import pkg` resolves to pkg/index.* or pkg/__init__.*, so map
            # each package directory to its entry-point file.
            dir_path = "/".join(stem.split("/")[:-1])
            index_map[dir_path] = file_id

            dir_parts = dir_path.split("/")
            if len(dir_parts) > 1:
                alt_dir = "/".join(dir_parts[1:])
                index_map.setdefault(alt_dir, file_id)

    return full_stem_map, short_stem_map, index_map


def _match_file(
    resolved: str,
    language: str,
    full_stem_map: dict[str, uuid.UUID],
    short_stem_map: dict[str, list[uuid.UUID]],
    index_map: dict[str, uuid.UUID],
    *,
    path_by_id: dict[uuid.UUID, str],
    language_by_id: dict[uuid.UUID, str],
) -> uuid.UUID | None:
    """Match a resolved import specifier to a known file id.

    Applies the multi-strategy fallback chain documented on
    :func:`resolve_dependencies`: exact stem, package index, unique short
    stem, language-family narrowing, then suffix/segment scoring.

    Args:
        resolved: Repo-relative path stem produced by ``resolve_import``.
        language: Language of the file containing the import.
        full_stem_map: Exact-stem index from :func:`_build_stem_indexes`.
        short_stem_map: Filename-only index from :func:`_build_stem_indexes`.
        index_map: Package-entry index from :func:`_build_stem_indexes`.
        path_by_id: Lookup of file path by id, used only by disambiguation.
        language_by_id: Lookup of file language by id, used only by disambiguation.

    Returns:
        The matched file id, or None if no strategy succeeds.
    """
    matched_id: uuid.UUID | None = full_stem_map.get(resolved)

    if not matched_id:
        matched_id = index_map.get(resolved)

    if not matched_id:
        short_stem = resolved.split("/")[-1]
        candidates = short_stem_map.get(short_stem, [])
        if len(candidates) == 1:
            matched_id = candidates[0]
        elif len(candidates) > 1:
            matched_id = _disambiguate_candidates(
                candidates, language, resolved, path_by_id, language_by_id
            )

    return matched_id


def _disambiguate_candidates(
    candidates: list[uuid.UUID],
    language: str,
    resolved: str,
    path_by_id: dict[uuid.UUID, str],
    language_by_id: dict[uuid.UUID, str],
) -> uuid.UUID | None:
    """Pick the best file among several sharing the same filename.

    Narrows candidates to the importer's language family first; if several
    remain, prefers an exact suffix match on the resolved specifier, then the
    candidate with the longest reversed path-segment overlap.

    Args:
        candidates: File ids whose filename stem equals the resolved basename.
        language: Language of the importing file.
        resolved: The resolved import specifier being matched.
        path_by_id: Lookup of file path by id, used to score candidates.
        language_by_id: Lookup of file language by id, used to filter candidates.

    Returns:
        The best-matching file id, or None if no candidate stands out.
    """
    lang = language.lower()
    # Narrow ambiguous same-named candidates to the importer's language
    # family (a.py vs a.ts) before scoring.
    if lang == "python":
        filtered = [cid for cid in candidates if language_by_id.get(cid, "") == "python"]
    elif lang in ("javascript", "typescript", "tsx", "jsx"):
        filtered = [
            cid
            for cid in candidates
            if language_by_id.get(cid, "") in ("javascript", "typescript", "tsx", "jsx")
        ]
    else:
        filtered = candidates

    if not filtered:
        filtered = candidates

    if len(filtered) == 1:
        return filtered[0]

    # Prefer exact suffix match; otherwise score candidates by how many
    # trailing path segments overlap the specifier.
    best: uuid.UUID | None = None
    best_score = 0
    for cid in filtered:
        c_path = path_by_id.get(cid, "")
        c_stem = c_path.replace("\\", "/").rsplit(".", 1)[0]
        if c_stem.endswith(resolved):
            return cid
        # Compare path segments from the end: more shared trailing segments
        # = deeper structural similarity.
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
            best = cid

    return best if best_score > 0 else None


def resolve_dependencies(db: Session, repo_id: uuid.UUID, repo_root: str) -> int:
    """Resolve all import symbols for a repository into Dependency edges.

    For each stored ``import`` symbol, the import specifier is resolved to a
    candidate path (language-aware, via ``resolve_import``), then matched to a
    known file using a multi-strategy fallback chain:

    1. **Full stem map** — exact match on the resolved path's stem (extension
       stripped), including a variant with the top-level directory stripped to
       tolerate unknown src-root prefixes.
    2. **Index map** — the resolved stem refers to a package directory whose
       entry point is an ``index``/``__init__`` file.
    3. **Short stem** — match on filename alone; only accepted when exactly one
       candidate exists.
    4. **Language filter** — when several candidates share a filename, narrow
       them to files matching the importer's language family (Python vs JS/TS).
    5. **Suffix scoring** — among remaining candidates, prefer one whose full
       path ends with the resolved specifier; otherwise pick the candidate with
       the longest reversed path-segment overlap.

    Each edge points from the import symbol to a concrete symbol in the target
    file (matched by imported name, falling back to the first symbol). Imports
    into files with no definitions but existing imports are treated as barrel
    re-exports and linked to their first import symbol. Duplicate (source,
    target) edges and self-imports are skipped.

    Args:
        db: Database session used to query files/symbols and insert edges.
        repo_id: ID of the repository being processed.
        repo_root: Root directory of the cloned repository on disk (used for
            tsconfig paths and workspace package maps).

    Returns:
        Number of dependency edges inserted.
    """
    # Project (id, path, language) -- the columns the matcher actually reads.
    # Avoiding `select(File)` keeps ORM instances out of the session entirely,
    # which is what bounds the resolver's peak memory.
    file_rows = db.execute(
        select(File.id, File.path, File.language).where(File.repository_id == repo_id)
    ).all()
    file_triples = [(row.id, row.path, row.language or "") for row in file_rows]
    file_id_to_path = {row.id: row.path for row in file_rows}
    language_by_id = {row.id: row.language or "" for row in file_rows}

    full_stem_map, short_stem_map, index_map = _build_stem_indexes(file_triples)

    ts_paths = load_ts_paths(repo_root)
    workspace_map = load_workspace_map(repo_root)

    # Imports: kind + name + file_id are all the resolver reads.
    imports = db.execute(
        select(AstSymbol.id, AstSymbol.file_id, AstSymbol.name)
        .join(File, AstSymbol.file_id == File.id)
        .filter(File.repository_id == repo_id)
        .filter(AstSymbol.kind == "import")
    ).all()

    # Embeddable definitions: name is matched against the imported symbol's
    # basename, and file_id groups them per parent file for the "first
    # symbol" fallback. Source_code is intentionally not loaded.
    definitions = db.execute(
        select(AstSymbol.id, AstSymbol.file_id, AstSymbol.name)
        .join(File, AstSymbol.file_id == File.id)
        .filter(File.repository_id == repo_id)
        .filter(AstSymbol.kind.in_(["function", "class", "method"]))
    ).all()

    # Group definitions per file so the barrel fallback can take the first.
    file_id_to_defs: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = {}
    for d_id, d_file_id, d_name in definitions:
        file_id_to_defs.setdefault(d_file_id, []).append((d_id, d_name or ""))

    # Names index: (file_id, name) -> definition id.
    symbol_name_map: dict[tuple[uuid.UUID, str], uuid.UUID] = {
        (d_file_id, d_name): d_id
        for d_file_id, defs in file_id_to_defs.items()
        for d_id, d_name in defs
        if d_name
    }

    # Barrel fallback needs the first import per file. Built only for files
    # that have no definitions (those are the only files that fall through).
    barrel_first_import: dict[uuid.UUID, uuid.UUID] = {}
    for imp_id, imp_file_id, _imp_name in imports:
        if imp_file_id in file_id_to_defs:
            continue
        barrel_first_import.setdefault(imp_file_id, imp_id)

    # Build the edge list as plain dicts and flush in batches. Holding every
    # edge as a Dependency ORM instance is what the previous code did, and it
    # is what this function is measured against.
    pending: list[dict] = []
    seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
    count = 0

    def _flush() -> None:
        nonlocal pending
        if not pending:
            return
        db.execute(pg_insert(Dependency).values(pending))
        db.commit()
        pending = []

    for imp_id, imp_file_id, imp_name in imports:
        if not imp_name or imp_name in ("<anonymous>", ""):
            continue

        language = language_by_id.get(imp_file_id, "")
        importing_file = file_id_to_path.get(imp_file_id)
        if not importing_file:
            continue

        resolved = resolve_import(
            language=language,
            import_name=imp_name,
            importing_file=importing_file,
            repo_root=repo_root,
            ts_paths=ts_paths,
            workspace_map=workspace_map,
        )

        if not resolved:
            continue

        matched_id = _match_file(
            resolved,
            language,
            full_stem_map,
            short_stem_map,
            index_map,
            path_by_id=file_id_to_path,
            language_by_id=language_by_id,
        )

        if not matched_id or matched_id == imp_file_id:
            continue

        targets = file_id_to_defs.get(matched_id, [])
        if not targets:
            # No definitions but existing imports => barrel/re-export file;
            # link to its first import symbol so the edge isn't lost.
            barrel_target = barrel_first_import.get(matched_id)
            if not barrel_target:
                logger.debug(
                    "Dropping dependency edge to %s -- no symbols at all",
                    file_id_to_path.get(matched_id),
                )
                continue

            edge = (imp_file_id, matched_id)
            if edge in seen:
                continue
            seen.add(edge)

            pending.append(
                {
                    "source_symbol_id": imp_id,
                    "target_symbol_id": barrel_target,
                    "dep_type": "imports",
                }
            )
            count += 1
            if len(pending) >= DEPENDENCY_BATCH_SIZE:
                _flush()
            continue

        last_segment = imp_name.split("/")[-1]
        # Strip module-path prefix and leading/trailing underscores so e.g.
        # "pkg/_helper.py" matches an import of "helper".
        imported_name = last_segment.split(".")[-1].strip("_")
        target_id = symbol_name_map.get((matched_id, imported_name))
        if not target_id:
            logger.debug(
                "No symbol match for '%s' in %s, falling back to first symbol",
                imported_name,
                file_id_to_path.get(matched_id),
            )
            target_id = targets[0][0]

        edge = (imp_file_id, matched_id)
        if edge in seen:
            continue
        seen.add(edge)

        pending.append(
            {
                "source_symbol_id": imp_id,
                "target_symbol_id": target_id,
                "dep_type": "imports",
            }
        )
        count += 1
        if len(pending) >= DEPENDENCY_BATCH_SIZE:
            _flush()

    _flush()
    logger.info("Resolved %d internal dependencies for repo %s", count, repo_id)
    return count


def compute_fan_metrics(db: Session, repo_id: uuid.UUID) -> None:
    """Compute per-file fan-in/fan-out counts from dependency edges.

    Args:
        db: Database session used to read dependencies and update files.
        repo_id: ID of the repository whose files should be scored.
    """
    fan_in: dict[uuid.UUID, int] = defaultdict(int)
    fan_out: dict[uuid.UUID, int] = defaultdict(int)

    # Two joins are unavoidable (Dependency -> AstSymbol -> File on each
    # side), but neither needs the AstSymbol columns other than its file_id.
    # Projecting only those keeps the result set to ``UUID, UUID`` rows
    # rather than full ORM symbols.
    src_file_id_col = AstSymbol.__table__.c.file_id
    target_symbol = AstSymbol.__table__.alias("tgt")
    target_file_id_col = target_symbol.c.file_id

    repo_file_ids = select(File.id).where(File.repository_id == repo_id)

    edges = db.execute(
        select(src_file_id_col.label("src_file"), target_file_id_col.label("tgt_file"))
        .select_from(Dependency)
        .join(AstSymbol, Dependency.source_symbol_id == AstSymbol.id)
        .join(target_symbol, Dependency.target_symbol_id == target_symbol.c.id)
        .where(src_file_id_col.in_(repo_file_ids))
        .where(target_file_id_col.in_(repo_file_ids))
    ).all()

    for edge in edges:
        src_file = edge.src_file
        tgt_file = edge.tgt_file
        if not src_file or not tgt_file or src_file == tgt_file:
            continue
        fan_out[src_file] += 1
        fan_in[tgt_file] += 1

    # Persist the counts in a single UPDATE per side. The previous code
    # mutated every File ORM row individually; doing so forces the session
    # to materialise each row, which is what we just avoided loading.
    from sqlalchemy import update

    if fan_in:
        db.execute(
            update(File),
            [
                {"id": file_id, "fan_in": count, "fan_out": fan_out.get(file_id, 0)}
                for file_id, count in fan_in.items()
            ],
        )
    # Files that only fan out (no inbound edges) were never written above;
    # update them now so fan_out is correct even when fan_in is empty.
    if fan_out:
        only_fan_out_ids = [fid for fid in fan_out if fid not in fan_in]
        if only_fan_out_ids:
            db.execute(
                update(File),
                [
                    {"id": file_id, "fan_in": 0, "fan_out": fan_out[file_id]}
                    for file_id in only_fan_out_ids
                ],
            )

    db.commit()
