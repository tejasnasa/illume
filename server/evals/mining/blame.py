"""Blame a line back to the commit and pull request that wrote it.

``git blame`` is run with ``-w -M -C`` (with a lowered copy threshold) so whitespace-only
edits, moved blocks and copies between files are looked through. Commits that are still
mechanical (a mass reformat, a dependency bump, a whitespace-dominated diff) are skipped by
re-blaming the line at the commit's parent, up to a small number of hops.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from evals.mining.clones import git, is_ancestor

MAX_FILES_CHANGED = 30
WHITESPACE_CHANGE_RATIO = 0.10
MECHANICAL_MESSAGE = re.compile(
    r"^(chore\(deps\)|bump|format|reformat|lint|style:|prettier|black|ruff)", re.IGNORECASE
)
# Git's default threshold for detecting a block copied from another file is 40
# alphanumeric characters (20 for a move within a file); a short function moved between
# files falls under it, so both are set to 20.
MOVE_COPY_MIN_CHARS = 20
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

_HEADER = re.compile(r"^([0-9a-f]{40}) (\d+) (\d+)(?: \d+)?$")


@dataclass(frozen=True)
class MechanicalVerdict:
    """Whether a commit is a mechanical change.

    Attributes:
        reason: Why it is mechanical, or ``None`` when it is an ordinary commit.
    """

    reason: str | None

    @property
    def mechanical(self) -> bool:
        """Whether the commit should be looked through."""
        return self.reason is not None


@dataclass(frozen=True)
class BlameLine:
    """One line of a file with its origin.

    Attributes:
        line: The line number at the blamed revision (1-based).
        commit: The commit that wrote it.
        original_path: The path the line had in that commit.
        original_line: The line number it had in that commit.
        content: The line's text without the newline.
    """

    line: int
    commit: str
    original_path: str
    original_line: int
    content: str


@dataclass(frozen=True)
class SkippedCommit:
    """A mechanical commit the walk looked through.

    Attributes:
        commit: The commit's SHA.
        reason: Why it counted as mechanical.
    """

    commit: str
    reason: str


@dataclass(frozen=True)
class BlameResult:
    """The commit that really wrote a line.

    Attributes:
        commit: The non-mechanical commit's SHA.
        path: The path the line had in that commit.
        line: The line number it had in that commit.
        skipped: Mechanical commits passed on the way, nearest first.
    """

    commit: str
    path: str
    line: int
    skipped: tuple[SkippedCommit, ...] = ()


def _numstat(clone: Path, *args: str) -> list[tuple[int, int]]:
    """Run ``git diff --numstat`` and return ``(added, deleted)`` per file (binary as 0, 0)."""
    result = git(clone, "diff", "--numstat", *args)
    if result.returncode != 0:
        return []
    rows: list[tuple[int, int]] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added = int(parts[0]) if parts[0].isdigit() else 0
        deleted = int(parts[1]) if parts[1].isdigit() else 0
        rows.append((added, deleted))
    return rows


def _parent_of(clone: Path, sha: str) -> str | None:
    """Return the first parent of ``sha``, or ``None`` for a root commit."""
    result = git(clone, "rev-parse", "--verify", "--quiet", f"{sha}^")
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def is_mechanical(clone: Path, sha: str) -> MechanicalVerdict:
    """Decide whether a commit is mechanical and should be looked through.

    A commit is mechanical when its subject matches ``MECHANICAL_MESSAGE``, when it changes
    more than ``MAX_FILES_CHANGED`` files, or when ignoring whitespace leaves at most
    ``WHITESPACE_CHANGE_RATIO`` of its changed lines. A root commit is compared with the
    empty tree.

    Args:
        clone: A clone containing ``sha``.
        sha: The commit to classify.

    Returns:
        The verdict, carrying the first matching reason.
    """
    subject = git(clone, "show", "-s", "--format=%s", sha).stdout.strip()
    if MECHANICAL_MESSAGE.match(subject):
        return MechanicalVerdict(f"message: {subject}")

    parent = _parent_of(clone, sha) or EMPTY_TREE
    plain = _numstat(clone, parent, sha)
    if len(plain) > MAX_FILES_CHANGED:
        return MechanicalVerdict(f"{len(plain)} files changed")

    total = sum(added + deleted for added, deleted in plain)
    if total > 0:
        ignoring_whitespace = sum(a + d for a, d in _numstat(clone, "-w", parent, sha))
        if ignoring_whitespace <= WHITESPACE_CHANGE_RATIO * total:
            return MechanicalVerdict("whitespace-only changes")
    return MechanicalVerdict(None)


def _parse_porcelain(text: str) -> list[BlameLine]:
    """Parse ``git blame --line-porcelain`` output into one entry per line."""
    lines: list[BlameLine] = []
    commit = ""
    original_line = final_line = 0
    filename = ""
    for raw in text.split("\n"):
        if raw.startswith("\t"):
            content = raw[1:].rstrip("\r")
            lines.append(BlameLine(final_line, commit, filename, original_line, content))
            continue
        header = _HEADER.match(raw)
        if header:
            commit, original_line, final_line = header[1], int(header[2]), int(header[3])
        elif raw.startswith("filename "):
            filename = raw[len("filename ") :]
    return lines


def _blame(clone: Path, rev: str, path: str, *range_args: str) -> list[BlameLine]:
    """Run blame and return its lines; empty when git cannot blame the path at ``rev``."""
    result = git(
        clone,
        "blame",
        "--line-porcelain",
        "-w",
        f"-M{MOVE_COPY_MIN_CHARS}",
        f"-C{MOVE_COPY_MIN_CHARS}",
        *range_args,
        rev,
        "--",
        path,
    )
    if result.returncode != 0:
        return []
    return _parse_porcelain(result.stdout)


def blame_file(clone: Path, rev: str, path: str) -> list[BlameLine]:
    """Blame every line of a file in one run.

    Args:
        clone: A clone containing ``rev``.
        rev: The revision to blame at.
        path: Repo-relative POSIX path at ``rev``.

    Returns:
        One entry per line; empty when the file does not exist at ``rev``.
    """
    return _blame(clone, rev, path)


def _follow_line(clone: Path, rev: str, path: str, line: int, content: str) -> BlameLine | None:
    """Re-blame a line at a parent revision, allowing for lines that shifted.

    The parent's line number can differ from the one the commit recorded, because the
    commit may have added or removed lines above it. The line whose text matches (ignoring
    surrounding whitespace) and is nearest to the recorded number wins; when no text
    matches, the recorded number is used.
    """
    lines = blame_file(clone, rev, path)
    if not lines:
        return None
    wanted = content.strip()
    matches = [item for item in lines if item.content.strip() == wanted] if wanted else []
    if matches:
        return min(matches, key=lambda item: abs(item.line - line))
    return next((item for item in lines if item.line == line), None)


def blame_line(
    clone: Path,
    rev: str,
    path: str,
    line: int,
    *,
    max_hops: int = 3,
    mechanical: Callable[[Path, str], MechanicalVerdict] = is_mechanical,
) -> BlameResult | None:
    """Find the non-mechanical commit that wrote a line.

    Args:
        clone: A clone containing ``rev``.
        rev: The revision to blame at.
        path: Repo-relative POSIX path at ``rev``.
        line: 1-based line number at ``rev``.
        max_hops: How many mechanical commits may be looked through.
        mechanical: The predicate that classifies a commit; replaceable for tests.

    Returns:
        The commit, its path and line, and the commits skipped on the way; ``None`` when
        git cannot blame the line, the walk reaches a root commit while still mechanical,
        or more than ``max_hops`` mechanical commits are met.
    """
    # The whole file is blamed rather than one line: git only detects a moved or copied
    # block when the block itself is long enough, and a single-line range hides that.
    first = next((item for item in blame_file(clone, rev, path) if item.line == line), None)
    if first is None:
        return None
    current = first
    skipped: list[SkippedCommit] = []
    for hop in range(max_hops + 1):
        verdict = mechanical(clone, current.commit)
        if not verdict.mechanical:
            return BlameResult(
                commit=current.commit,
                path=current.original_path,
                line=current.original_line,
                skipped=tuple(skipped),
            )
        skipped.append(SkippedCommit(current.commit, verdict.reason or ""))
        if hop == max_hops:
            return None
        parent = _parent_of(clone, current.commit)
        if parent is None:
            return None
        followed = _follow_line(
            clone, parent, current.original_path, current.original_line, current.content
        )
        if followed is None:
            return None
        current = followed
    return None


def _parents(clone: Path, sha: str) -> list[str]:
    """Return the parents of ``sha`` in order."""
    result = git(clone, "rev-list", "--parents", "-n", "1", sha)
    return result.stdout.split()[1:] if result.returncode == 0 else []


def pr_for_commit(
    clone: Path, sha: str, merge_sha_to_pr: Mapping[str, int], tip: str
) -> int | None:
    """Find the pull request a commit landed through.

    A commit that is itself a pull request's merge commit (squash and rebase merges) maps
    directly. Otherwise the first merge commit on the ancestry path from ``sha`` to
    ``tip`` that is a pull request's merge commit and that brought ``sha`` in through a
    side parent (reachable from a later parent, not from the first) is used.

    Args:
        clone: A clone containing both commits.
        sha: The commit to place.
        merge_sha_to_pr: Pull request merge commit SHA to pull request number.
        tip: The tip of the branch the pull requests merged into.

    Returns:
        The pull request number, or ``None`` when no pull request owns the commit.
    """
    if sha in merge_sha_to_pr:
        return merge_sha_to_pr[sha]
    result = git(clone, "rev-list", "--ancestry-path", "--merges", "--reverse", f"{sha}..{tip}")
    if result.returncode != 0:
        return None
    for merge in result.stdout.split():
        number = merge_sha_to_pr.get(merge)
        if number is None:
            continue
        parents = _parents(clone, merge)
        if len(parents) < 2 or is_ancestor(clone, sha, parents[0]):
            continue
        if any(is_ancestor(clone, sha, parent) for parent in parents[1:]):
            return number
    return None
