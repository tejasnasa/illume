"""The primary metric: recall and precision of the files an answer lists.

Scored against ``gold_files`` over the ``Files:`` list parsed the same way for every arm.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from app.services.test_files import is_test_path
from evals.gold.schema import GoldItem
from evals.metrics.files_list import parse_files_list
from evals.run.records import Generation


@dataclass(frozen=True)
class AnswerScores:
    """The file scores of one answer.

    Attributes:
        recall: Required gold files listed, over required gold files; ``None`` when the gold
            is empty (such an item is scored by the judge instead).
        precision: Listed files that are required gold, over listed files that count; ``None``
            when nothing counts or the gold is empty.
        tp: Required gold files listed.
        listed: How many listed files counted toward precision.
        gold_n: How many files the gold requires.
        format_failure: The answer has no ``Files:`` list.
        nonexistent_listed: Listed paths that do not exist at the base commit; each counts
            against precision.
    """

    recall: float | None
    precision: float | None
    tp: int
    listed: int
    gold_n: int
    format_failure: bool
    nonexistent_listed: int


def scored_gold(item: GoldItem, *, include_tests: bool = True) -> frozenset[str]:
    """The files an item's answer is required to list.

    Args:
        item: The gold item.
        include_tests: Whether test files are required; ``False`` drops ``gold_test_files``.

    Returns:
        ``gold_files`` without the anchor (never scored) and, optionally, without tests.
    """
    gold = set(item.gold_files)
    if item.anchor_file is not None:
        gold.discard(item.anchor_file)
    if not include_tests:
        gold -= set(item.gold_test_files)
    return frozenset(gold)


def answer_file_scores(
    item: GoldItem,
    generation: Generation,
    files_at_base: Collection[str],
    *,
    include_tests: bool = True,
) -> AnswerScores:
    """Score the files an answer lists against an item's gold.

    The anchor file is never scored: it is not required, and listing it is neither a hit nor
    a miss. With ``include_tests=False`` the gold drops its test files and any listed test
    file (by the gold's own test list or by path) is ignored on both sides. A listed path
    that is not in ``files_at_base`` counts against precision. Listed ``acceptable_files``
    that are not required are neither hits nor misses in precision, and recall is over the
    required files only. An empty gold gives ``recall=None`` and ``precision=None``. An answer
    with no ``Files:`` list gives recall ``0.0`` (``None`` for an empty gold), precision
    ``None`` and ``format_failure=True``. Duplicates are counted once.

    Args:
        item: The gold item.
        generation: An answer to score.
        files_at_base: Every file present at the base commit.
        include_tests: Whether test files count.

    Returns:
        The scores.

    Raises:
        ValueError: If the generation is an error record; callers exclude those.
    """
    if generation.status != "ok":
        raise ValueError("an error generation is never scored")
    gold = scored_gold(item, include_tests=include_tests)
    parsed = parse_files_list(generation.answer)
    if not parsed.found:
        return AnswerScores(
            recall=0.0 if gold else None,
            precision=None,
            tp=0,
            listed=0,
            gold_n=len(gold),
            format_failure=True,
            nonexistent_listed=0,
        )

    base = set(files_at_base)
    test_files = set(item.gold_test_files)
    listed: list[str] = []
    for path in parsed.paths:
        if path == item.anchor_file:
            continue
        if not include_tests and (path in test_files or is_test_path(path)):
            continue
        listed.append(path)

    nonexistent = sum(1 for path in listed if path not in base)
    acceptable = set(item.acceptable_files) - gold
    counted = [path for path in listed if path not in acceptable]
    tp = sum(1 for path in listed if path in gold)
    if not gold:
        return AnswerScores(None, None, 0, len(counted), 0, False, nonexistent)
    return AnswerScores(
        recall=tp / len(gold),
        precision=tp / len(counted) if counted else None,
        tp=tp,
        listed=len(counted),
        gold_n=len(gold),
        format_failure=False,
        nonexistent_listed=nonexistent,
    )


__all__ = ["AnswerScores", "answer_file_scores", "scored_gold"]
