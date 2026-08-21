import logging
from pathlib import Path

from app.models import AstSymbol, File, Repository
from app.services._publish import publish_log
from app.services.criticality import run_criticality_scoring
from app.services.dependency_resolver import compute_fan_metrics, resolve_dependencies
from app.services.embedder import generate_embeddings
from app.services.parser import parse_file
from app.services.stack_detector import SKIP_DIRS, SOURCE_EXTENSIONS, detect_entry_points, detect_stack
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _update_status(db: Session, redis_client, repo: Repository, status: str) -> None:
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
    import os
    source_files: list[Path] = []

    for root, dirs, files in os.walk(repo_root):
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
            continue

        relative_path = file_path.relative_to(repo_root).as_posix()

        db_file = File(
            repository_id=repo.id,
            path=relative_path,
            language=parsed.language,
            loc=parsed.loc,
        )
        db.add(db_file)
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
    _update_status(db, redis_client, repo, "embedding")
    publish_log(
        redis_client,
        str(repo.id),
        "embedding_started",
        "Starting embedding generation...",
    )

    def publish_progress(msg: str):
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
