"""How the codebases differ: measurements of each repository at its base commit.

Everything here is free: it reads the symbols, files and pull requests the eval database holds for
a repository and the full commit messages from the harness clone, and calls no model. The numbers
describe the repositories and are shown beside the results as observations; they are never used
as a cause.

Comment lines are not stored by the parser, so they are counted from each function's stored source
with a per-language line-comment heuristic, plus the docstring or doc comment the parser stored
when that text is not already inside the function's source. Visible AI involvement is a lower
bound: a commit counts only when its message carries a ``Co-Authored-By`` trailer naming an AI, or
its author is an AI bot account. Work an AI did without leaving either trace is not counted.

Library code here takes nothing from ``evals.settings``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AstSymbol, File, PullRequest
from evals.mining.clones import git
from evals.stats import wilson_interval

STYLE_VERSION = 1
FUNCTION_KINDS = ("function", "method")
IDENTIFIER_KINDS = ("function", "method", "class", "variable")
RECENT_DAYS = 365
"""How far back from the base commit the recent window reaches, in days."""

_HASH_LANGUAGES = frozenset(
    {"python", "ruby", "shell", "bash", "sh", "yaml", "perl", "r", "elixir", "toml", "makefile"}
)
_HASH_EXTENSIONS = frozenset({".py", ".rb", ".sh", ".bash", ".yaml", ".yml", ".pl", ".r", ".ex"})

AI_SIGNATURES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(pattern, re.IGNORECASE))
    for label, pattern in (
        (
            "claude",
            r"anthropic|claude\[bot\]|claude[ -](?:code|opus|sonnet|haiku|\d)|^\s*claude\s*(?:<|$)",
        ),
        ("copilot", r"copilot"),
        ("cursor", r"cursor(?:\s?agent|\.com|\[bot\])|^\s*cursor\s*(?:<|$)"),
        ("codex", r"codex"),
        ("devin", r"devin-ai|devin\.ai|devin\[bot\]|^\s*devin(?:\s+ai)?\s*(?:<|$)"),
        ("gemini", r"gemini"),
        ("chatgpt", r"chatgpt|openai"),
        ("jules", r"google-labs-jules|jules\[bot\]|jules@google"),
        ("aider", r"\baider\b"),
        ("windsurf", r"windsurf|codeium"),
        ("amazon q", r"amazon[ -]?q\b|amazonq"),
        ("kiro", r"\bkiro\b"),
    )
)
"""The AI tools a trailer or a bot account is matched against: a label and its pattern."""

_TRAILER = re.compile(r"^\s*co-authored-by:\s*(?P<who>.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_LOG_FIELD = "\x1f"
_LOG_RECORD = "\x1e"


@dataclass(frozen=True)
class SymbolRow:
    """One stored symbol with the file it lives in.

    Attributes:
        kind: ``function``, ``method``, ``class``, ``variable`` and so on.
        name: The symbol's name.
        start_line: First line, when known.
        end_line: Last line, when known.
        source: The stored source of the symbol.
        docstring: The docstring or doc comment the parser attached, if any.
        path: The file's path.
        language: The file's language as stored.
    """

    kind: str
    name: str
    start_line: int | None
    end_line: int | None
    source: str | None
    docstring: str | None
    path: str
    language: str | None


@dataclass(frozen=True)
class CommitRow:
    """One commit as read from the clone.

    Attributes:
        author_name: The author's name.
        author_email: The author's email.
        authored_at: When it was authored.
        message: The whole message, subject and body.
    """

    author_name: str
    author_email: str
    authored_at: datetime
    message: str


# --- comments ---------------------------------------------------------------------------


def _comment_style(path: str, language: str | None) -> str:
    """``hash`` for ``#`` line comments, otherwise ``slash`` for ``//`` and ``/* */``."""
    if language and language.lower() in _HASH_LANGUAGES:
        return "hash"
    suffix = Path(path).suffix.lower()
    return "hash" if suffix in _HASH_EXTENSIONS else "slash"


def comment_lines(source: str, path: str, language: str | None) -> list[str]:
    """The lines of a piece of source that are comments, by a per-language line heuristic.

    A line counts when it is nothing but a comment: a ``#`` line for Python-like languages, a
    ``//`` line or a line inside a ``/* */`` block for the rest. Trailing comments after code are
    not counted.

    Args:
        source: The source text.
        path: The file's path, whose extension decides the style when the language is unknown.
        language: The language as stored, if any.

    Returns:
        The comment lines, stripped.
    """
    style = _comment_style(path, language)
    found: list[str] = []
    in_block = False
    for raw in source.splitlines():
        line = raw.strip()
        if not line:
            continue
        if style == "hash":
            if line.startswith("#") and not line.startswith("#!"):
                found.append(line)
            continue
        if in_block:
            found.append(line)
            if "*/" in line:
                in_block = False
        elif line.startswith("//"):
            found.append(line)
        elif line.startswith("/*"):
            found.append(line)
            in_block = "*/" not in line
    return found


def documentation_lines(row: SymbolRow) -> int:
    """Comment and docstring lines that belong to one function.

    The counted comment lines of its source, plus the lines of the stored docstring unless that
    text is already among them (a doc comment stored inside the function's own slice).

    Args:
        row: A function or method.

    Returns:
        How many lines.
    """
    comments = comment_lines(row.source or "", row.path, row.language)
    doc = [line.strip() for line in (row.docstring or "").splitlines() if line.strip()]
    if not doc:
        return len(comments)
    already = any(doc[0].strip("/*# ") and doc[0].strip("/*# ") in c for c in comments)
    return len(comments) + (0 if already else len(doc))


# --- the code ---------------------------------------------------------------------------


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def code_style(symbols: Iterable[SymbolRow], file_lengths: Sequence[int]) -> dict[str, Any]:
    """Function, file and identifier measurements of one repository.

    Args:
        symbols: Every stored symbol.
        file_lengths: Lines of code of each file.

    Returns:
        ``functions`` (count, documentation lines per function, mean length in lines),
        ``files`` (count, mean length) and ``identifiers`` (count, mean length in characters),
        each with the ``n`` it rests on and ``None`` for a mean it has no data for.
    """
    rows = list(symbols)
    functions = [r for r in rows if r.kind in FUNCTION_KINDS]
    lengths = [
        r.end_line - r.start_line + 1
        for r in functions
        if r.start_line is not None and r.end_line is not None and r.end_line >= r.start_line
    ]
    identifiers = [len(r.name) for r in rows if r.kind in IDENTIFIER_KINDS and r.name]
    docs = [documentation_lines(r) for r in functions]
    return {
        "functions": {
            "n": len(functions),
            "doc_lines_per_function": _mean(docs),
            "mean_length_lines": _mean(lengths),
            "n_with_length": len(lengths),
        },
        "files": {"n": len(file_lengths), "mean_length_lines": _mean(file_lengths)},
        "identifiers": {"n": len(identifiers), "mean_length_chars": _mean(identifiers)},
    }


# --- the history ------------------------------------------------------------------------


def ai_in_trailers(message: str) -> list[str]:
    """The AI tools named in a message's ``Co-Authored-By`` trailers.

    Args:
        message: A commit message.

    Returns:
        The label of each AI that a trailer names, once each, in the order they are listed.
    """
    found: list[str] = []
    for match in _TRAILER.finditer(message):
        who = match.group("who")
        for label, pattern in AI_SIGNATURES:
            if pattern.search(who) and label not in found:
                found.append(label)
    return found


def is_ai_author(name: str, email: str) -> bool:
    """Whether a commit's author is an AI bot account.

    An account counts when it is a bot (``[bot]`` in the name or email, or GitHub's no-reply
    address that bot accounts commit under) and matches the AI list, or when it commits as
    Anthropic's no-reply address. Bots that are not AI, such as dependency updaters, do not
    count.

    Args:
        name: The author's name.
        email: The author's email.

    Returns:
        Whether the author is an AI bot.
    """
    lowered = f"{name} {email}".lower()
    if "noreply@anthropic.com" in lowered:
        return True
    botlike = "[bot]" in lowered or "users.noreply.github.com" in lowered
    candidates = (name, email, f"{name} <{email}>")
    return botlike and any(p.search(c) for _, p in AI_SIGNATURES for c in candidates)


def commit_ai_signals(commit: CommitRow) -> list[str]:
    """Why a commit counts as visibly AI-involved: ``trailer``, ``bot_author``, or both."""
    signals = []
    if ai_in_trailers(commit.message):
        signals.append("trailer")
    if is_ai_author(commit.author_name, commit.author_email):
        signals.append("bot_author")
    return signals


def _share(k: int, n: int) -> dict[str, Any]:
    lo, hi = wilson_interval(k, n)
    return {"k": k, "n": n, "share": k / n if n else None, "lo": lo, "hi": hi}


def history_style(
    commits: Sequence[CommitRow], pull_requests: Sequence[tuple[str | None, int]]
) -> dict[str, Any]:
    """Commit and pull request measurements of one repository.

    Args:
        commits: Non-merge commits up to the base commit.
        pull_requests: ``(description, files changed)`` of each pull request before the base
            commit.

    Returns:
        ``commits`` (count, median message length in characters), ``pull_requests`` (count,
        median description length, median files changed) and ``ai_involvement`` (a lower bound:
        the share of all commits and of the last twelve months before the base commit that carry
        a trailer naming an AI or an AI bot author).
    """
    lengths = [len(c.message.strip()) for c in commits]
    base_date = max((c.authored_at for c in commits), default=None)
    flagged = [(c, commit_ai_signals(c)) for c in commits]
    k_all = sum(1 for _, signals in flagged if signals)
    ai: dict[str, Any] = {
        "lower_bound": True,
        "all": _share(k_all, len(commits)),
        "by_signal": {
            "trailer": sum(1 for _, s in flagged if "trailer" in s),
            "bot_author": sum(1 for _, s in flagged if "bot_author" in s),
        },
        "tools": sorted({label for c in commits for label in ai_in_trailers(c.message)}),
    }
    if base_date is not None:
        since = base_date - timedelta(days=RECENT_DAYS)
        recent = [(c, s) for c, s in flagged if c.authored_at >= since]
        ai["last_12_months"] = {
            **_share(sum(1 for _, s in recent if s), len(recent)),
            "since": since.date().isoformat(),
        }
    descriptions = [len((d or "").strip()) for d, _ in pull_requests]
    return {
        "commits": {
            "n": len(commits),
            "median_message_chars": median(lengths) if lengths else None,
            "base_date": base_date.date().isoformat() if base_date else None,
        },
        "pull_requests": {
            "n": len(pull_requests),
            "median_description_chars": median(descriptions) if descriptions else None,
            "median_files_changed": median(f for _, f in pull_requests) if pull_requests else None,
        },
        "ai_involvement": ai,
    }


# --- reading the sources ----------------------------------------------------------------


def read_commits(clone: Path, base_commit: str) -> list[CommitRow]:
    """The non-merge commits reachable from the base commit, with their whole messages.

    Args:
        clone: The harness clone.
        base_commit: The commit everything is frozen at.

    Returns:
        The commits, newest first; empty when the clone cannot be read.
    """
    result = git(
        clone,
        "log",
        base_commit,
        "--no-merges",
        f"--format=%an{_LOG_FIELD}%ae{_LOG_FIELD}%aI{_LOG_FIELD}%B{_LOG_RECORD}",
        timeout=600,
    )
    if result.returncode != 0:
        return []
    commits: list[CommitRow] = []
    for record in result.stdout.split(_LOG_RECORD):
        parts = record.lstrip("\n").split(_LOG_FIELD, 3)
        if len(parts) != 4:
            continue
        name, email, stamp, message = parts
        try:
            authored = datetime.fromisoformat(stamp.strip())
        except ValueError:
            continue
        commits.append(CommitRow(name, email, authored, message))
    return commits


def read_symbols(db: Session, repo_id: Any) -> tuple[list[SymbolRow], list[int]]:
    """Every stored symbol of a repository and the length of each of its files."""
    statement = (
        select(
            AstSymbol.kind,
            AstSymbol.name,
            AstSymbol.start_line,
            AstSymbol.end_line,
            AstSymbol.source_code,
            AstSymbol.docstring,
            File.path,
            File.language,
        )
        .join(File, File.id == AstSymbol.file_id)
        .where(File.repository_id == repo_id)
    )
    symbols = [SymbolRow(*row) for row in db.execute(statement).all()]
    lengths = [
        loc
        for (loc,) in db.execute(select(File.loc).where(File.repository_id == repo_id)).all()
        if loc is not None
    ]
    return symbols, lengths


def read_pull_requests(db: Session, repo_id: Any) -> list[tuple[str | None, int]]:
    """``(description, files changed)`` of every stored pull request of a repository."""
    rows = db.execute(
        select(PullRequest.description, PullRequest.files_changed).where(
            PullRequest.repository_id == repo_id
        )
    ).all()
    return [(description, int(changed or 0)) for description, changed in rows]


def repo_style(db: Session, repo_id: Any, clone: Path | None, base_commit: str) -> dict[str, Any]:
    """Every measurement for one ingested repository.

    Args:
        db: A sync session on the eval database.
        repo_id: The repository's id.
        clone: The harness clone, for the commit messages; without it the commit measurements
            are left out.
        base_commit: The commit the repository was ingested at.

    Returns:
        The code and history measurements, plus the base commit.
    """
    symbols, file_lengths = read_symbols(db, repo_id)
    out = code_style(symbols, file_lengths)
    commits = read_commits(clone, base_commit) if clone is not None else []
    history = history_style(commits, read_pull_requests(db, repo_id))
    if not commits:
        history.pop("ai_involvement")
        history.pop("commits")
    out.update(history)
    out["base_commit"] = base_commit
    return out


def write_style(path: Path, styles: dict[str, dict[str, Any]]) -> None:
    """Write the per-repository measurements as the JSON the report reads."""
    document = {"version": STYLE_VERSION, "repos": styles}
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_style(path: Path) -> dict[str, dict[str, Any]]:
    """Read measurements written by :func:`write_style`; empty when the file is absent."""
    if not path.is_file():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    repos = document.get("repos") if isinstance(document, dict) else None
    return dict(repos) if isinstance(repos, dict) else {}


__all__ = [
    "AI_SIGNATURES",
    "CommitRow",
    "SymbolRow",
    "ai_in_trailers",
    "code_style",
    "comment_lines",
    "commit_ai_signals",
    "documentation_lines",
    "history_style",
    "is_ai_author",
    "read_commits",
    "read_style",
    "repo_style",
    "write_style",
]
