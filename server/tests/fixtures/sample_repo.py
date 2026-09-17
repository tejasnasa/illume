"""Builds a small polyglot git repository for pipeline tests.

The obvious shape for this is a committed `sample-repo/` directory; this builds the same
thing programmatically instead, for one reason: a committed sample would need a nested
`.git` directory checked into the repository, which git cannot track usefully and which
would go stale the moment anything referenced it. A builder is deterministic, is
reviewable as source, and produces a genuinely valid repository every run.

The content is chosen so that each stage of the pipeline has something to find:

* `src/main.py` imports `src/util.py` and `src/models.py` -- a real dependency edge, and
  a fan-in of 2 for `util`.
* `src/service.py` holds a class with methods, so the traversal that has to open a class
  body to reach them is exercised rather than passing on an empty result.
* `web/api.ts` and `web/format.ts` give the TypeScript grammar and a second language for
  the language breakdown.
* `src/orphan.py` imports nothing and is imported by nothing, so the graph has an
  isolated node.
* `README.md` with `##` sections, which the embedder splits into document chunks.
* A commit message containing `|`, which the field-separated `git log` parse must not
  truncate.
* A file moved into a subdirectory between commits, producing a one-sided rename
  (`{ => pkg}/`), which the rename normaliser must collapse back to a real path.

The second commit exists so there is more than one entry in the git history -- ownership
percentages and change frequency are meaningless with a single commit.
"""

from __future__ import annotations

import itertools
import os
import subprocess
from pathlib import Path

AUTHOR_NAME = "Ada Lovelace"
AUTHOR_EMAIL = "ada@example.com"

# Fixed, and in the past. Two reasons: a deterministic timestamp makes `git_last_modified`
# and change-frequency assertions reproducible, and it is what lets a test tell an
# authored date apart from `_parse_git_date`'s fallback to `now()` -- the failure mode
# where an unparsed date was silently replaced by the analysis time.
FIRST_COMMIT_DATE = "2026-01-01T12:00:00+00:00"
SECOND_COMMIT_DATE = "2026-02-01T12:00:00+00:00"

# Roughly 10 kB of source: comfortably past `MAX_CHUNK_TOKENS` (2048 estimated tokens, and
# `_token_estimate` is `len(text) // 4`, so about 8192 characters) whether it is rendered as
# the symbol's chunk or as the whole-file fallback. Both matter -- see
# `test_a_file_too_large_to_chunk_is_absent_from_the_index`.
_OVERSIZED_BODY = "\n".join(f"    value_{i} = {i}" for i in range(550))

FILES = {
    "README.md": """# Sample Project

A tiny repository used to exercise the ingestion pipeline.

## Overview

It reads files and reports on them.

## Usage

Run `python -m src.main`.
""",
    "src/util.py": '''"""String helpers."""


def slugify(text: str) -> str:
    """Lowercase a string and replace spaces with hyphens."""
    return text.strip().lower().replace(" ", "-")
''',
    "src/models.py": '''"""Domain types."""


class Report:
    """A summary of one file."""

    def __init__(self, path: str, lines: int):
        self.path = path
        self.lines = lines

    def describe(self) -> str:
        """Render the report as a single line."""
        return f"{self.path}: {self.lines}"

    def is_large(self) -> bool:
        """Whether the file exceeds a hundred lines."""
        return self.lines > 100
''',
    "src/service.py": '''"""Ties the pieces together."""
from src.models import Report
from src.util import slugify


class Scanner:
    """Walks input and builds reports."""

    def scan(self, names: list[str]) -> list[Report]:
        """Build one report per name."""
        return [Report(slugify(n), len(n)) for n in names]

    def largest(self, reports: list[Report]) -> Report | None:
        """Return the report with the most lines."""
        return max(reports, key=lambda r: r.lines) if reports else None
''',
    "src/main.py": '''"""Entry point."""
from src.service import Scanner
from src.util import slugify

from orphan import nothing


def run() -> None:
    """Print a report for a fixed set of names."""
    scanner = Scanner()
    for report in scanner.scan(["Hello World", "Second"]):
        print(report.describe())


if __name__ == "__main__":
    run()
''',
    "src/orphan.py": '''"""Imported by nothing and importing nothing."""


def nothing() -> None:
    """Do nothing at all."""
''',
    "web/format.ts": """export function titleCase(value: string): string {
  return value.replace(/\\b\\w/g, (c) => c.toUpperCase());
}

export interface FormatOptions {
  uppercase?: boolean;
}
""",
    "web/api.ts": """import { titleCase } from "./format";

export const endpoint = "/api/v1/reports";

export class ReportClient {
  constructor(private readonly baseUrl: string) {}

  async fetchAll(): Promise<string[]> {
    const res = await fetch(`${this.baseUrl}${endpoint}`);
    return res.json();
  }
}
""",
    # A two-file import cycle. `_topological_sort` documents that files inside a cycle
    # are appended as a final tier, and nothing else in the suite produces one -- the rest
    # of the fixture is a DAG. Without this the cycle branch is only ever read, never run.
    "src/cycle_a.py": '''"""One half of an import cycle."""
from src.cycle_b import b_func


def a_func() -> str:
    """Delegate to the other half."""
    return b_func()
''',
    "src/cycle_b.py": '''"""The other half of an import cycle."""
from src.cycle_a import a_func


def b_func() -> str:
    """Return a constant; the import above closes the cycle."""
    return "b"
''',
    # Non-ASCII *file name*, ASCII contents -- one variable at a time. This is what
    # exercises `relative_to(root).as_posix()` on a path that is not encodable as ASCII,
    # and the ownership/churn matching that keys on the same string.
    "src/café.py": '''"""A module whose file name is not ASCII."""


def greeting() -> str:
    """Return a greeting."""
    return "hallo"
''',
    # Malformed JSON, so `parse_notebook` returns None and `process_repository_files`
    # takes its "unparseable, skip it" branch instead of aborting the run.
    #
    # A file full of *syntax errors* would not do this: tree-sitter is error-tolerant and
    # still returns a partial parse, and `parse_file` only returns None for an unsupported
    # extension, an unreadable file, or a rejected notebook. A syntax-error file is the
    # obvious choice for covering this branch, but it would not have covered it.
    "src/broken.ipynb": '{"cells": [{"cell_type": "code", "source": ["x = 1"]},',
    # Too large to embed by either route. `embedder` drops an oversized chunk rather than
    # truncating it, and measures the whole-file fallback against the same limit -- so a
    # file that is oversized both ways ends up with no chunk at all and is silently
    # invisible to chat search.
    "src/oversized.py": f'''"""A module whose one function is too large to embed."""


def enormous() -> int:
    """Assign a great many locals, then return a constant."""
{_OVERSIZED_BODY}
    return 0
''',
}

# Committed second, to create a one-sided rename: `src/nested.py` becomes
# `src/pkg/nested.py`, which git renders as `src/{ => pkg}/nested.py`.
RENAMED_FROM = "src/nested.py"
RENAMED_TO = "src/pkg/nested.py"

LATE_FILE = '''"""Added late so the second commit has work to do."""


def later() -> int:
    """Return a constant."""
    return 42
'''


# One offset consumed per `build()`, so no two builds in a process produce the same
# commits. Combined with the worker index, which is what makes it unique across processes
# as well -- see `_next_date_offset`.
_builds = itertools.count()


def _git(repo: Path, *args: str, env_extra: dict | None = None) -> str:
    """Run a git command in `repo`, returning stdout."""
    import os

    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": AUTHOR_NAME,
        "GIT_AUTHOR_EMAIL": AUTHOR_EMAIL,
        "GIT_COMMITTER_NAME": AUTHOR_NAME,
        "GIT_COMMITTER_EMAIL": AUTHOR_EMAIL,
        # Keep the fixture's history independent of the developer's global config.
        "GIT_CONFIG_GLOBAL": str(repo / ".gitconfig-none"),
        "GIT_CONFIG_SYSTEM": str(repo / ".gitconfig-none"),
        **(env_extra or {}),
    }
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def build(root: Path) -> Path:
    """
    Create the repository at `root` and return it.

    Two commits, deliberately: the first is the bulk of the files, the second adds one and
    moves another, so `git log --numstat` has a rename and more than one author-date to
    work with.
    """
    root.mkdir(parents=True, exist_ok=True)
    offset = _next_date_offset()
    _git(root, "init", "-b", "main")

    for relative, content in FILES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        # write_bytes, not write_text: Windows would otherwise translate the newlines and
        # the captured source_code would not match what was written.
        path.write_bytes(content.encode("utf-8"))

    nested = root / RENAMED_FROM
    nested.write_bytes(
        b'"""Later moved into a package."""\n\n\ndef nested() -> int:\n    return 1\n'
    )

    _git(root, "add", "-A")
    _git(
        root,
        "commit",
        "-m",
        "feat: initial import of the sample project",
        env_extra=_dated(FIRST_COMMIT_DATE, offset),
    )

    # The pipe is the point: `git log` is parsed with a field separator, and a message
    # containing it used to truncate the message and lose the commit date.
    moved = root / RENAMED_TO
    moved.parent.mkdir(parents=True, exist_ok=True)
    moved.write_bytes(nested.read_bytes())
    nested.unlink()
    (root / "src" / "late.py").write_bytes(LATE_FILE.encode("utf-8"))

    _git(root, "add", "-A")
    _git(
        root,
        "commit",
        "-m",
        "feat: move helper into a package | also add late.py",
        env_extra=_dated(SECOND_COMMIT_DATE, offset),
    )

    return root


def _next_date_offset() -> int:
    """
    Seconds to shift the *next* fixture repository's commit dates by.

    `commits.hash` is globally unique and this repository is otherwise byte-identical every
    time -- same author, same dates, same content -- so any two ingests of it collide on
    that constraint and the second one dies:

        psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint
        "commits_hash_key"
        DETAIL:  Key (hash)=(b97d8d69ee36fe3c90947b1a84df18cb90e0a1f8) already exists.

    That is the duplicate-hash collision surfacing as an execution-order flake, and the
    offset has to be unique per *build*, not merely per worker. A worker-only offset fixes
    the cross-worker case and leaves the one that actually bites: two tests on the same
    worker in quick succession, where the first test's teardown has not yet removed its
    commits.
    That is why the collision named the worker's *own* commit hash -- `b97d8d69` is what
    gw3 builds, and gw3 was the worker that failed.

    Shifting the dates changes the hash while leaving everything asserted on alone. The
    offset is whole minutes against commits made at noon, so the calendar date is
    unchanged, and the only date assertion is that these are well in the past -- see
    `test_a_commit_date_is_the_authored_date_not_the_analysis_time`.

    That collision is fixed -- the redundant global constraint was dropped by migration
    `e934fbe8247e` -- so the per-build offset is no longer load-bearing. It is kept because
    distinct hashes make a test failure easier to read, and because
    `tests/migrations/test_migrate.py::TestCommitHashUniqueness` deliberately re-creates
    the shared-hash case rather than relying on a fixture to produce it by accident.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    try:
        worker_index = int(worker.removeprefix("gw"))
    except ValueError:
        worker_index = 0
    return (worker_index * 10_000 + next(_builds)) * 60


def _shift(timestamp: str, offset: int) -> str:
    """Move an ISO timestamp forward by `offset` seconds."""
    from datetime import datetime, timedelta

    return (datetime.fromisoformat(timestamp) + timedelta(seconds=offset)).isoformat()


def _dated(timestamp: str, offset: int) -> dict:
    """Environment that pins both the author and committer date of a commit."""
    shifted = _shift(timestamp, offset)
    return {"GIT_AUTHOR_DATE": shifted, "GIT_COMMITTER_DATE": shifted}
