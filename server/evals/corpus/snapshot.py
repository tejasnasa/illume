"""Database snapshots with ``pg_dump`` / ``pg_restore``.

A snapshot lets later runs reuse a paid-for ingestion (embeddings, glossaries, briefs)
instead of repeating it. The password reaches the child processes only through the
``PGPASSWORD`` environment variable, never the command line.
"""

import os
import shutil
import subprocess
from pathlib import Path

from sqlalchemy.engine import make_url

SNAPSHOT_TIMEOUT_SECONDS = 3600
_TOLERATED_SET = "SET transaction_timeout"


class SnapshotError(RuntimeError):
    """Raised when a snapshot or restore cannot run or fails."""


def _tool(name: str) -> str:
    """Locate a PostgreSQL client tool on ``PATH``.

    Raises:
        SnapshotError: If it is not installed.
    """
    found = shutil.which(name)
    if found is None:
        raise SnapshotError(f"{name} was not found on PATH; install the PostgreSQL client tools")
    return found


def _connection(db_url: str) -> tuple[list[str], dict[str, str]]:
    """Split a SQLAlchemy URL into libpq arguments and a child environment.

    Args:
        db_url: A ``postgresql://`` or ``postgresql+driver://`` URL.

    Returns:
        The ``--host/--port/--username/--dbname`` arguments and an environment carrying
        ``PGPASSWORD`` when the URL has a password.
    """
    url = make_url(db_url)
    if not url.database:
        raise SnapshotError("the database URL names no database")
    args = ["--dbname", url.database]
    if url.host:
        args += ["--host", url.host]
    if url.port:
        args += ["--port", str(url.port)]
    if url.username:
        args += ["--username", url.username]
    env = dict(os.environ)
    if url.password:
        env["PGPASSWORD"] = url.password
    return args, env


def _only_version_skew(stderr: str) -> bool:
    """Whether every error in ``pg_restore`` output is the newer-client ``SET`` it cannot apply.

    A dump taken by a newer client than the server begins with settings the older server
    rejects (``transaction_timeout`` from version 17). ``pg_restore`` carries on and
    restores everything else, then exits non-zero; that exit is not a failed restore.
    """
    errors = [line for line in stderr.splitlines() if line.startswith("pg_restore: error:")]
    commands = [line for line in stderr.splitlines() if line.startswith("Command was:")]
    return (
        bool(errors)
        and len(errors) == len(commands)
        and all(_TOLERATED_SET in line for line in commands)
    )


def _run(
    command: list[str], env: dict[str, str], action: str, *, tolerate_version_skew: bool = False
) -> None:
    """Run a client tool, raising a message that omits the environment on failure."""
    try:
        result = subprocess.run(
            command,
            env=env,
            capture_output=True,
            text=True,
            timeout=SNAPSHOT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise SnapshotError(f"{action} timed out") from exc
    if result.returncode != 0 and not (tolerate_version_skew and _only_version_skew(result.stderr)):
        raise SnapshotError(f"{action} failed ({result.returncode}): {result.stderr.strip()}")


def snapshot(db_url: str, out_file: Path) -> Path:
    """Dump a database to a custom-format archive.

    Args:
        db_url: The database to dump.
        out_file: Where to write the archive; parent directories are created.

    Returns:
        ``out_file``.

    Raises:
        SnapshotError: If ``pg_dump`` is missing or fails.
    """
    dump = _tool("pg_dump")
    args, env = _connection(db_url)
    out_file = Path(out_file)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    _run([dump, "-Fc", "--file", str(out_file), *args], env, "pg_dump")
    return out_file


def restore(db_url: str, in_file: Path) -> None:
    """Restore a custom-format archive, replacing what it overlaps.

    Args:
        db_url: The database to restore into.
        in_file: An archive written by :func:`snapshot`.

    Raises:
        SnapshotError: If the archive is missing, ``pg_restore`` is absent or it fails.
    """
    if not Path(in_file).is_file():
        raise SnapshotError(f"no snapshot at {in_file}")
    tool = _tool("pg_restore")
    args, env = _connection(db_url)
    _run(
        [tool, "--clean", "--if-exists", "--no-owner", *args, str(in_file)],
        env,
        "pg_restore",
        tolerate_version_skew=True,
    )
