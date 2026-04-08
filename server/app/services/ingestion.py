import logging
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import git
from app.models.ast_symbol import AstSymbol
from app.models.file import File
from app.models.repository import Repository
from app.services.parser import parse_file
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
        print(f"Processing {file_path}...")
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
    return processed
