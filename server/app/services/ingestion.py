import logging
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

import git
from app.models import AstSymbol, Dependency, File, HealthMetric, Repository
from app.services.embedder import generate_embeddings
from app.services.health_scorer import compute_health_metrics
from app.services.parser import parse_file
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


CRITICAL_PATH_PATTERNS = [
    r"config\.",
    r"database\.",
    r"middleware/",
    r"migrations/",
    r"auth\.",
    r"security\.",
    r"celery\.",
    r"main\.",
]


SOURCE_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".rb",
    ".cs",
    ".php",
    ".swift",
    ".kt",
}

SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    "coverage",
    ".pytest_cache",
    "alembic",
}


def _publish_log(redis_client, repo_id: str, message: str) -> None:
    channel = f"task:{repo_id}:logs"
    redis_client.publish(channel, message)
    logger.info("[%s] %s", repo_id, message)


def _update_status(db: Session, repo: Repository, status: str) -> None:
    repo.status = status
    db.commit()


def clone_repository(
    db: Session,
    redis_client,
    repo: Repository,
    github_access_token: str | None = None,
) -> Path:
    _update_status(db, repo, "cloning")
    _publish_log(redis_client, str(repo.id), "Cloning repository...")

    clone_url = _build_clone_url(repo.github_url, github_access_token)
    tmp_dir = tempfile.mkdtemp(prefix=f"illume_{repo.id}_")

    try:
        git.Repo.clone_from(
            clone_url,
            tmp_dir,
            single_branch=True,
        )
    except git.GitCommandError as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError(f"Git clone failed: {e.stderr.strip()}") from e

    _publish_log(redis_client, str(repo.id), "Clone complete.")
    return Path(tmp_dir)


def walk_source_files(repo_root: Path) -> list[Path]:
    source_files: list[Path] = []

    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        for filename in files:
            filepath = Path(root) / filename
            if filepath.suffix in SOURCE_EXTENSIONS:
                source_files.append(filepath)

    return source_files


def cleanup_clone(tmp_dir: Path) -> None:
    shutil.rmtree(tmp_dir, ignore_errors=True)


def _build_clone_url(github_url: str, github_access_token: str | None) -> str:
    # Inject the OAuth token into the clone URL for private repos like https://github.com/user/repo -> https://<token>@github.com/user/repo
    if not github_access_token:
        return github_url

    parsed = urlparse(github_url)
    return parsed._replace(netloc=f"{github_access_token}@{parsed.netloc}").geturl()


def process_repository_files(
    db: Session,
    redis_client,
    repo,
    repo_root: Path,
) -> int:
    _update_status(db, repo, "parsing")
    _publish_log(redis_client, str(repo.id), "Starting file analysis...")

    source_files = walk_source_files(repo_root)
    total = len(source_files)
    _publish_log(redis_client, str(repo.id), f"Found {total} source files.")

    processed = 0

    for file_path in source_files:
        parsed = parse_file(file_path)
        if not parsed:
            continue

        relative_path = str(file_path.relative_to(repo_root))

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
        _publish_log(
            redis_client,
            str(repo.id),
            f"{relative_path} ({parsed.loc} LOC, {len(parsed.symbols)} symbols)",
        )

    db.commit()
    _publish_log(redis_client, str(repo.id), f"Stored {processed} files in DB.")

    dep_count = resolve_dependencies(db, repo.id)
    _publish_log(redis_client, str(repo.id), f"Resolved {dep_count} dependencies.")

    _publish_log(redis_client, str(repo.id), "Computing fan-in/fan-out metrics...")
    compute_fan_metrics(db, repo.id)

    _publish_log(redis_client, str(repo.id), "Scoring file criticality...")
    run_criticality_scoring(db, repo.id)

    return processed


def embed_repository_symbols(
    db: Session,
    redis_client,
    repo: Repository,
    readme_content: str | None = None,
) -> int:
    _update_status(db, repo, "embedding")
    _publish_log(redis_client, str(repo.id), "Starting embedding generation...")

    def publish_log(msg: str):
        _publish_log(redis_client, str(repo.id), msg)

    count = generate_embeddings(
        repository_id=repo.id,
        db=db,
        publish_log=publish_log,
        readme_content=readme_content,
    )

    _publish_log(
        redis_client, str(repo.id), f"Embedding complete — {count} vectors stored."
    )
    return count


def resolve_dependencies(db: Session, repo_id: uuid.UUID) -> int:
    files = db.query(File).filter(File.repository_id == repo_id).all()

    normalized_paths: dict[str, File] = {}
    for f in files:
        normalized = f.path.replace("\\", "/")
        stem = normalized.rsplit(".", 1)[0]
        normalized_paths[stem] = f
        filename_stem = stem.split("/")[-1]
        normalized_paths.setdefault(filename_stem, f)

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
    for s in symbols:
        file_id_to_symbols.setdefault(s.file_id, []).append(s)

    deps_to_insert = []
    count = 0

    for imp in imports:
        if not imp.name or imp.name in ("<anonymous>", ""):
            continue

        module_path = imp.name.replace("\\", "/").replace(".", "/").lstrip("./").strip()

        for noise in (
            " as aioredis",
            " as ",
        ):
            if noise in module_path:
                module_path = module_path.split(noise)[0].strip()

        if not module_path:
            continue

        candidates = [
            module_path,
            module_path.split("/")[-1],
        ]

        matched_file: File | None = None
        for candidate in candidates:
            if candidate in normalized_paths:
                target_file = normalized_paths[candidate]
                if target_file.id != imp.file_id:
                    matched_file = target_file
                    break

        if not matched_file:
            continue

        targets = file_id_to_symbols.get(matched_file.id, [])
        if not targets:
            continue

        deps_to_insert.append(
            Dependency(
                source_symbol_id=imp.id,
                target_symbol_id=targets[0].id,
                dep_type="imports",
            )
        )
        count += 1

    db.bulk_save_objects(deps_to_insert)
    db.commit()
    logger.info("Resolved %d internal dependencies for repo %s", count, repo_id)
    return count


def compute_fan_metrics(db: Session, repo_id: uuid.UUID) -> None:
    from collections import defaultdict

    fan_in: dict[uuid.UUID, int] = defaultdict(int)
    fan_out: dict[uuid.UUID, int] = defaultdict(int)

    deps = db.query(Dependency).filter(Dependency.source_symbol_id.isnot(None)).all()

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


def score_repository_health(
    db: Session,
    redis_client,
    repo: Repository,
) -> int:
    _update_status(db, repo, "scoring")
    _publish_log(redis_client, str(repo.id), "Computing health metrics...")

    compute_health_metrics(repo.id, db)

    hotspot_count = (
        db.execute(
            select(HealthMetric).where(
                HealthMetric.repository_id == repo.id,
                HealthMetric.file_id.isnot(None),
            )
        )
        .scalars()
        .all()
    )
    hotspot_count = sum(
        1 for m in hotspot_count if m.breakdown and m.breakdown.get("is_hotspot")
    )

    _publish_log(
        redis_client,
        str(repo.id),
        f"Health scoring complete — {hotspot_count} hotspot(s) found.",
    )
    return hotspot_count


def _score_file(file) -> tuple[str, list[str]]:
    score = 0
    reasons: list[str] = []
    now = datetime.now(tz=timezone.utc)

    fan_in = file.fan_in or 0
    if fan_in >= 10:
        score += 3
        reasons.append(f"imported by {fan_in} files")
    elif fan_in >= 5:
        score += 1
        reasons.append(f"imported by {fan_in} files")

    if any(re.search(p, file.path) for p in CRITICAL_PATH_PATTERNS):
        score += 2
        reasons.append("core infrastructure file")

    if file.git_last_modified:
        last_modified = file.git_last_modified
        if last_modified.tzinfo is None:
            last_modified = last_modified.replace(tzinfo=timezone.utc)
        if (now - last_modified).days > 180:
            score += 1
            reasons.append("untouched for 6+ months")

    if not file.has_tests:
        score += 1
        reasons.append("no test coverage")

    if score >= 4:
        criticality = "critical"
    elif score >= 2:
        criticality = "caution"
    else:
        criticality = "safe"

    return criticality, reasons


def run_criticality_scoring(db: Session, repo_id: UUID) -> int:
    from app.models import File

    files = db.query(File).filter(File.repository_id == repo_id).all()

    for f in files:
        f.criticality, f.criticality_reasons = _score_file(f)

    db.commit()
    return len(files)
