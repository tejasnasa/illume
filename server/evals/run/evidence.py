"""The text behind a citation key, read from the harness clone and the pull request cache.

The generation records keep only keys, not the chunks they stand for, so the judge pass looks the
text up again: code from the clone at the base commit, commit messages from the clone, pull
requests from the cached pull request data. A key with no text is reported as unknown by returning
``None``; the judge's prompt then says the text is unavailable.

Library code here takes nothing from ``evals.settings``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from app.services.retrieval.citations import parse_key
from evals.gold.schema import GoldItem
from evals.mining import clones
from evals.mining.github_cache import CachedPR, load_prs
from evals.run.judge import EvidenceText

WHOLE_FILE_LINES = 120
"""How many lines of a file cited without a range are shown."""


def clone_evidence(
    clone: Path, base_commit: str, pull_requests: Mapping[int, CachedPR] | None = None
) -> EvidenceText:
    """A lookup from a citation key to its text, for one repository at its base commit.

    Args:
        clone: The harness clone.
        base_commit: The commit the repository was ingested at.
        pull_requests: Cached pull requests by number.

    Returns:
        A function from a key as written to its text, or ``None`` when it cannot be read.
    """
    prs = pull_requests or {}

    def lookup(raw: str) -> str | None:
        key = parse_key(raw)
        if key is None:
            return None
        if key.kind == "F" and key.path:
            text = clones.show_file(clone, base_commit, key.path)
            if text is None:
                return None
            lines = text.splitlines()
            if key.start is None or key.end is None:
                return "\n".join(lines[:WHOLE_FILE_LINES])
            return "\n".join(lines[key.start - 1 : key.end])
        if key.kind == "C" and key.commit:
            result = clones.git(clone, "show", "-s", "--format=%an%n%B", key.commit)
            return result.stdout.strip() if result.returncode == 0 else None
        if key.kind == "PR" and key.pr_number in prs:
            pr = prs[key.pr_number]
            return f"PR #{pr.number}: {pr.title}\n{pr.body}".strip()
        return None

    return lookup


def evidence_for_items(
    *,
    clones_dir: Path,
    github_cache_dir: Path,
    repos: Mapping[str, tuple[str, str]],
) -> Callable[[GoldItem], EvidenceText]:
    """The per-item lookup the judge pass takes.

    Args:
        clones_dir: Where the harness clones live.
        github_cache_dir: The cached pull request data.
        repos: Corpus entry name to ``(slug, base_commit)``.

    Returns:
        A function that gives an item's lookup; an item of an unknown repository gets one that
        knows nothing.
    """
    built: dict[str, EvidenceText] = {}

    def for_item(item: GoldItem) -> EvidenceText:
        if item.repo in built:
            return built[item.repo]
        known = repos.get(item.repo)
        if known is None:
            built[item.repo] = lambda raw: None
        else:
            slug, base = known
            prs = {pr.number: pr for pr in load_prs(github_cache_dir, slug)}
            built[item.repo] = clone_evidence(clones.clone_dir(clones_dir, slug), base, prs)
        return built[item.repo]

    return for_item


__all__ = ["WHOLE_FILE_LINES", "clone_evidence", "evidence_for_items"]
