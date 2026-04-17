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

    repo.detected_stack = detect_stack(repo_root)
    repo.entry_points = detect_entry_points(repo_root)

    db.commit()
    _publish_log(
        redis_client,
        str(repo.id),
        f"Stack detected: {repo.detected_stack.get('languages', [])}",
    )

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


def detect_stack(repo_root: Path) -> dict:
    import json

    SKIP_DIRS = {
        "node_modules",
        ".git",
        ".next",
        "dist",
        "build",
        "__pycache__",
        ".venv",
        "venv",
        "target",
        "bin",
        "obj",
    }

    languages: set[str] = set()
    frameworks: set[str] = set()
    databases: set[str] = set()
    ci_cd: set[str] = set()

    ext_map = {
        ".py": "Python",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".go": "Go",
        ".rs": "Rust",
        ".java": "Java",
        ".cs": "C#",
        ".rb": "Ruby",
        ".php": "PHP",
        ".cpp": "C++",
        ".c": "C",
        ".kt": "Kotlin",
        ".swift": "Swift",
    }

    all_files = [
        f
        for f in repo_root.rglob("*")
        if not any(skip in f.parts for skip in SKIP_DIRS)
    ]

    for f in all_files:
        if f.suffix in ext_map:
            languages.add(ext_map[f.suffix])

    for f in all_files:
        if f.name == "package.json":
            try:
                data = json.loads(f.read_text())
                deps = {
                    **data.get("dependencies", {}),
                    **data.get("devDependencies", {}),
                }

                js_fw = {
                    "next": "Next.js",
                    "react": "React",
                    "vue": "Vue",
                    "svelte": "Svelte",
                    "express": "Express",
                    "@nestjs/core": "NestJS",
                    "angular": "Angular",
                }

                js_db = {
                    "mongoose": "MongoDB",
                    "pg": "PostgreSQL",
                    "mysql": "MySQL",
                    "sqlite3": "SQLite",
                    "redis": "Redis",
                    "ioredis": "Redis",
                }

                for k, v in js_fw.items():
                    if k in deps:
                        frameworks.add(v)

                for k, v in js_db.items():
                    if k in deps:
                        databases.add(v)

            except Exception:
                pass

    for f in all_files:
        if f.suffix == ".py":
            try:
                text = f.read_text().lower()

                if "fastapi" in text:
                    frameworks.add("FastAPI")
                if "django" in text:
                    frameworks.add("Django")
                if "flask" in text:
                    frameworks.add("Flask")

                if "sqlalchemy" in text:
                    databases.add("SQLAlchemy")
                if "psycopg" in text:
                    databases.add("PostgreSQL")
                if "pymongo" in text:
                    databases.add("MongoDB")
                if "redis" in text:
                    databases.add("Redis")

            except Exception:
                pass

    for f in all_files:
        name = f.name.lower()

        if name == "pom.xml":
            try:
                if "spring-boot" in f.read_text(errors="ignore").lower():
                    frameworks.add("Spring Boot")
            except Exception:
                pass

        if name in {"build.gradle", "build.gradle.kts"}:
            try:
                if "spring" in f.read_text(errors="ignore").lower():
                    frameworks.add("Spring")
            except Exception:
                pass

    go_mod = repo_root / "go.mod"
    if go_mod.exists():
        text = go_mod.read_text().lower()
        if "gin-gonic" in text:
            frameworks.add("Gin")
        if "echo" in text:
            frameworks.add("Echo")

    cargo = repo_root / "Cargo.toml"
    if cargo.exists():
        text = cargo.read_text().lower()
        if "actix-web" in text:
            frameworks.add("Actix")
        if "rocket" in text:
            frameworks.add("Rocket")
        if "diesel" in text:
            databases.add("PostgreSQL")

    gemfile = repo_root / "Gemfile"
    if gemfile.exists():
        text = gemfile.read_text().lower()
        if "rails" in text:
            frameworks.add("Ruby on Rails")

    composer = repo_root / "composer.json"
    if composer.exists():
        try:
            data = json.loads(composer.read_text())
            deps = data.get("require", {})
            if "laravel/framework" in deps:
                frameworks.add("Laravel")
            if "symfony" in str(deps):
                frameworks.add("Symfony")
        except Exception:
            pass

    if (repo_root / "manage.py").exists():
        frameworks.add("Django")

    if any((repo_root / f).exists() for f in ["next.config.js", "next.config.ts"]):
        frameworks.add("Next.js")

    if (repo_root / "apps").exists() and (repo_root / "packages").exists():
        frameworks.add("Monorepo")

    for f in all_files:
        name = f.name.lower()
        path = str(f).lower()

        if "socket" in name or "ws" in name:
            frameworks.add("WebSockets")
            frameworks.add("Real-time System")

        if "prisma" in path:
            frameworks.add("Prisma ORM")
            databases.add("PostgreSQL")

        if "redis" in path:
            databases.add("Redis")
            frameworks.add("Caching Layer")

    if (repo_root / ".github" / "workflows").exists():
        ci_cd.add("GitHub Actions")
    if (repo_root / ".gitlab-ci.yml").exists():
        ci_cd.add("GitLab CI")
    if (repo_root / "Jenkinsfile").exists():
        ci_cd.add("Jenkins")
    if (repo_root / "Dockerfile").exists():
        ci_cd.add("Docker")

    return {
        "languages": sorted(languages),
        "frameworks": sorted(frameworks),
        "databases": sorted(databases),
        "ci_cd": sorted(ci_cd),
    }


def detect_entry_points(repo_root: Path) -> list[str]:
    SKIP_DIRS = {
        "node_modules",
        ".git",
        ".next",
        "dist",
        "build",
        "__pycache__",
        ".venv",
        "venv",
        "target",
        "bin",
        "obj",
    }

    entry_points: set[str] = set()

    all_files = [
        f
        for f in repo_root.rglob("*")
        if f.is_file() and not any(skip in f.parts for skip in SKIP_DIRS)
    ]

    def rel(f: Path) -> str:
        return str(f.relative_to(repo_root)).replace("\\", "/")

    for f in all_files:
        name = f.name.lower()
        path = rel(f)

        if name in {
            "main.py",
            "app.py",
            "server.py",
            "run.py",
            "main.go",
            "main.rs",
            "main.java",
            "main.kt",
            "program.cs",
            "app.rb",
        }:
            entry_points.add(path)

        if name in {
            "index.js",
            "server.js",
            "main.js",
            "index.ts",
            "server.ts",
            "main.ts",
        }:
            if "src" not in path or "server" in path or "api" in path:
                entry_points.add(path)

        if name in {"app.tsx", "app.jsx"} and "src" in path:
            entry_points.add(path)

        if name in {"page.tsx", "page.jsx"} and "app" in path:
            entry_points.add(path)

        elif name in {"index.tsx", "index.jsx"} and "pages" in path:
            entry_points.add(path)

        elif name in {"next.config.js", "next.config.ts"}:
            entry_points.add(path)

        if name in {"manage.py", "wsgi.py", "asgi.py"}:
            entry_points.add(path)

        if name in {"pom.xml", "build.gradle", "build.gradle.kts"}:
            entry_points.add(path)

        if name in {"cargo.toml", "go.mod", "gemfile", "composer.json"}:
            entry_points.add(path)

        if name == "dockerfile":
            entry_points.add(path)

    for f in all_files:
        if f.suffix not in {".py", ".js", ".ts", ".go", ".rs", ".java", ".cs"}:
            continue

        try:
            text = f.read_text(errors="ignore").lower()
        except Exception:
            continue

        path = rel(f)

        if 'if __name__ == "__main__"' in text:
            entry_points.add(path)

        if "uvicorn.run" in text or "fastapi(" in text:
            entry_points.add(path)

        if "app.listen" in text or "express()" in text:
            entry_points.add(path)

        if "createServer" in text or "http.createServer" in text:
            entry_points.add(path)

        if "func main()" in text:
            entry_points.add(path)

        if "fn main()" in text:
            entry_points.add(path)

        if "public static void main" in text:
            entry_points.add(path)

        if "webapplication.createbuilder" in text:
            entry_points.add(path)

    return sorted(entry_points)
