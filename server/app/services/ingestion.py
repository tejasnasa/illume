import json
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
from app.models import AstSymbol, Dependency, File, Repository
from app.services.embedder import generate_embeddings
from app.services.import_resolver import (
    load_ts_paths,
    load_workspace_map,
    resolve_import,
)
from app.services.parser import parse_file
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
    "target",
    "bin",
    "obj",
}


def _publish_log(
    redis_client, repo_id: str, event: str, message: str, **kwargs
) -> None:
    channel = f"task:{repo_id}:logs"
    data = {
        "event": event,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **kwargs,
    }
    redis_client.publish(channel, json.dumps(data))
    logger.info("[%s] %s: %s", repo_id, event, message)


def _update_status(db: Session, redis_client, repo: Repository, status: str) -> None:
    repo.status = status
    db.commit()
    _publish_log(
        redis_client,
        str(repo.id),
        "status_update",
        f"Status changed to {status}",
        status=status,
    )


def clone_repository(
    db: Session,
    redis_client,
    repo: Repository,
    github_access_token: str | None = None,
) -> Path:
    _update_status(db, redis_client, repo, "cloning")
    _publish_log(redis_client, str(repo.id), "clone_started", "Cloning repository...")

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

    _publish_log(redis_client, str(repo.id), "clone_complete", "Clone complete.")
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
    _update_status(db, redis_client, repo, "parsing")
    _publish_log(
        redis_client, str(repo.id), "parsing_started", "Starting file analysis..."
    )

    source_files = walk_source_files(repo_root)
    total = len(source_files)
    _publish_log(
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
        _publish_log(
            redis_client,
            str(repo.id),
            "file_processed",
            f"{relative_path} ({parsed.loc} LOC, {len(parsed.symbols)} symbols)",
        )

    db.commit()
    _publish_log(
        redis_client,
        str(repo.id),
        "db_storage_complete",
        f"Stored {processed} files in DB.",
    )

    dep_count = resolve_dependencies(db, repo.id, str(repo_root))
    _publish_log(
        redis_client,
        str(repo.id),
        "deps_resolved",
        f"Resolved {dep_count} dependencies.",
    )

    _publish_log(
        redis_client,
        str(repo.id),
        "metrics_started",
        "Computing fan-in/fan-out metrics...",
    )
    compute_fan_metrics(db, repo.id)

    _publish_log(
        redis_client, str(repo.id), "criticality_started", "Scoring file criticality..."
    )
    run_criticality_scoring(db, repo.id)

    repo.detected_stack = detect_stack(repo_root)
    repo.entry_points = detect_entry_points(repo_root)

    db.commit()
    _publish_log(
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
    _publish_log(
        redis_client,
        str(repo.id),
        "embedding_started",
        "Starting embedding generation...",
    )

    def publish_log(msg: str):
        _publish_log(redis_client, str(repo.id), "embedding_progress", msg)

    count = generate_embeddings(
        repository_id=repo.id,
        db=db,
        publish_log=publish_log,
        readme_content=readme_content,
    )

    _publish_log(
        redis_client,
        str(repo.id),
        "embedding_complete",
        f"Embedding complete — {count} vectors stored.",
    )
    return count


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
            logger.debug(
                "Dropping dependency edge to %s — no symbols extracted (config/type-only file?)",
                matched_file.path,
            )
            continue

        last_segment = imp.name.split("/")[-1]
        imported_name = last_segment.split(".")[-1].strip("_")
        target_symbol = symbol_name_map.get((matched_file.id, imported_name))
        if not target_symbol:
            if len(targets) == 1:
                target_symbol = targets[0]
            else:
                logger.debug(
                    "No symbol match for '%s' in %s (%d candidates), dropping edge",
                    imported_name,
                    matched_file.path,
                    len(targets),
                )
                continue

        source_candidates = file_id_to_symbols.get(imp.file_id, [])
        if not source_candidates:
            continue

        if len(source_candidates) == 1:
            source_symbol = source_candidates[0]
        else:
            file_stem = importing_file.split("/")[-1].rsplit(".", 1)[0]
            source_symbol = symbol_name_map.get((imp.file_id, file_stem))
            if not source_symbol:
                source_symbol = max(
                    source_candidates,
                    key=lambda s: (s.end_line or 0) - (s.start_line or 0),
                )

        edge = (source_symbol.id, target_symbol.id)
        if edge in seen:
            continue
        seen.add(edge)

        deps_to_insert.append(
            Dependency(
                source_symbol_id=source_symbol.id,
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
    from collections import defaultdict

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

    languages: set[str] = set()
    frameworks: set[str] = set()
    databases: set[str] = set()
    ci_cd: set[str] = set()
    infrastructure: set[str] = set()

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
                    "supabase": "Supabase",
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

                if re.search(
                    r"^\s*(import fastapi|from fastapi[\. ])", text, re.MULTILINE
                ):
                    frameworks.add("FastAPI")
                if re.search(
                    r"^\s*(import django|from django[\. ])", text, re.MULTILINE
                ):
                    frameworks.add("Django")
                if re.search(r"^\s*(import flask|from flask[\. ])", text, re.MULTILINE):
                    frameworks.add("Flask")

                if re.search(
                    r"^\s*(import sqlalchemy|from sqlalchemy[\. ])", text, re.MULTILINE
                ):
                    databases.add("SQLAlchemy")

                if re.search(
                    r"^\s*(import psycopg|from psycopg[\. ])", text, re.MULTILINE
                ):
                    databases.add("PostgreSQL")

                if re.search(
                    r"^\s*(import pymongo|from pymongo[\. ])", text, re.MULTILINE
                ):
                    databases.add("MongoDB")

                if re.search(r"^\s*(import redis|from redis[\. ])", text, re.MULTILINE):
                    databases.add("Redis")

                if re.search(
                    r"^\s*(import celery|from celery[\. ])", text, re.MULTILINE
                ):
                    infrastructure.add("Celery")

            except Exception:
                pass

    for f in all_files:
        name = f.name.lower()

        if name == "pom.xml":
            try:
                text = f.read_text(errors="ignore").lower()
                if "spring-boot" in text:
                    frameworks.add("Spring Boot")
                if "hibernate" in text:
                    databases.add("Hibernate")
            except Exception:
                pass

        if name in {"build.gradle", "build.gradle.kts"}:
            try:
                text = f.read_text(errors="ignore").lower()
                if "org.springframework" in text:
                    frameworks.add("Spring")
                if "hibernate" in text:
                    databases.add("Hibernate")
            except Exception:
                pass

    go_mod = repo_root / "go.mod"
    if go_mod.exists():
        text = go_mod.read_text().lower()
        if "gin-gonic" in text:
            frameworks.add("Gin")
        if "labstack/echo" in text:
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

    manage_path = repo_root / "manage.py"
    if manage_path.exists():
        try:
            manage_text = manage_path.read_text(errors="ignore")
            if re.search(
                r"^\s*(import django|from django[\. ])", manage_text, re.MULTILINE
            ):
                frameworks.add("Django")
        except OSError:
            pass

    if any((repo_root / f).exists() for f in ["next.config.js", "next.config.ts"]):
        frameworks.add("Next.js")

    if (repo_root / "apps").exists() and (repo_root / "packages").exists():
        infrastructure.add("Monorepo")

    for f in all_files:
        name = f.name.lower()
        path = str(f).lower()

        if "socketio" in name or "socket.io" in name:
            infrastructure.add("Socket.IO")
            infrastructure.add("WebSockets")
        elif re.search(r"\bsocket\b", name) or re.search(r"\bws\b", name):
            infrastructure.add("WebSockets")

        if "prisma" in path:
            databases.add("Prisma ORM")
            databases.add("PostgreSQL")

        if "drizzle.config" in path:
            databases.add("Drizzle ORM")

        if re.search(r"\bredis\b", name):
            databases.add("Redis")

    if (repo_root / ".github" / "workflows").exists():
        ci_cd.add("GitHub Actions")

    if (repo_root / ".gitlab-ci.yml").exists():
        ci_cd.add("GitLab CI")

    if (repo_root / "Jenkinsfile").exists():
        ci_cd.add("Jenkins")

    if (repo_root / "Dockerfile").exists():
        infrastructure.add("Docker")
    if (repo_root / "docker-compose.yml").exists() or (
        repo_root / "docker-compose.yaml"
    ).exists():
        infrastructure.add("Docker")

    if any(
        f.suffix in {".yaml", ".yml"} and "kind:" in f.read_text(errors="ignore")
        for f in all_files
    ):
        infrastructure.add("Kubernetes")

    if any(f.suffix == ".tf" for f in all_files):
        infrastructure.add("Terraform")

    return {
        "languages": sorted(languages),
        "frameworks": sorted(frameworks),
        "databases": sorted(databases),
        "ci_cd": sorted(ci_cd),
        "infrastructure": sorted(infrastructure),
    }


def detect_entry_points(repo_root: Path) -> list[str]:

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
