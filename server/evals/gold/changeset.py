"""Change-set items: a merged pull request's description, asked as "which files change?".

The gold is the files the pull request changed that already existed at the base commit,
less changelogs, lockfiles and generated files. The question seed is the title and body
with everything that would give the answer away removed: gold paths, gold basenames and
identifiers that occur only in gold files.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath

from app.services.test_files import is_test_path
from evals.gold.schema import GoldItem, make_item
from evals.mining.clones import files_at, git
from evals.mining.github_cache import CachedPR
from evals.mining.paths import resolve_pr_paths

MIN_GOLD_FILES = 2
MAX_GOLD_FILES = 15
MIN_BODY_WORDS = 20
MIN_IDENTIFIER_LENGTH = 3

LOCKFILE_NAMES = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "uv.lock",
        "poetry.lock",
        "Pipfile.lock",
        "Cargo.lock",
        "go.sum",
        "Gemfile.lock",
        "composer.lock",
    }
)
_CHANGELOG_STEMS = frozenset({"changelog", "changes", "history", "news"})
_CHANGELOG_EXTENSIONS = frozenset({"", ".md", ".markdown", ".rst", ".txt", ".adoc"})
GENERATED_NAME_PATTERNS = (
    re.compile(r".*_pb2\.py$"),
    re.compile(r".*_pb2_grpc\.py$"),
    re.compile(r".*\.pb\.go$"),
    re.compile(r".*\.min\.js$"),
    re.compile(r".*\.min\.css$"),
    re.compile(r".*\.generated\..*"),
    re.compile(r".*\.snap$"),
)
GENERATED_DIRS = frozenset({"__snapshots__", "dist", "build", "vendor", "node_modules"})
DOC_EXTENSIONS = frozenset({".md", ".rst", ".txt", ".adoc"})

ANCHOR_SENTENCE = "Start from `{path}`."

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_CHECKLIST = re.compile(r"^[ \t]*[-*+][ \t]*\[[ xX]\].*$", re.MULTILINE)
_MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_HTML_IMAGE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_REPO_URL = r"https?://github\.com/[^\s)\]>]*/(?:blob|tree|pull|pulls|commit|commits)/[^\s)\]>]*"
_REPO_LINK = re.compile(rf"\[([^\]]*)\]\(\s*{_REPO_URL}\s*\)")
_REPO_BARE_URL = re.compile(_REPO_URL)
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_BACKTICK_SPAN = re.compile(r"`([^`\n]+)`")


@dataclass(frozen=True)
class ChangesetBuild:
    """The result of building change-set items.

    Attributes:
        items: The items, two per kept pull request (one when removing the anchor would
            leave no gold file).
        drops: ``(pull request number, reason)`` for every pull request not kept, in the
            order they were examined.
    """

    items: list[GoldItem] = field(default_factory=list)
    drops: list[tuple[int, str]] = field(default_factory=list)


# --- what is stripped from the gold -----------------------------------------------


def is_lockfile(path: str) -> bool:
    """Whether a path is a dependency lockfile."""
    return PurePosixPath(path).name in LOCKFILE_NAMES


def is_changelog(path: str) -> bool:
    """Whether a path is a changelog, in any directory and any case."""
    posix = PurePosixPath(path.lower())
    if posix.name.startswith("changelog"):
        return True
    return posix.stem in _CHANGELOG_STEMS and posix.suffix in _CHANGELOG_EXTENSIONS


def is_generated(path: str) -> bool:
    """Whether a path is generated or vendored output."""
    posix = PurePosixPath(path)
    if any(part in GENERATED_DIRS for part in posix.parts[:-1]):
        return True
    return any(pattern.match(posix.name) for pattern in GENERATED_NAME_PATTERNS)


def is_noise(path: str) -> bool:
    """Whether a path is stripped from the gold: a changelog, lockfile or generated file."""
    return is_lockfile(path) or is_changelog(path) or is_generated(path)


def is_doc(path: str) -> bool:
    """Whether a path is documentation: a prose extension, or anything under ``docs/``."""
    posix = PurePosixPath(path)
    return posix.suffix.lower() in DOC_EXTENSIONS or "docs" in posix.parts[:-1]


def is_bot(pr: CachedPR) -> bool:
    """Whether a pull request was opened by a bot account."""
    return pr.user_type == "Bot" or pr.author.lower().endswith("[bot]")


# --- ordering on the mainline ------------------------------------------------------


def mainline_positions(
    clone: Path, base_commit: str, tip: str, merge_shas: set[str]
) -> dict[str, int]:
    """Position of each pull request merge among the mainline merges after the base commit.

    Args:
        clone: A clone containing both commits.
        base_commit: The commit ``B``.
        tip: The tip of the default branch.
        merge_shas: Merge commit SHAs of the pull requests that count.

    Returns:
        Merge SHA to its 0-based position among the first-parent commits of
        ``B..tip`` that are in ``merge_shas``, oldest first. A SHA not on the first-parent
        line is absent.
    """
    result = git(clone, "rev-list", "--first-parent", "--reverse", f"{base_commit}..{tip}")
    ordered = [sha for sha in result.stdout.split() if sha in merge_shas]
    return {sha: index for index, sha in enumerate(ordered)}


# --- the question seed -------------------------------------------------------------


def identifier_tokens(text: str) -> list[str]:
    """Find the identifier-shaped tokens in a text.

    A token qualifies when it is at least ``MIN_IDENTIFIER_LENGTH`` characters and contains
    an underscore, a capital letter after its first character or a dot (dotted names are
    reported whole and as each part), or when it sits inside backticks.

    Args:
        text: Prose that may mention code.

    Returns:
        The distinct qualifying tokens, sorted.
    """
    backticked: set[str] = set()
    for span in _BACKTICK_SPAN.finditer(text):
        for token in _TOKEN.findall(span.group(1)):
            backticked.add(token)
            backticked.update(token.split("."))

    found: set[str] = set()
    for match in _TOKEN.finditer(text):
        token = match.group(0)
        parts = token.split(".")
        for candidate in {token, *parts}:
            if len(candidate) < MIN_IDENTIFIER_LENGTH:
                continue
            shaped = (
                "_" in candidate
                or "." in candidate
                or len(parts) > 1
                or any(char.isupper() for char in candidate[1:])
            )
            if shaped or candidate in backticked:
                found.add(candidate)
    return sorted(found)


def _present(term: str, text: str) -> bool:
    """Whether ``term`` occurs in ``text`` not embedded in a longer word."""
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None


def _remove(term: str, text: str) -> str:
    """Delete every whole-word occurrence of ``term``."""
    return re.sub(rf"(?<!\w){re.escape(term)}(?!\w)", "", text)


class IdentifierIndex:
    """Answers whether an identifier occurs only in a set of gold files at a commit.

    Attributes:
        clone: The clone searched.
        base_commit: The commit searched.
        gold_paths: The files whose identifiers are gold-unique when found nowhere else.
    """

    def __init__(self, clone: Path, base_commit: str, gold_paths: Sequence[str]) -> None:
        self.clone = clone
        self.base_commit = base_commit
        self.gold_paths = tuple(sorted(set(gold_paths)))
        self._gold_text: str | None = None
        self._cache: dict[str, bool] = {}

    def _text(self) -> str:
        """The gold files' contents at the base commit, joined."""
        if self._gold_text is None:
            chunks = []
            for path in self.gold_paths:
                shown = git(self.clone, "show", f"{self.base_commit}:{path}")
                if shown.returncode == 0:
                    chunks.append(shown.stdout)
            self._gold_text = "\n".join(chunks)
        return self._gold_text

    def is_gold_unique(self, token: str) -> bool:
        """Whether ``token`` occurs in a gold file at the base commit and in no other file.

        Args:
            token: An identifier.

        Returns:
            ``True`` only when every file containing it (as a whole word) is a gold file
            and at least one gold file does.
        """
        if token in self._cache:
            return self._cache[token]
        unique = False
        if _present(token, self._text()):
            found = git(
                self.clone,
                "-c",
                "core.quotepath=off",
                "grep",
                "-w",
                "-l",
                "-F",
                "-e",
                token,
                self.base_commit,
                "--",
            )
            prefix = f"{self.base_commit}:"
            holders = {
                line.removeprefix(prefix).strip()
                for line in found.stdout.splitlines()
                if line.strip()
            }
            unique = found.returncode == 0 and bool(holders) and holders <= set(self.gold_paths)
        self._cache[token] = unique
        return unique


@dataclass(frozen=True)
class LeakContext:
    """What a question must not reveal.

    Attributes:
        gold_paths: Paths whose full path, basename and stem must not appear.
        is_gold_unique: Whether an identifier occurs only in gold files.
    """

    gold_paths: tuple[str, ...]
    is_gold_unique: Callable[[str], bool]


def _names_of(path: str) -> tuple[str, str | None]:
    """Return a path's basename and, when it has an extension and is long enough, its stem."""
    posix = PurePosixPath(path)
    stem = posix.stem if posix.stem != posix.name else None
    if stem is not None and len(stem) < MIN_IDENTIFIER_LENGTH:
        stem = None
    return posix.name, stem


def leaked_terms(text: str, item_context: LeakContext) -> list[str]:
    """Report anything in ``text`` that gives a gold file away.

    Args:
        text: A seed or a phrased question.
        item_context: The gold paths and the gold-unique test.

    Returns:
        The distinct leaked gold paths, basenames, stems and gold-unique identifiers still
        present, sorted. Empty means the text is clean.
    """
    leaks: set[str] = set()
    for path in item_context.gold_paths:
        basename, stem = _names_of(path)
        for term in (path, basename, stem):
            if term and _present(term, text):
                leaks.add(term)
    for token in identifier_tokens(text):
        if item_context.is_gold_unique(token):
            leaks.add(token)
    return sorted(leaks)


def _tidy(text: str) -> str:
    """Collapse the gaps left by removals: empty backticks, repeated spaces and blank lines."""
    text = re.sub(r"`\s*`", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" +([,.;:!?)])", r"\1", text)
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_seed(pr: CachedPR, gold_paths: Sequence[str], index: IdentifierIndex) -> str:
    """Make the question seed from a pull request, without anything that names the answer.

    Args:
        pr: The pull request.
        gold_paths: Every gold path of the pull request (the anchor included).
        index: The gold-unique identifier lookup for the same files.

    Returns:
        The title and body with comments, checklists, images, repository links, gold
        paths, gold basenames and stems, and gold-unique identifiers removed.
    """
    text = f"{pr.title}\n\n{pr.body}"
    text = _HTML_COMMENT.sub("", text)
    text = _CHECKLIST.sub("", text)
    text = _MARKDOWN_IMAGE.sub("", text)
    text = _HTML_IMAGE.sub("", text)
    text = _REPO_LINK.sub(r"\1", text)
    text = _REPO_BARE_URL.sub("", text)

    for path in sorted(gold_paths, key=len, reverse=True):
        text = _remove(path, text)
    names: set[str] = set()
    for path in gold_paths:
        basename, stem = _names_of(path)
        names.add(basename)
        if stem:
            names.add(stem)
    for name in sorted(names, key=len, reverse=True):
        text = _remove(name, text)

    for token in sorted(identifier_tokens(text), key=len, reverse=True):
        if index.is_gold_unique(token):
            text = _remove(token, text)
    return _tidy(text)


# --- building the items --------------------------------------------------------------


def build_changeset_items(
    *,
    repo_name: str,
    clone: Path,
    base_commit: str,
    prs: Sequence[CachedPR],
    drift_window: int,
    generator_cutoff: date,
    tip: str,
) -> ChangesetBuild:
    """Build the change-set items for the pull requests merged after the base commit.

    Args:
        repo_name: The corpus entry's name.
        clone: A full clone containing the base commit and ``tip``.
        base_commit: The commit ``B``.
        prs: The cached pull requests merged after ``B``, with their files.
        drift_window: Pull requests at or beyond this many mainline merges after ``B``
            are dropped.
        generator_cutoff: Pull requests merged after this date are flagged post-cutoff.
        tip: The tip of the default branch.

    Returns:
        The items and the reason for every dropped pull request.
    """
    at_base = files_at(clone, base_commit)
    positions = mainline_positions(clone, base_commit, tip, {pr.merge_commit_sha for pr in prs})
    build = ChangesetBuild()

    for pr in sorted(prs, key=lambda candidate: candidate.number):
        reason = _screen(pr, positions, drift_window)
        gold: list[str] = []
        absent: list[str] = []
        if reason is None:
            assert pr.files is not None
            present, missing = resolve_pr_paths(pr.files, at_base)
            gold = [path for path in present if not is_noise(path)]
            absent = [path for path in missing if not is_noise(path)]
            if len(gold) < MIN_GOLD_FILES:
                reason = "too_few_files"
            elif len(gold) > MAX_GOLD_FILES:
                reason = "too_many_files"
            elif len(pr.body.split()) < MIN_BODY_WORDS:
                reason = "short_description"
        if reason is not None:
            build.drops.append((pr.number, reason))
            continue

        index = IdentifierIndex(clone, base_commit, gold)
        seed = build_seed(pr, gold, index)
        if not seed:
            build.drops.append((pr.number, "empty_seed"))
            continue
        build.items.extend(
            _items_for(
                repo_name=repo_name,
                base_commit=base_commit,
                pr=pr,
                gold=sorted(gold),
                absent=absent,
                seed=seed,
                merges_since_base=positions[pr.merge_commit_sha],
                post_cutoff=pr.merged_at.date() > generator_cutoff,
            )
        )
    return build


def _screen(pr: CachedPR, positions: dict[str, int], drift_window: int) -> str | None:
    """Return why a pull request is dropped before its gold is worked out, or ``None``."""
    if pr.merge_commit_sha not in positions:
        return "not_on_mainline"
    if positions[pr.merge_commit_sha] >= drift_window:
        return "beyond_drift_window"
    if is_bot(pr):
        return "bot"
    if not pr.files:
        return "no_files"
    paths = [item.path for item in pr.files]
    if all(is_lockfile(path) for path in paths):
        return "lockfile_only"
    if all(is_doc(path) for path in paths):
        return "docs_only"
    if all(is_generated(path) for path in paths):
        return "generated_only"
    return None


def _items_for(
    *,
    repo_name: str,
    base_commit: str,
    pr: CachedPR,
    gold: list[str],
    absent: list[str],
    seed: str,
    merges_since_base: int,
    post_cutoff: bool,
) -> list[GoldItem]:
    """Make the blind item and, when a gold file remains once it is removed, the anchor one."""
    common = {
        "repo": repo_name,
        "base_commit": base_commit,
        "family": "changeset",
        "absent_at_base": tuple(absent),
        "gold_prs": (pr.number,),
        "gold_commits": (pr.merge_commit_sha,),
        "post_cutoff": post_cutoff,
        "merges_since_base": merges_since_base,
        "cluster": f"{repo_name}#{pr.number}",
    }

    def tests_of(paths: list[str]) -> tuple[str, ...]:
        return tuple(path for path in paths if is_test_path(path))

    items = [
        make_item(
            **common,
            template="changeset.blind",
            question_seed=seed,
            gold_files=tuple(gold),
            gold_test_files=tests_of(gold),
        )
    ]
    non_tests = [path for path in gold if not is_test_path(path)]
    anchor = (non_tests or gold)[0]
    remaining = [path for path in gold if path != anchor]
    if remaining:
        items.append(
            make_item(
                **common,
                template="changeset.anchor",
                question_seed=f"{seed}\n\n{ANCHOR_SENTENCE.format(path=anchor)}",
                gold_files=tuple(remaining),
                gold_test_files=tests_of(remaining),
                anchor_file=anchor,
            )
        )
    return items
