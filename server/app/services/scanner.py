"""Repository file processing pipeline.

Walks a cloned repository's source files, parses them into AST symbols,
persists files/symbols/dependencies to the database, computes fan metrics,
detects the tech stack, and generates embeddings. Criticality scoring is no
longer invoked here -- ``ingest_repository`` calls ``run_criticality_scoring``
once git history has populated the columns it depends on
(``git_last_modified``, ``has_tests``).

Memory shape (Phase B): rather than committing every file individually -- which
keeps one ORM instance per pending row in the session's identity map -- the loop
collects *plain dict rows* and emits them in batches via
``db.execute(insert(...))``. Each batch is committed before the next is built,
so the live set of pending rows is bounded by the batch size rather than by
the whole file count. UUIDs are assigned client-side with ``uuid4()`` so the
symbols batch can reference its files without a round-trip to read back their
server-assigned ids.
"""

import logging
import uuid
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import AstSymbol, File, Repository
from app.services._publish import publish_log
from app.services._stage_timer import stage
from app.services.dependency_resolver import compute_fan_metrics, resolve_dependencies
from app.services.embedder import generate_embeddings
from app.services.parser import parse_file
from app.services.stack_detector import (
    SKIP_DIRS,
    SOURCE_EXTENSIONS,
    detect_entry_points,
    detect_stack,
)

logger = logging.getLogger(__name__)

# Emit one batched insert + commit every this many files. Chosen large enough
# that the per-batch overhead is negligible, small enough that a crash leaves
# at most a few hundred files of duplicate work. The flush-per-file path that
# preceded this code capped pending objects at roughly one file's symbols, so
# raising the cap this high makes peak memory *worse* if the rows still carry
# per-instance overhead -- which is exactly why the loop now builds plain dict
# rows instead of ORM instances.
FILE_BATCH_SIZE = 500


def _update_status(db: Session, redis_client, repo: Repository, status: str) -> None:
    """Persist a new repo status and broadcast it over the log stream."""
    repo.status = status
    db.commit()
    publish_log(
        redis_client,
        str(repo.id),
        "status_update",
        f"Status changed to {status}",
        status=status,
    )


def walk_source_files(repo_root: Path) -> list[Path]:
    """Recursively collect source files under ``repo_root``.

    Skips vendored/generated directories (see ``SKIP_DIRS``) and keeps only
    files whose extension is in ``SOURCE_EXTENSIONS``.

    Args:
        repo_root: Root directory of the cloned repository.

    Returns:
        List of absolute paths to parseable source files.
    """
    import os

    source_files: list[Path] = []

    for root, dirs, files in os.walk(repo_root):
        # Mutating dirs in-place prunes the walk from descending into skipped dirs.
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        for filename in files:
            filepath = Path(root) / filename
            if filepath.suffix in SOURCE_EXTENSIONS:
                source_files.append(filepath)

    return source_files


def _flush_files(
    db: Session,
    repository_id: uuid.UUID,
    file_rows: list[dict],
) -> None:
    """Batched file insert.

    Rows are plain dicts (no ORM instance, no ``InstanceState``), so the
    session's identity map stays empty and a long batch does not pin every
    row's overhead. ``ON CONFLICT DO NOTHING`` makes a re-run of the same
    parse safe: the row already exists, ``RETURNING`` is empty for it, and
    a follow-up SELECT picks up its id.
    """
    if not file_rows:
        return
    db.execute(
        pg_insert(File)
        .values(file_rows)
        .on_conflict_do_nothing(index_elements=["repository_id", "path"])
    )


def _flush_symbols(db: Session, symbol_rows: list[dict]) -> None:
    """Batched symbol insert.

    All rows in one batch must reference files committed in the matching
    file batch -- the parser assigns the parent file's UUID by reading it
    from ``files_in_batch`` rather than asking the database, which is why
    ``File.id`` can keep its ``server_default`` for callers that still rely
    on it (factories, raw SQL).
    """
    if not symbol_rows:
        return
    db.execute(pg_insert(AstSymbol).values(symbol_rows))


def process_repository_files(
    db: Session,
    redis_client,
    repo: Repository,
    repo_root: Path,
) -> int:
    """Parse all source files in a repository and persist the analysis results.

    Runs the indexing pipeline: parses each file into AST symbols, stores files
    and symbols in the database, resolves inter-file dependencies, computes
    fan-in/fan-out metrics, and detects the repository's stack and entry points.

    Note: criticality scoring is intentionally *not* performed here -- it
    depends on ``File.git_last_modified`` and ``File.has_tests``, which are
    populated by ``analyze_git_history`` after parsing. ``ingest_repository``
    calls :func:`run_criticality_scoring` separately once that data exists.

    Args:
        db: Database session used for all persistence.
        redis_client: Redis client for publishing progress logs.
        repo: Repository record being indexed (updated with detected stack).
        repo_root: Root directory of the cloned repository on disk.

    Returns:
        Number of source files successfully parsed and stored.
    """
    _update_status(db, redis_client, repo, "parsing")
    publish_log(redis_client, str(repo.id), "parsing_started", "Starting file analysis...")
    db.query(File).filter(File.repository_id == repo.id).delete()
    db.commit()

    source_files = walk_source_files(repo_root)
    total = len(source_files)
    publish_log(redis_client, str(repo.id), "file_discovery", f"Found {total} source files.")

    processed = 0
    # File rows pending insertion; flushed every ``FILE_BATCH_SIZE`` files.
    file_batch: list[dict] = []
    # Symbol rows pending insertion; flushed alongside the file batch that owns
    # them so the FK targets exist when the symbols go in.
    symbol_batch: list[dict] = []
    # Local id assigned by the parser; consumed by the symbol flush and then
    # discarded. Keyed by file path so the symbol builder can find the parent.
    file_id_for_path: dict[str, uuid.UUID] = {}

    # Rate-limited progress: publish every N files plus the final one. The
    # previous per-file publish drove the client to re-render an unbounded
    # list of log frames for every file in a 10k-file repo.
    publish_every = max(50, total // 20) if total else 1
    last_publish_at = 0

    with stage("parse"):
        for file_path in source_files:
            parsed = parse_file(file_path)
            if not parsed:
                # Unparseable or unsupported file; skip rather than abort the run.
                continue

            relative_path = file_path.relative_to(repo_root).as_posix()

            # Client-assigned id so the symbol batch can reference it without a
            # round-trip after the file flush.
            new_file_id = uuid.uuid4()
            file_id_for_path[relative_path] = new_file_id

            file_batch.append(
                {
                    "id": new_file_id,
                    "repository_id": repo.id,
                    "path": relative_path,
                    "language": parsed.language,
                    "loc": parsed.loc,
                }
            )

            for symbol in parsed.symbols:
                symbol_batch.append(
                    {
                        "file_id": new_file_id,
                        "kind": symbol.kind,
                        "name": symbol.name,
                        "start_line": symbol.start_line,
                        "end_line": symbol.end_line,
                        "source_code": symbol.source_code,
                        "cyclomatic_complexity": symbol.cyclomatic_complexity,
                        "docstring": symbol.docstring,
                    }
                )

            processed += 1

            if len(file_batch) >= FILE_BATCH_SIZE:
                # Files before symbols: the FK on ast_symbols.file_id requires
                # the parent file row to exist.
                _flush_files(db, repo.id, file_batch)
                _flush_symbols(db, symbol_batch)
                db.commit()
                file_batch = []
                symbol_batch = []
                # ``file_id_for_path`` is only used inside a single batch, so
                # drop it as soon as the matching flush has happened. Keeping
                # it across the whole run would replay every prior path's
                # UUID and grow without bound.
                file_id_for_path = {}

            if processed - last_publish_at >= publish_every or processed == total:
                publish_log(
                    redis_client,
                    str(repo.id),
                    "file_processed",
                    f"{processed}/{total} files indexed",
                )
                last_publish_at = processed

        # Final flush of whatever the last partial batch holds.
        if file_batch or symbol_batch:
            _flush_files(db, repo.id, file_batch)
            _flush_symbols(db, symbol_batch)
            db.commit()
            file_batch = []
            symbol_batch = []
            file_id_for_path = {}

    publish_log(
        redis_client,
        str(repo.id),
        "db_storage_complete",
        f"Stored {processed} files in DB.",
    )

    with stage("resolve_dependencies"):
        dep_count = resolve_dependencies(db, repo.id, str(repo_root))
    publish_log(
        redis_client,
        str(repo.id),
        "deps_resolved",
        f"Resolved {dep_count} dependencies.",
    )

    publish_log(
        redis_client,
        str(repo.id),
        "metrics_started",
        "Computing fan-in/fan-out metrics...",
    )
    with stage("compute_fan_metrics"):
        compute_fan_metrics(db, repo.id)

    with stage("detect_stack"):
        repo.detected_stack = detect_stack(repo_root)
        repo.entry_points = detect_entry_points(repo_root)

    db.commit()
    publish_log(
        redis_client,
        str(repo.id),
        "stack_detected",
        f"Stack detected: {repo.detected_stack.get('languages', [])}",
    )

    return processed


def embed_repository_symbols(
    db: Session,
    redis_client,
    repo: Repository,
    readme_content: str | None = None,
) -> int:
    """Generate vector embeddings for a repository's indexed symbols.

    Args:
        db: Database session used by the embedder.
        redis_client: Redis client for publishing progress logs.
        repo: Repository record whose symbols should be embedded.
        readme_content: Optional README text included as extra context for
            embedding generation.

    Returns:
        Number of embedding vectors stored.
    """
    _update_status(db, redis_client, repo, "embedding")
    publish_log(
        redis_client,
        str(repo.id),
        "embedding_started",
        "Starting embedding generation...",
    )

    def publish_progress(msg: str):
        """Forward embedder messages to the repo's log stream."""
        publish_log(redis_client, str(repo.id), "embedding_progress", msg)

    with stage("generate_embeddings"):
        count = generate_embeddings(
            repository_id=repo.id,
            db=db,
            publish_log=publish_progress,
            readme_content=readme_content,
        )

    publish_log(
        redis_client,
        str(repo.id),
        "embedding_complete",
        f"Embedding complete — {count} vectors stored.",
    )
    return count
