"""Repository file processing pipeline.

Walks a cloned repository's source files, parses them into AST symbols,
persists files/symbols/dependencies to the database, computes fan metrics and
criticality scores, detects the tech stack, and generates embeddings.
"""

import logging

from sqlalchemy.orm import Session

from app.models import AstSymbol, File, Repository
from app.services._publish import publish_log
from app.services.criticality import run_criticality_scoring
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


def process_repository_files(
    db: Session,
    redis_client,
    repo: Repository,
    repo_root: Path,
) -> int:
    """Parse all source files in a repository and persist the analysis results.

    Runs the full indexing pipeline: parses each file into AST symbols, stores
    files and symbols in the database, resolves inter-file dependencies,
    computes fan-in/fan-out metrics and criticality scores, and detects the
    repository's stack and entry points. Progress is published via Redis logs.

    Args:
        db: Database session used for all persistence.
        redis_client: Redis client for publishing progress logs.
        repo: Repository record being indexed (updated with detected stack).
        repo_root: Root directory of the cloned repository on disk.

    Returns:
        Number of source files successfully parsed and stored.
    """
    _update_status(db, redis_client, repo, "parsing")
    publish_log(
        redis_client, str(repo.id), "parsing_started", "Starting file analysis..."
    )

    source_files = walk_source_files(repo_root)
    total = len(source_files)
    publish_log(
        redis_client, str(repo.id), "file_discovery", f"Found {total} source files."
    )

    processed = 0

    for file_path in source_files:
        parsed = parse_file(file_path)
        if not parsed:
            # Unparseable or unsupported file; skip rather than abort the run.
            continue

        relative_path = file_path.relative_to(repo_root).as_posix()

        db_file = File(
            repository_id=repo.id,
            path=relative_path,
            language=parsed.language,
            loc=parsed.loc,
        )
        db.add(db_file)
        # Flush now so db_file.id exists for the symbol rows below.
        db.flush()

        for symbol in parsed.symbols:
            db_symbol = AstSymbol(
                file_id=db_file.id,
                kind=symbol.kind,
                name=symbol.name,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                source_code=symbol.source_code,
                cyclomatic_complexity=symbol.cyclomatic_complexity,
            )
            db.add(db_symbol)

        processed += 1
        publish_log(
            redis_client,
            str(repo.id),
            "file_processed",
            f"{relative_path} ({parsed.loc} LOC, {len(parsed.symbols)} symbols)",
        )

    db.commit()
    publish_log(
        redis_client,
        str(repo.id),
        "db_storage_complete",
        f"Stored {processed} files in DB.",
    )

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
    compute_fan_metrics(db, repo.id)

    publish_log(
        redis_client, str(repo.id), "criticality_started", "Scoring file criticality..."
    )
    run_criticality_scoring(db, repo.id)

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
