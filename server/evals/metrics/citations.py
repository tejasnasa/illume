"""Citation health: cited keys that match nothing the run saw, and files that do not exist.

The product reports an ``unresolved`` list for the keys an answer cites that match no evidence
the run saw. This reproduces that rule on recorded generations so every arm is measured the
same way, and adds a check the product does not make: a cited file that is not in the tree at
the base commit.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass

from app.services.retrieval.citations import CitationKey, find_keys, normalize_path, parse_key
from evals.run.records import Generation


@dataclass(frozen=True)
class CitationScores:
    """Citation health of one answer.

    Attributes:
        cited: Distinct keys the answer cites, as written.
        unresolved: Cited keys that are malformed or match nothing the run saw.
        missing_at_base: Cited code keys whose file is not in the tree at the base commit.
        unresolved_rate: ``unresolved / cited``; ``None`` when nothing is cited (a Classic
            answer cites nothing, which is not a perfect score).
        missing_rate: ``missing_at_base / cited code keys``; ``None`` without code keys.
    """

    cited: int
    unresolved: int
    missing_at_base: int
    unresolved_rate: float | None
    missing_rate: float | None


def seen_keys(generation: Generation) -> list[str]:
    """Every key the run saw: final candidates, the pool and every step's evidence."""
    keys = [c.key for c in generation.candidates] + [c.key for c in generation.pool]
    for step in generation.steps:
        keys.extend(step.evidence_keys)
    return keys


def _covers(seen: CitationKey, wanted: CitationKey) -> bool:
    if seen.kind != wanted.kind:
        return False
    if wanted.kind == "F":
        if normalize_path(seen.path or "") != normalize_path(wanted.path or ""):
            return False
        if None in (wanted.start, wanted.end, seen.start, seen.end):
            return True
        assert wanted.start and wanted.end and seen.start and seen.end
        return min(seen.end, wanted.end) >= max(seen.start, wanted.start)
    if wanted.kind == "C":
        have, asked = seen.commit or "", wanted.commit or ""
        return have.startswith(asked) or asked.startswith(have)
    return seen.render() == wanted.render()


def resolves(wanted: CitationKey, seen: Iterable[CitationKey]) -> bool:
    """Whether a cited key matches something seen.

    A code key without a range matches any range of that file; one with a range matches
    evidence whose range overlaps it; commits match by hash prefix; other kinds match exactly.
    """
    return any(_covers(candidate, wanted) for candidate in seen)


def cited_keys_of(generation: Generation) -> list[str]:
    """The keys the answer cites, as written, each once.

    Read from the bracketed keys in the answer text; when the text has none, from the
    generation's recorded ``cited_keys``.
    """
    raw = [text for text, _ in find_keys(generation.answer)] or list(generation.cited_keys)
    return list(dict.fromkeys(raw))


def citation_scores(generation: Generation, files_at_base: Collection[str]) -> CitationScores:
    """Score an answer's citations.

    Edge cases: a malformed key is unresolved; an answer that cites nothing has ``None``
    rates, not 0; duplicates count once; a code key's file is checked at the base commit
    whether or not it resolved.

    Args:
        generation: An answer.
        files_at_base: Every file present at the base commit.

    Returns:
        The scores.

    Raises:
        ValueError: If the generation is an error record.
    """
    if generation.status != "ok":
        raise ValueError("an error generation is never scored")
    seen = [key for key in (parse_key(k) for k in seen_keys(generation)) if key is not None]
    base = set(files_at_base)
    cited = cited_keys_of(generation)
    unresolved = missing = code_keys = 0
    for raw in cited:
        parsed = parse_key(raw)
        if parsed is None or not resolves(parsed, seen):
            unresolved += 1
        if parsed is not None and parsed.kind == "F":
            code_keys += 1
            if normalize_path(parsed.path or "") not in base:
                missing += 1
    return CitationScores(
        cited=len(cited),
        unresolved=unresolved,
        missing_at_base=missing,
        unresolved_rate=unresolved / len(cited) if cited else None,
        missing_rate=missing / code_keys if code_keys else None,
    )


__all__ = ["CitationScores", "cited_keys_of", "citation_scores", "resolves", "seen_keys"]
