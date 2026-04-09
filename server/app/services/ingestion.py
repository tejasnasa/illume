import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlparse

import git
from app.models import AstSymbol, Dependency, File, Repository
from app.models.health_metric import HealthMetric
from app.services.embedder import generate_embeddings
from app.services.health_scorer import compute_health_metrics
from app.services.parser import parse_file
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


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
            depth=1,
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

    return processed


def embed_repository_symbols(
    db: Session,
    redis_client,
    repo: Repository,
) -> int:
    _update_status(db, repo, "embedding")
    _publish_log(redis_client, str(repo.id), "Starting embedding generation...")

    def publish_log(msg: str):
        _publish_log(redis_client, str(repo.id), msg)

    count = generate_embeddings(
        repository_id=repo.id,
        db=db,
        publish_log=publish_log,
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
        if normalized.startswith("src/"):
            normalized = normalized[4:]
        normalized = normalized.rsplit(".", 1)[0]
        normalized_paths[normalized] = f

    imports = (
        db.query(AstSymbol)
        .join(File, AstSymbol.file_id == File.id)
        .filter(File.repository_id == repo_id)
        .filter(AstSymbol.kind == "import")
        .all()
    )

    for k in list(normalized_paths.keys())[:10]:
        print(f"  '{k}'")

    for imp in imports[:10]:
        module_path = imp.name.replace("\\", "/").lstrip("./")
        module_path = (
            module_path.rsplit(".", 1)[0]
            if "." in module_path.split("/")[-1]
            else module_path
        )

    symbols = (
        db.query(AstSymbol)
        .join(File, AstSymbol.file_id == File.id)
        .filter(File.repository_id == repo_id)
        .filter(AstSymbol.kind.in_(["function", "class", "method"]))
        .all()
    )
    file_id_to_symbols: dict = {}
    for s in symbols:
        file_id_to_symbols.setdefault(s.file_id, []).append(s)

    count = 0
    deps_to_insert = []

    for imp in imports:
        if imp.name in ("<anonymous>", ""):
            continue

        module_path = imp.name.replace("\\", "/").lstrip("./")
        module_path = (
            module_path.rsplit(".", 1)[0]
            if "." in module_path.split("/")[-1]
            else module_path
        )

        matched_file_ids = [
            f.id
            for norm_path, f in normalized_paths.items()
            if module_path in norm_path or norm_path in module_path
        ]

        for file_id in matched_file_ids[:3]:
            for target in file_id_to_symbols.get(file_id, [])[:10]:
                deps_to_insert.append(
                    Dependency(
                        source_symbol_id=imp.id,
                        target_symbol_id=target.id,
                        dep_type="imports",
                    )
                )
                count += 1

    print(f"file_id_to_symbols keys: {len(file_id_to_symbols)}")

    db.bulk_save_objects(deps_to_insert)
    db.commit()
    return count


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
