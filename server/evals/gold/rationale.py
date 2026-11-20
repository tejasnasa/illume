"""Rationale items: why does this line exist?

A line of source at the base commit is blamed back to the commit that wrote it, and the
commit to the pull request it landed through. The item is kept only when that pull
request's description explains the intent, and the answer notes are sentences quoted from
it. The pull requests are part of the indexed history, so these items are circular by
design and are reported apart from the change-set headline.
"""

import random
import re
from collections.abc import Collection, Mapping
from datetime import date
from pathlib import Path

from app.services.stack_detector import is_scannable
from app.services.test_files import is_test_path
from evals.gold.changeset import is_generated
from evals.gold.schema import GoldItem, make_item
from evals.mining.blame import (
    MechanicalVerdict,
    blame_file,
    blame_line,
    is_mechanical,
    pr_for_commit,
)
from evals.mining.clones import show_file
from evals.mining.github_cache import CachedPR

MIN_LINE_CHARS = 20
MAX_LINE_CHARS = 160
MIN_BODY_WORDS = 30
MIN_NOTE_WORDS = 8
MAX_NOTES = 3
LINES_PER_FILE = 3
MAX_FILES_EXAMINED = 400

SEED_TEMPLATE = "Why does `{path}` contain `{line}`? What was the intent?"

_COMMENT_START = ("#", "//", "/*", "*", "--", '"', "'", "`")
_IMPORT_LINE = re.compile(
    r"^(import\b|from\s+\S+\s+import\b|use\s|using\s|package\s|require\b|export\s.*\sfrom\b"
    r"|(const|let|var)\s+.*=\s*require\()"
)
_TRIVIAL_LINE = re.compile(
    r"^([\]\)\}\{\[\(,;:\s]*|(pass|return|break|continue|else|try|finally)\b[:;]?)$"
)
_CODE_FENCE = re.compile(r"```.*?```", re.DOTALL)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


def is_candidate_line(line: str) -> bool:
    """Whether a source line is substantial enough to ask about.

    A line qualifies when it has at least ``MIN_LINE_CHARS`` non-space characters, fits in
    ``MAX_LINE_CHARS``, and is not a comment, a string or docstring line, an import, or a
    bare bracket, ``pass`` or ``return``.

    Args:
        line: One line of source, without its newline.

    Returns:
        ``True`` when the line may be asked about.
    """
    stripped = line.strip()
    if len(stripped) > MAX_LINE_CHARS or len("".join(stripped.split())) < MIN_LINE_CHARS:
        return False
    if stripped.startswith(_COMMENT_START):
        return False
    return not (_IMPORT_LINE.match(stripped) or _TRIVIAL_LINE.match(stripped))


def answer_notes(body: str) -> tuple[str, ...]:
    """Pick up to ``MAX_NOTES`` sentences from a pull request body to quote as facts.

    Markdown is stripped (comments, code fences, images, link targets, headings, bullets and
    emphasis marks) and the first sentences of at least ``MIN_NOTE_WORDS`` words are kept
    exactly as they read.

    Args:
        body: The pull request description.

    Returns:
        The sentences, in order; empty when the body has none long enough.
    """
    text = _HTML_COMMENT.sub("", body)
    text = _CODE_FENCE.sub("", text)
    text = _IMAGE.sub("", text)
    text = _LINK.sub(r"\1", text)
    notes: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"^\s*(#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s*)", "", raw)
        line = re.sub(r"[*_`]{1,3}", "", line).strip()
        if not line:
            continue
        for sentence in _SENTENCE_BREAK.split(line):
            sentence = sentence.strip()
            if len(sentence.split()) >= MIN_NOTE_WORDS:
                notes.append(sentence)
                if len(notes) == MAX_NOTES:
                    return tuple(notes)
    return tuple(notes)


def build_rationale_items(
    *,
    repo_name: str,
    clone: Path,
    base_commit: str,
    prs_by_merge_sha: Mapping[str, CachedPR],
    tip: str,
    files: Collection[str],
    seed: int,
    per_repo_target: int,
    max_per_pr: int = 2,
    generator_cutoff: date | None = None,
) -> list[GoldItem]:
    """Build rationale items from lines of source at the base commit.

    Candidate files are visited in a deterministic shuffle. For each, a few candidate lines
    are sampled and blamed with a single whole-file blame; a commit that turns out to be
    mechanical is looked through with ``blame_line``.

    Args:
        repo_name: The corpus entry's name.
        clone: A full clone containing the base commit and ``tip``.
        base_commit: The commit ``B``.
        prs_by_merge_sha: Merge commit SHA to pull request, for the pull requests merged
            before ``B`` (their text is in the index).
        tip: The tip of the default branch.
        files: Every file at the base commit; only parsed source files outside tests and
            generated output are used.
        seed: Seeds the sampling, together with the repository and base commit.
        per_repo_target: Stop after this many items.
        max_per_pr: The most items taken from one pull request.
        generator_cutoff: Pull requests merged after this date are flagged post-cutoff;
            ``post_cutoff`` is left ``None`` when omitted.

    Returns:
        The items, in the order found.
    """
    rng = random.Random(f"{repo_name}:{base_commit}:{seed}")
    merge_to_number = {sha: pr.number for sha, pr in prs_by_merge_sha.items()}
    by_number = {pr.number: pr for pr in prs_by_merge_sha.values()}
    candidates = sorted(
        path
        for path in files
        if is_scannable(path)
        and not path.endswith(".ipynb")
        and not is_test_path(path)
        and not is_generated(path)
    )
    rng.shuffle(candidates)

    mechanical_cache: dict[str, MechanicalVerdict] = {}

    def mechanical(path: Path, sha: str) -> MechanicalVerdict:
        if sha not in mechanical_cache:
            mechanical_cache[sha] = is_mechanical(path, sha)
        return mechanical_cache[sha]

    pr_cache: dict[str, int | None] = {}
    per_pr: dict[int, int] = {}
    items: list[GoldItem] = []

    for path in candidates[:MAX_FILES_EXAMINED]:
        if len(items) >= per_repo_target:
            break
        text = show_file(clone, base_commit, path)
        if text is None:
            continue
        lines = text.splitlines()
        eligible = [number for number, line in enumerate(lines, 1) if is_candidate_line(line)]
        if not eligible:
            continue
        sampled = sorted(rng.sample(eligible, min(LINES_PER_FILE, len(eligible))))
        blamed = {entry.line: entry for entry in blame_file(clone, base_commit, path)}

        for number in sampled:
            if len(items) >= per_repo_target:
                break
            entry = blamed.get(number)
            if entry is None:
                continue
            commit = entry.commit
            if mechanical(clone, commit).mechanical:
                walked = blame_line(clone, base_commit, path, number, mechanical=mechanical)
                if walked is None:
                    continue
                commit = walked.commit
            if commit not in pr_cache:
                pr_cache[commit] = pr_for_commit(clone, commit, merge_to_number, tip)
            pr_number = pr_cache[commit]
            if pr_number is None or per_pr.get(pr_number, 0) >= max_per_pr:
                continue
            pr = by_number[pr_number]
            if len(pr.body.split()) < MIN_BODY_WORDS:
                continue
            notes = answer_notes(pr.body)
            if not notes:
                continue
            per_pr[pr_number] = per_pr.get(pr_number, 0) + 1
            items.append(
                make_item(
                    repo=repo_name,
                    base_commit=base_commit,
                    family="rationale",
                    template="rationale.blame",
                    question_seed=SEED_TEMPLATE.format(path=path, line=lines[number - 1].strip()),
                    gold_files=(path,),
                    gold_prs=(pr_number,),
                    gold_commits=(commit,),
                    gold_answer_notes=notes,
                    circular_with=("history",),
                    post_cutoff=(
                        None if generator_cutoff is None else pr.merged_at.date() > generator_cutoff
                    ),
                    cluster=f"{repo_name}#{pr_number}",
                )
            )
    return items
