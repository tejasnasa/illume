"""Heuristic tech-stack and entry-point detection.

Scans package manifests (package.json, go.mod, Cargo.toml, Gemfile,
composer.json, pom.xml, build.gradle), CI/infra files, and raw source text to
infer a repository's languages, frameworks, databases, CI/CD systems, and
infrastructure — plus likely entry-point files. All detection is best-effort
pattern matching; unreadable files are silently skipped.
"""

import json
import re
from pathlib import Path

# Extensions counted when tallying source-file languages.
SOURCE_EXTENSIONS = {
    ".py",
    ".ipynb",
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

# Directories excluded from all scanning (vendored/generated content).
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


def detect_stack(repo_root: Path) -> dict:
    """Heuristically detect a repository's stack by scanning manifests and source.

    This is a best-effort heuristic scanner: it walks all files (skipping
    vendored dirs) and infers the stack from file extensions, dependency
    manifests (package.json, go.mod, Cargo.toml, Gemfile, composer.json,
    pom.xml, build.gradle), import statements in Python/notebook sources,
    well-known config filenames, and CI/infra file presence. Any unreadable or
    malformed file is skipped rather than raising.

    Args:
        repo_root: Root directory of the cloned repository.

    Returns:
        Dict with sorted lists under the keys ``languages``, ``frameworks``,
        ``databases``, ``ci_cd``, and ``infrastructure``.
    """
    languages: set[str] = set()
    frameworks: set[str] = set()
    databases: set[str] = set()
    ci_cd: set[str] = set()
    infrastructure: set[str] = set()

    ext_map = {
        ".py": "Python",
        ".ipynb": "Python",
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
        if f.suffix in (".py", ".ipynb"):
            try:
                if f.suffix == ".ipynb":
                    try:
                        # Notebooks store code as JSON; concatenate code-cell
                        # sources (which may be str or list-of-str) into one
                        # script so the same regexes apply.
                        content = f.read_text(encoding="utf-8", errors="replace")
                        nb_data = json.loads(content)
                        cells = nb_data.get("cells", [])
                        code_pieces = []
                        for cell in cells:
                            if cell.get("cell_type") == "code":
                                source = cell.get("source", "")
                                if isinstance(source, list):
                                    code_text = "".join(source)
                                else:
                                    code_text = str(source)
                                if code_text:
                                    # Newline separator keeps imports on distinct
                                    # lines so MULTILINE regexes match per-cell.
                                    if not code_text.endswith("\n"):
                                        code_text += "\n"
                                    code_pieces.append(code_text)
                        text = "".join(code_pieces).lower()
                    except Exception:
                        continue
                else:
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
    """Heuristically identify likely application entry-point files.

    Matches conventional entry filenames (main.py, index.ts, manage.py,
    Dockerfile, etc.), framework-specific locations (Next.js pages/app
    routes), and source patterns such as ``if __name__ == "__main__"`` or
    ``func main()``.

    Args:
        repo_root: Root directory of the cloned repository.

    Returns:
        Sorted list of repo-relative paths of candidate entry points.
    """
    entry_points: set[str] = set()

    all_files = [
        f
        for f in repo_root.rglob("*")
        if f.is_file() and not any(skip in f.parts for skip in SKIP_DIRS)
    ]

    def rel(f: Path) -> str:
        """Return a file's path relative to the repo root with forward slashes."""
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
            # Generic index/main names are too common in UI code to always be
            # entry points; only trust them in server-ish locations.
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

        # Build/manifest files mark runnable projects even without source hits.
        if name in {"pom.xml", "build.gradle", "build.gradle.kts"}:
            entry_points.add(path)

        if name in {"cargo.toml", "go.mod", "gemfile", "composer.json"}:
            entry_points.add(path)

        if name == "dockerfile":
            entry_points.add(path)

    for f in all_files:
        # Second pass over sources: framework bootstrap calls are stronger
        # entry-point signals than filenames alone.
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

        if "createserver" in text or "http.createserver" in text:
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
