"""Repository file processing pipeline.

Walks a cloned repository's source files, parses them into AST symbols,
persists files/symbols/dependencies to the database, computes fan metrics,
detects the tech stack, and generates embeddings. Criticality scoring is no
longer invoked here -- ``ingest_repository`` calls ``run_criticality_scoring``
once git history has populated the columns it depends on
(``git_last_modified``, ``has_tests``).

Memory shape: rather than committing every file individually -- which
keeps one ORM instance per pending row in the session's identity map -- the loop
collects *plain dict rows* and emits them in batches via
``db.execute(insert(...))``. Each batch is committed before the next is built,
so the live set of pending rows is bounded by the batch size rather than by
the whole file count. UUIDs are assigned client-side with ``uuid4()`` so the
symbols batch can reference its files without a round-trip to read back their
server-assigned ids.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

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
    detect_entry_points,
    detect_stack,
    is_scannable,
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


def _update_status(
    db: Session,
    redis_client,
    repo: Repository,
    status: str,
    manage_status: bool = True,
) -> None:
    """Persist a new repo status and broadcast it over the log stream.

    See :func:`app.services.cloner._update_status` for the
    ``manage_status=False`` contract -- the sync path uses it to leave a
    ready row's status alone.
    """
    if not manage_status:
        return
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
    files whose extension is in ``SOURCE_EXTENSIONS``. The predicate
    :func:`app.services.stack_detector.is_scannable` is the single source
    of truth -- both this walk and the incremental delta consult it, so a
    change to one is automatically picked up by the other.

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
            try:
                relative = filepath.relative_to(repo_root).as_posix()
            except ValueError:
                # ``walk`` only descends into ``repo_root``; this branch is
                # defensive against a symlink that escapes it.
                continue
            if is_scannable(relative):
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
    manage_status: bool = True,
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
        manage_status: When ``False``, suppress the ``status='parsing'`` flip
            and its log frame.

    Returns:
        Number of source files successfully parsed and stored.
    """
    _update_status(db, redis_client, repo, "parsing", manage_status=manage_status)
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


def apply_file_delta(
    db: Session,
    repository_id: uuid.UUID,
    repo_root: Path,
    paths: Iterable[str],
) -> tuple[int, int, int]:
    """Apply one git diff's worth of file changes to the database.

    The unit of incremental work: one call per sync. ``paths`` is the set
    of repo-relative paths ``git diff --name-status -M`` produced (after
    renames have been normalised to their post-rename target). For each
    path the caller has already classified as one of ``{"A", "M", "R"}``
    or ``"D"``, the function either upserts the row or deletes it.

    Insertion (A/M/R): the row is upserted by ``(repository_id, path)``
    on the ``uq_file_repo_path`` unique constraint. Every derived column
    is rewritten -- language, loc, path -- so the post-write row is
    indistinguishable from a fresh insert regardless of what the prior
    row looked like. Symbols belonging to the file are deleted first
    (cascade clears their embeddings and dependency edges), then the
    new ones are inserted.

    Deletion (D): the row goes. Cascade clears every symbol, dependency
    edge, code-owner row and file-scoped embedding.

    Failure mode: ``parse_file`` returning ``None`` (unparseable /
    unsupported) and ``(repo_root / path).is_file()`` returning ``False``
    (submodule pointer rendered as ``M`` on a directory, file moved away)
    both fall through to the delete branch -- the same transaction
    deletes the row rather than leaving a symbol-less orphan behind.

    Args:
        db: Session used for all persistence; the caller controls the
            transaction. The function does not commit -- the sync task
            holds Txn 1 across all of Step A.
        repository_id: ID of the repository whose rows are being mutated.
        repo_root: Filesystem root of the (already-reset) working tree.
        paths: Iterable of repo-relative paths to upsert/delete. Empty
            iterables are valid: nothing to do, both return values are 0.

    Returns:
        Tuple of ``(upserted, deleted, changed)`` where ``changed`` is
        the union of the two -- the size of the work performed, used by
        the delta engine to decide whether to escalate to a full rebuild.
    """
    upserted = 0
    deleted = 0

    for raw_path in paths:
        path = raw_path.replace("\\", "/")
        file_on_disk = repo_root / path
        # ``is_scannable`` filters to extensions we know how to parse; a
        # ``.png`` in the diff is not a parseable source file, so it is
        # neither upserted nor deleted -- the absence in the database is
        # the right state. ``parse_file`` is the more authoritative check
        # for files that *look* parseable, so a previously-parseable file
        # that became unparseable still goes through the delete branch.
        should_have = file_on_disk.is_file() and is_scannable(path)

        if should_have:
            parsed = parse_file(file_on_disk)
            if parsed is None:
                should_have = False

        if not should_have:
            deleted += _delete_file_row(db, repository_id, path)
            continue

        # Cascade-clear the file's prior symbols + their edges before
        # re-inserting. The dependency resolver rebuilds whole-repo
        # afterwards, so a per-file delete is enough to clear the
        # outgoing edges the resolver will rebuild anyway. Incoming
        # edges from unchanged importers are not destroyed by this
        # delete -- the ``Dependency.source_symbol_id`` cascade reaches
        # *outgoing* edges only -- which is precisely why the whole-repo
        # re-resolve is the right follow-up.
        _delete_file_row(db, repository_id, path)

        new_file_id = uuid.uuid4()
        db.execute(
            pg_insert(File)
            .values(
                {
                    "id": new_file_id,
                    "repository_id": repository_id,
                    "path": path,
                    "language": parsed.language,
                    "loc": parsed.loc,
                }
            )
            .on_conflict_do_update(
                index_elements=["repository_id", "path"],
                set_={
                    "language": parsed.language,
                    "loc": parsed.loc,
                    "path": path,
                },
            )
        )
        if parsed.symbols:
            db.execute(
                pg_insert(AstSymbol).values(
                    [
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
                        for symbol in parsed.symbols
                    ]
                )
            )
        upserted += 1

    return upserted, deleted, upserted + deleted


def _delete_file_row(db: Session, repository_id: uuid.UUID, path: str) -> int:
    """Delete the ``File`` row for ``(repository_id, path)``; return 1 if it existed.

    Returns 0 when the row was already absent -- the common case for a
    branch switch that lands on a tree where the path is new. The CASCADE
    on ``ast_symbols.file_id`` clears the row's symbols and the symbols'
    outgoing ``Dependency`` rows in one statement.
    """
    result = (
        db.query(File)
        .filter(File.repository_id == repository_id, File.path == path)
        .delete(synchronize_session=False)
    )
    return 1 if result else 0


def compute_delta(
    repo_root: Path,
    old_sha: str,
    new_sha: str,
) -> list[tuple[str, str]]:
    """Return ``[(status, path)]`` for files changed between two SHAs.

    Runs ``git diff --name-status -M <old> <new>`` against the working
    tree. The ``-M`` flag picks up renames; ``status`` is one of
    ``{A, M, D, R, ...}`` per git's convention. Returns an empty list
    when the two SHAs agree, which the caller turns into the
    short-circuit path (no DB writes, no LLM calls).

    The function does not filter on ``SKIP_DIRS`` -- it returns the full
    diff. ``is_scannable`` is consulted by :func:`apply_file_delta` and
    the resolver, so a non-source change (``.png``, ``alembic/``) is a
    no-op there rather than being elided here. Centralising the filter in
    one place is what keeps the incremental file set from drifting from
    the full-walk file set.

    Args:
        repo_root: Filesystem path to the cloned working tree, already
            pointing at ``new_sha``.
        old_sha: Commit SHA the repo's data was last synced against. May
            be missing or detached -- callers verify reachability.
        new_sha: Commit SHA the working tree is currently at.

    Returns:
        List of ``(status, path)`` pairs in git's order, with paths
        normalised to forward slashes. The pair is what the deltas
        engine threads through :func:`apply_file_delta`.
    """
    import subprocess

    output = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "diff",
            "--name-status",
            "-M",
            old_sha,
            new_sha,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout

    diff: list[tuple[str, str]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 2)
        if len(parts) < 2:
            continue
        status = parts[0][0]  # ``R100`` -> ``R``
        # ``R`` rows carry three fields: ``R100``, ``old``, ``new``. We
        # want the post-rename target -- the resolver keys on it.
        path = parts[-1]
        diff.append((status, path.replace("\\", "/")))
    return diff


def is_fast_forward(old_sha: str, new_sha: str, repo_root: Path) -> bool:
    """Whether ``old_sha`` is an ancestor of ``new_sha`` (or equal to it).

    A fast-forward is the cheap case the delta engine can service
    surgically. Anything else -- a force-push, a branch switch, a
    rebase -- is the expensive case that escalates to a full rebuild.

    ``git merge-base --is-ancestor`` exits 0 when the relation holds and
    1 otherwise. Both SHAs are verified reachable first so a corrupted
    ``old_sha`` produces a clear error rather than the silent
    ``bad object`` git would otherwise raise inside the diff.
    """
    import subprocess

    for sha in (old_sha, new_sha):
        subprocess.run(
            ["git", "-C", str(repo_root), "cat-file", "-e", f"{sha}^{{commit}}"],
            capture_output=True,
            timeout=30,
            check=True,
        )
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "merge-base",
            "--is-ancestor",
            old_sha,
            new_sha,
        ],
        capture_output=True,
        timeout=30,
    )
    return result.returncode == 0


def should_escalate(
    diff: list[tuple[str, str]],
    total_files: int,
    *,
    max_files: int,
    max_ratio: float,
) -> bool:
    """Whether a diff is large enough that a full rebuild is cheaper.

    Two thresholds, either of which trips the escalation. The hard cap
    on changed files is absolute: past ``max_files`` a re-ingest is the
    only sane option, no matter how small the repository is. The ratio
    cap is for repositories where a half-the-tree diff has happened; a
    re-resolution of the whole graph is more work than a clean rebuild.

    The function reads ``total_files`` rather than recomputing it so the
    caller can decide which count to use (e.g. exclude ``SKIP_DIRS``-only
    paths the walk would have skipped). Today the caller passes the raw
    repository file count from the prior ingest.
    """
    changed = len(diff)
    if changed > max_files:
        return True
    if total_files > 0 and (changed / total_files) > max_ratio:
        return True
    return False


def summarise(
    *,
    upserted: int,
    deleted: int,
    new_sha: str,
    glossary_added: int = 0,
    embeddings_added: int = 0,
) -> dict:
    """Build the ``last_sync_summary`` JSONB payload the UI surfaces.

    Shape is what the settings panel renders in the status line ("12
    files changed, 3 commits, updated just now"); the exact keys are
    pinned by the test that consumes them.
    """
    return {
        "files_upserted": upserted,
        "files_deleted": deleted,
        "files_changed": upserted + deleted,
        "new_commit_sha": new_sha,
        "glossary_added": glossary_added,
        "embeddings_added": embeddings_added,
        "status": "ok",
    }


def embed_repository_symbols(
    db: Session,
    redis_client,
    repo: Repository,
    readme_content: str | None = None,
    measure_memory: bool = True,
    manage_status: bool = True,
    embedding_mode: Literal["full", "incremental"] = "full",
) -> int:
    """Generate vector embeddings for a repository's indexed symbols.

    Args:
        db: Database session used by the embedder.
        redis_client: Redis client for publishing progress logs.
        repo: Repository record whose symbols should be embedded.
        readme_content: Optional README text included as extra context for
            embedding generation.
        measure_memory: Passed through to the ``generate_embeddings`` stage
            timer. Set False when the caller runs this concurrently with
            another stage -- ``tracemalloc`` and ``VmHWM`` are process-global,
            so the peak delta would cover the other thread's allocations too.
            Callers that need a clean per-stage memory number for the embedder
            must run it unoverlapped.
        manage_status: When ``False``, suppress the ``status='embedding'`` flip
            and its log frame.
        embedding_mode: Forwarded to :func:`generate_embeddings`. ``"full"``
            deletes the repo's existing ``Embedding`` rows first (the
            initial-ingest path); ``"incremental"`` is the sync task's mode
            and skips that delete. The reconcile logic that makes
            incremental actually useful is added later.

    Returns:
        Number of embedding vectors stored.
    """
    _update_status(db, redis_client, repo, "embedding", manage_status=manage_status)
    publish_log(
        redis_client,
        str(repo.id),
        "embedding_started",
        "Starting embedding generation...",
    )

    def publish_progress(msg: str):
        """Forward embedder messages to the repo's log stream."""
        publish_log(redis_client, str(repo.id), "embedding_progress", msg)

    with stage("generate_embeddings", measure_memory=measure_memory):
        count = generate_embeddings(
            repository_id=repo.id,
            db=db,
            publish_log=publish_progress,
            readme_content=readme_content,
            mode=embedding_mode,
        )

    publish_log(
        redis_client,
        str(repo.id),
        "embedding_complete",
        f"Embedding complete — {count} vectors stored.",
    )
    return count
