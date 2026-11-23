"""Harness-owned full clones and the read-only git queries run against them.

Every helper shells out to ``git -C <clone> ...`` with list-form arguments, so nothing
passes through a shell. A clone is made with ``--no-checkout``: mining only reads objects,
and skipping the working tree keeps large repositories cheap.
"""

import subprocess
from pathlib import Path

GIT_TIMEOUT_SECONDS = 120
CLONE_TIMEOUT_SECONDS = 1800


def git(
    clone_path: Path, *args: str, timeout: float = GIT_TIMEOUT_SECONDS
) -> subprocess.CompletedProcess:
    """Run git inside a clone and return the finished process without raising.

    Args:
        clone_path: The repository directory.
        *args: Arguments after ``git -C <clone_path>``.
        timeout: Seconds before the call is abandoned.

    Returns:
        The completed process with text output decoded as UTF-8 (undecodable bytes are
        replaced rather than raising).
    """
    return subprocess.run(
        ["git", "-C", str(clone_path), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def clone_dir(clones_dir: Path, slug: str) -> Path:
    """Return where the clone for ``slug`` lives.

    Args:
        clones_dir: The directory holding every clone.
        slug: ``owner/repo``.

    Returns:
        ``<clones_dir>/<owner>__<repo>``, matching the GitHub cache's layout.
    """
    return Path(clones_dir) / slug.replace("/", "__")


def ensure_clone(url: str, clones_dir: Path, *, slug: str) -> Path:
    """Clone a repository fully without a checkout, or refresh an existing clone.

    Args:
        url: The clone URL or a local path.
        clones_dir: The directory holding every clone.
        slug: ``owner/repo``, which names the clone's directory.

    Returns:
        The clone's path.

    Raises:
        RuntimeError: If git fails to clone or fetch.
    """
    target = clone_dir(clones_dir, slug)
    if (target / ".git").exists() or (target / "HEAD").exists():
        # `--force` lets an upstream tag rewrite overwrite the local tag. The clone is a
        # read-only mirror and every revision the harness uses is pinned by SHA.
        result = git(
            target,
            "fetch",
            "--prune",
            "--tags",
            "--force",
            "origin",
            timeout=CLONE_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git fetch failed for {slug}: {result.stderr.strip()}")
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "clone", "--no-checkout", url, str(target)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=CLONE_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git clone failed for {slug}: {result.stderr.strip()}")
    return target


def rev_exists(clone_path: Path, rev: str) -> bool:
    """Whether ``rev`` names an object the clone contains.

    Args:
        clone_path: The clone.
        rev: A SHA or any revision expression.

    Returns:
        ``True`` when git can resolve it to a commit.
    """
    if not rev:
        return False
    return git(clone_path, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").returncode == 0


def is_ancestor(clone_path: Path, sha: str, base_commit: str) -> bool:
    """Whether ``sha`` is an ancestor of, or equal to, ``base_commit``.

    Uses ``git merge-base --is-ancestor``, which is immune to the timestamp skew that
    rebases and clock drift introduce. A SHA the clone does not contain counts as not an
    ancestor.

    Args:
        clone_path: A clone that contains ``base_commit``.
        sha: The commit to test.
        base_commit: The commit to test against.

    Returns:
        ``True`` only when git exits 0.
    """
    if not sha:
        return False
    return git(clone_path, "merge-base", "--is-ancestor", sha, base_commit).returncode == 0


def default_tip(clone_path: Path) -> str | None:
    """Return the commit at the tip of the remote's default branch.

    Args:
        clone_path: A clone made by ``ensure_clone``.

    Returns:
        The tip SHA, falling back to ``HEAD`` when the remote head is not recorded, or
        ``None`` when neither resolves.
    """
    for ref in ("refs/remotes/origin/HEAD", "HEAD"):
        result = git(clone_path, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return None


def files_at(clone_path: Path, rev: str) -> set[str]:
    """List every file in the tree at ``rev``.

    Args:
        clone_path: The clone.
        rev: A commit-ish.

    Returns:
        Repo-relative POSIX paths; empty when ``rev`` does not resolve.
    """
    result = git(clone_path, "-c", "core.quotepath=off", "ls-tree", "-r", "--name-only", "-z", rev)
    if result.returncode != 0:
        return set()
    return {path for path in result.stdout.split("\0") if path}


def show_file(clone_path: Path, rev: str, path: str) -> str | None:
    """Return a file's text at a revision.

    Args:
        clone_path: The clone.
        rev: A commit-ish.
        path: Repo-relative POSIX path.

    Returns:
        The file's contents, or ``None`` when it does not exist at ``rev``.
    """
    result = git(clone_path, "show", f"{rev}:{path}")
    if result.returncode != 0:
        return None
    return result.stdout
