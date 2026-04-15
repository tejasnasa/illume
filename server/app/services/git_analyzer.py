import json
import logging
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.models import CodeOwner, Commit, File
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

GIT_LOG_MAX_COMMITS = 500

_TEST_TEMPLATES = [
    "test_{stem}{suffix}",
    "{stem}.test{suffix}",
    "{stem}.spec{suffix}",
    "{stem}_test{suffix}",
    "{stem}.test.js",
    "{stem}.spec.js",
    "{stem}.test.tsx",
    "{stem}.spec.tsx",
    "test_{stem}.py",
    "{stem}_spec{suffix}",
]

_REDIS_CHANNEL_PREFIX = "ingest:progress"


def analyze_git_history(
    db: Session,
    redis_client,
    repo,
    clone_path: Path,
) -> None:
    _publish(
        redis_client, repo.id, "git_analysis_started", "Starting git history analysis"
    )

    raw_commits = _run_git_log(clone_path)
    parsed = _parse_git_log(raw_commits)
    _publish(
        redis_client,
        repo.id,
        "commits_parsed",
        f"Parsed {len(parsed)} commits from git log",
    )

    if not parsed:
        logger.warning("repo=%s  No commits found – skipping git analysis", repo.id)
        _publish(
            redis_client,
            repo.id,
            "git_analysis_complete",
            "No commits found; git analysis skipped",
        )
        return

    _bulk_insert_commits(db, repo.id, parsed)
    logger.info("repo=%s  Inserted %d commit rows", repo.id, len(parsed))

    file_stats = _aggregate_file_stats(parsed)
    _publish(
        redis_client,
        repo.id,
        "file_stats_aggregated",
        f"Aggregated ownership stats for {len(file_stats)} files",
    )

    has_tests_map = _detect_test_files(clone_path, list(file_stats.keys()))

    _bulk_update_files(db, repo.id, file_stats, has_tests_map)
    logger.info("repo=%s  Updated %d file rows", repo.id, len(file_stats))

    _bulk_insert_code_owners(db, repo.id, file_stats)
    _publish(
        redis_client,
        repo.id,
        "ownership_written",
        f"Code ownership records written for {len(file_stats)} files",
    )

    logger.info("repo=%s  Git analysis complete", repo.id)


def _run_git_log(clone_path: Path) -> str:
    cmd = [
        "git",
        "-C",
        clone_path,
        "log",
        "--numstat",
        "--format=%H|%ae|%an|%s|%ai",
        f"-n{GIT_LOG_MAX_COMMITS}",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        return result.stdout
    except subprocess.CalledProcessError as exc:
        logger.error("git log failed: %s", exc.stderr)
        raise RuntimeError(f"git log failed: {exc.stderr.strip()}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("git log timed out after 120 s") from exc


def _parse_git_log(raw: str) -> list[dict]:

    commits: list[dict] = []
    current: dict | None = None

    for line in raw.splitlines():
        if not line.strip():
            continue

        if "|" in line and _looks_like_header(line):
            if current is not None:
                commits.append(current)
            parts = line.split("|", 4)
            if len(parts) < 5:
                continue
            hash_, email, name, message, date_str = parts
            current = {
                "hash": hash_.strip(),
                "author_email": email.strip().lower(),
                "author_name": name.strip(),
                "message": message.strip(),
                "timestamp": _parse_git_date(date_str.strip()),
                "files": [],
            }
            continue

        if current is not None and "\t" in line:
            file_entry = _parse_numstat_line(line)
            if file_entry:
                current["files"].append(file_entry)

    if current is not None:
        commits.append(current)

    return commits


def _looks_like_header(line: str) -> bool:
    candidate = line.split("|", 1)[0].strip()
    return bool(re.fullmatch(r"[0-9a-f]{7,40}", candidate))


def _parse_numstat_line(line: str) -> dict | None:
    parts = line.split("\t", 2)
    if len(parts) != 3:
        return None

    added_raw, deleted_raw, path_raw = parts
    path = _normalise_rename_path(path_raw.strip())

    try:
        added = int(added_raw) if added_raw != "-" else 0
        deleted = int(deleted_raw) if deleted_raw != "-" else 0
    except ValueError:
        return None

    return {"path": path, "added": added, "deleted": deleted}


_RENAME_RE = re.compile(r"^(.*?)\{(.+?) => (.+?)\}(.*)$")


def _normalise_rename_path(path: str) -> str:
    m = _RENAME_RE.match(path)
    if not m:
        return path
    prefix, _old, new, suffix = m.groups()
    return f"{prefix}{new}{suffix}".replace("//", "/")


def _parse_git_date(date_str: str) -> datetime:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %z")
        return dt.astimezone(timezone.utc)
    except ValueError:
        logger.warning("Could not parse git date %r; using now(UTC)", date_str)
        return datetime.now(timezone.utc)


def _aggregate_file_stats(parsed_commits: list[dict]) -> dict[str, dict]:

    file_author_counts: dict[str, dict[str, dict]] = defaultdict(dict)
    file_last_modified: dict[str, datetime] = {}

    for commit in parsed_commits:
        email = commit["author_email"]
        name = commit["author_name"]
        ts = commit["timestamp"]

        for file_entry in commit["files"]:
            path = file_entry["path"]

            if email not in file_author_counts[path]:
                file_author_counts[path][email] = {"name": name, "commit_count": 0}
            file_author_counts[path][email]["commit_count"] += 1

            if path not in file_last_modified or ts > file_last_modified[path]:
                file_last_modified[path] = ts

    result: dict[str, dict] = {}

    for path, author_map in file_author_counts.items():
        total_commits = sum(a["commit_count"] for a in author_map.values())

        sorted_contributors = sorted(
            author_map.items(),
            key=lambda kv: kv[1]["commit_count"],
            reverse=True,
        )

        contributors = [
            {
                "email": email,
                "name": data["name"],
                "commit_count": data["commit_count"],
                "percentage": round(data["commit_count"] / total_commits * 100, 1),
            }
            for email, data in sorted_contributors
        ]

        primary = sorted_contributors[0]
        primary_email = primary[0]
        primary_name = primary[1]["name"]

        result[path] = {
            "change_frequency": total_commits,
            "last_modified": file_last_modified[path],
            "primary_owner_email": primary_email,
            "primary_owner_name": primary_name,
            "contributors": contributors,
            "is_knowledge_silo": len(author_map) == 1,
        }

    return result


def _detect_test_files(clone_path: Path, file_paths: list[str]) -> dict[str, bool]:
    root = Path(clone_path)

    all_clone_paths: set[str] = set()
    for p in root.rglob("*"):
        if p.is_file():
            try:
                all_clone_paths.add(str(p.relative_to(root)))
            except ValueError:
                pass

    result: dict[str, bool] = {}

    for file_path in file_paths:
        p = Path(file_path)
        stem = p.stem
        suffix = p.suffix
        parent = p.parent

        candidates = _generate_test_candidates(parent, stem, suffix)
        result[file_path] = any(c in all_clone_paths for c in candidates)

    return result


def _generate_test_candidates(
    parent: Path,
    stem: str,
    suffix: str,
) -> list[str]:
    candidate_names: list[str] = []
    for template in _TEST_TEMPLATES:
        try:
            name = template.format(stem=stem, suffix=suffix)
            candidate_names.append(name)
        except KeyError:
            pass

    search_dirs: list[Path] = [
        parent,
        parent / "tests",
        parent / "__tests__",
        parent / "spec",
    ]
    if parent != Path("."):
        search_dirs.append(Path("tests"))
        search_dirs.append(Path("__tests__"))

    candidates: list[str] = []
    for directory in search_dirs:
        for name in candidate_names:
            candidates.append(str(directory / name))

    return candidates


def _bulk_insert_commits(db: Session, repo_id: str, parsed_commits: list[dict]) -> None:
    if not parsed_commits:
        return

    rows = [
        {
            "repository_id": repo_id,
            "hash": c["hash"],
            "author_name": c["author_name"],
            "author_email": c["author_email"],
            "message": c["message"],
            "files_changed": len(c["files"]),
            "authored_at": c["timestamp"],
        }
        for c in parsed_commits
    ]

    stmt = (
        pg_insert(Commit).values(rows).on_conflict_do_nothing(index_elements=["hash"])
    )
    db.execute(stmt)
    db.commit()


def _bulk_update_files(
    db: Session,
    repo_id: str,
    file_stats: dict[str, dict],
    has_tests_map: dict[str, bool],
) -> None:
    if not file_stats:
        return

    file_rows = db.query(File.id, File.path).filter(File.repository_id == repo_id).all()
    path_to_id: dict[str, str] = {row.path: str(row.id) for row in file_rows}

    updates = []
    for path, stats in file_stats.items():
        file_id = path_to_id.get(path)
        if file_id is None:
            continue
        updates.append(
            {
                "id": file_id,
                "change_frequency": stats["change_frequency"],
                "last_modified": stats["last_modified"],
                "has_tests": has_tests_map.get(path, False),
            }
        )

    if not updates:
        return

    if updates:
        db.execute(
            update(File),
            updates,
        )
        db.commit()


def _bulk_insert_code_owners(
    db: Session,
    repo_id: str,
    file_stats: dict[str, dict],
) -> None:
    if not file_stats:
        return

    file_rows = db.query(File.id, File.path).filter(File.repository_id == repo_id).all()
    path_to_id: dict[str, str] = {row.path: str(row.id) for row in file_rows}

    rows = []
    for path, stats in file_stats.items():
        file_id = path_to_id.get(path)
        if file_id is None:
            continue
        rows.append(
            {
                "file_id": file_id,
                "primary_owner": f"{stats['primary_owner_name']} <{stats['primary_owner_email']}>",
                "contributors": json.dumps(stats["contributors"]),
                "is_knowledge_silo": stats["is_knowledge_silo"],
            }
        )

    if not rows:
        return

    stmt = pg_insert(CodeOwner).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["file_id"],
        set_={
            "primary_owner": f"{stats['primary_owner_name']} <{stats['primary_owner_email']}>",
            "contributors": stmt.excluded.contributors,
            "is_knowledge_silo": stmt.excluded.is_knowledge_silo,
        },
    )
    db.execute(stmt)
    db.commit()


def _publish(
    redis_client,
    repo_id: str,
    event: str,
    message: str,
) -> None:
    channel = f"{_REDIS_CHANNEL_PREFIX}:{repo_id}"
    payload = json.dumps(
        {
            "event": event,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    try:
        redis_client.publish(channel, payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis publish failed (channel=%s): %s", channel, exc)
