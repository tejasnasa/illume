"""Path normalisation and the split between files present at the base commit and not."""

import posixpath
from collections.abc import Iterable, Mapping
from pathlib import Path

from evals.mining.github_cache import CachedPRFile

_DIFF_PREFIXES = ("a/", "b/")


def normalise_path(
    raw: str, repo_root: str | Path | None = None, *, strip_diff_prefix: bool = True
) -> str:
    """Turn a path into repo-relative POSIX form.

    Backslashes become ``/``, a leading ``repo_root`` is removed, ``./`` and leading ``/``
    are stripped, and one ``a/`` or ``b/`` diff prefix is dropped.

    Args:
        raw: The path as found in a diff, a payload or a model's answer.
        repo_root: When given, an absolute path under it is made relative to it.
        strip_diff_prefix: Whether to drop a leading ``a/`` or ``b/``. Turn this off for
            paths that are already repo-relative, where ``a/`` may be a real directory.

    Returns:
        The normalised path; empty when ``raw`` is empty.
    """
    text = raw.strip().replace("\\", "/")
    if repo_root is not None:
        root = str(repo_root).replace("\\", "/").rstrip("/")
        if root and text.lower().startswith(root.lower() + "/"):
            text = text[len(root) + 1 :]
    text = text.lstrip("/")
    if not text:
        return ""
    text = posixpath.normpath(text)
    if text == ".":
        return ""
    if strip_diff_prefix:
        for prefix in _DIFF_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix) :]
                break
    return text.lstrip("/")


def split_by_existence(
    paths: Iterable[str], files_at_base: set[str] | frozenset[str]
) -> tuple[list[str], list[str]]:
    """Separate paths that exist at the base commit from those that do not.

    Args:
        paths: Repo-relative POSIX paths.
        files_at_base: Every file in the tree at the base commit.

    Returns:
        ``(present, absent_at_base)``, each in first-seen order without duplicates. Absent
        files cannot have been retrieved, so they are kept aside rather than scored.
    """
    present: list[str] = []
    absent: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        (present if path in files_at_base else absent).append(path)
    return present, absent


def resolve_pr_paths(
    files: Iterable[CachedPRFile], files_at_base: set[str] | frozenset[str]
) -> tuple[list[str], list[str]]:
    """Map a pull request's files to their paths at the base commit.

    A file the pull request renamed is reported under its old path when that path existed
    at the base commit, because that is where retrieval would have found it. Anything
    else is checked at its new path.

    Args:
        files: The pull request's files.
        files_at_base: Every file in the tree at the base commit.

    Returns:
        ``(present, absent_at_base)`` as for ``split_by_existence``; absent entries are
        the paths as the pull request names them.
    """
    resolved: list[str] = []
    for item in files:
        path = normalise_path(item.path, strip_diff_prefix=False)
        previous = (
            normalise_path(item.previous_path, strip_diff_prefix=False)
            if item.previous_path
            else None
        )
        if previous and previous != path and previous in files_at_base:
            resolved.append(previous)
        else:
            resolved.append(path)
    return split_by_existence(resolved, files_at_base)


def rename_map(files: Iterable[CachedPRFile]) -> Mapping[str, str]:
    """Map each renamed file's new path to its previous path.

    Args:
        files: The pull request's files.

    Returns:
        New path to previous path, for files that carry a ``previous_path``.
    """
    return {
        normalise_path(f.path, strip_diff_prefix=False): normalise_path(
            f.previous_path, strip_diff_prefix=False
        )
        for f in files
        if f.previous_path
    }
