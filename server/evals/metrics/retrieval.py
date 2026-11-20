"""File-level retrieval metrics: recall, MRR and nDCG over a ranked list of files.

A run's candidates are keyed by citation keys, several per file and some for no file at all
(commits, pull requests, README sections). The metrics here work on files: each key is mapped
to its file, duplicates keep their best position, and keys with no file are counted aside.
Single-shot arms are measured on the fused or reranked pool, agents on the order in which they
first touched each file.
"""

from __future__ import annotations

import ast
import json
import math
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from app.services.retrieval.citations import normalize_path, parse_key
from evals.gold.schema import GoldItem
from evals.metrics.answer import scored_gold
from evals.run.records import CandidateRecord, Generation, StepRecordOut

KS = (5, 10, 20)


@dataclass(frozen=True)
class Ranking:
    """A ranked list of files and the keys that could not be placed in it.

    Attributes:
        files: Distinct file paths, best first.
        unmapped: Well-formed keys that name no file (commits, pull requests, documents).
        malformed: Keys ``parse_key`` rejects and that carry no file path either.
    """

    files: tuple[str, ...]
    unmapped: int = 0
    malformed: int = 0


@dataclass(frozen=True)
class RetrievalScores:
    """Retrieval metrics for one ranking against one gold set.

    Attributes:
        recall: Recall at each k; ``None`` when the gold is empty.
        mrr: Reciprocal rank of the first gold file (0 when none is ranked); ``None`` when the
            gold is empty.
        ndcg: nDCG at each k; ``None`` when the gold is empty.
        n_ranked: How many distinct files were ranked.
        unmapped: Keys that named no file.
        malformed: Keys that could not be parsed.
    """

    recall: Mapping[int, float | None] = field(default_factory=dict)
    mrr: float | None = None
    ndcg: Mapping[int, float | None] = field(default_factory=dict)
    n_ranked: int = 0
    unmapped: int = 0
    malformed: int = 0


def key_file(key: str, file_path: str | None = None) -> tuple[str | None, bool]:
    """The file a citation key refers to.

    An ``F:`` key names its file in the key. For any other well-formed key the candidate's own
    ``file_path`` is used when it has one.

    Args:
        key: The citation key, with or without brackets.
        file_path: The owning file the candidate carries, if any.

    Returns:
        ``(path, malformed)``. ``path`` is ``None`` when no file can be named. ``malformed`` is
        true only when the key does not parse and no ``file_path`` rescued it.
    """
    parsed = parse_key(key)
    if parsed is not None and parsed.kind == "F" and parsed.path:
        return normalize_path(parsed.path), False
    if file_path:
        path = normalize_path(file_path)
        if path:
            return path, False
    return None, parsed is None


def ranked_files(
    candidates: Iterable[CandidateRecord], *, exclude: Collection[str] = ()
) -> Ranking:
    """Turn ranked candidates into ranked distinct files.

    Candidates are ordered by ``rank`` (ties keep list order); each key is mapped to its file;
    a file keeps the position of its first, best-ranked key. Keys with no file are counted in
    ``unmapped`` (well-formed) or ``malformed`` (unparseable) and never raise.

    Args:
        candidates: The candidates of one list.
        exclude: Files to leave out of the ranking, such as an item's anchor.

    Returns:
        The ranking.
    """
    ordered = sorted(enumerate(candidates), key=lambda pair: (pair[1].rank, pair[0]))
    skip = set(exclude)
    files: list[str] = []
    seen: set[str] = set()
    unmapped = malformed = 0
    for _, candidate in ordered:
        path, bad = key_file(candidate.key, candidate.file_path)
        if path is None:
            if bad:
                malformed += 1
            else:
                unmapped += 1
            continue
        if path in seen or path in skip:
            continue
        seen.add(path)
        files.append(path)
    return Ranking(files=tuple(files), unmapped=unmapped, malformed=malformed)


def read_path(step: StepRecordOut) -> str | None:
    """The file a ``read_file`` step read, from its recorded arguments.

    Arguments are recorded as the model wrote them, a JSON object or its Python repr; anything
    that is neither yields ``None``.
    """
    if step.tool != "read_file" or not step.arguments:
        return None
    try:
        data = json.loads(step.arguments)
    except ValueError:
        try:
            data = ast.literal_eval(step.arguments)
        except ValueError, SyntaxError:
            return None
    path = data.get("path") if isinstance(data, dict) else None
    if not isinstance(path, str) or not path.strip():
        return None
    return normalize_path(path) or None


def step_files(step: StepRecordOut) -> list[str]:
    """Files a step touched: those in its evidence keys, then the one it read, in order."""
    files: list[str] = []
    for key in step.evidence_keys:
        path, _ = key_file(key)
        if path is not None and path not in files:
            files.append(path)
    read = read_path(step)
    if read is not None and read not in files:
        files.append(read)
    return files


def first_touch_ranking(
    steps: Sequence[StepRecordOut], *, exclude: Collection[str] = ()
) -> Ranking:
    """Files in the order an agent first touched them.

    Steps are taken in ``index`` order. A file counts when it first appears in a step's
    evidence keys or as a ``read_file`` path. Evidence keys that name no file are counted.
    """
    skip = set(exclude)
    files: list[str] = []
    seen: set[str] = set()
    unmapped = malformed = 0
    for step in sorted(steps, key=lambda s: s.index):
        for key in step.evidence_keys:
            path, bad = key_file(key)
            if path is None:
                if bad:
                    malformed += 1
                else:
                    unmapped += 1
        for path in step_files(step):
            if path not in seen and path not in skip:
                seen.add(path)
                files.append(path)
    return Ranking(files=tuple(files), unmapped=unmapped, malformed=malformed)


def first_touch_files(steps: Sequence[StepRecordOut]) -> list[str]:
    """The files of :func:`first_touch_ranking`, as a list."""
    return list(first_touch_ranking(steps).files)


def generation_ranking(generation: Generation, *, exclude: Collection[str] = ()) -> Ranking:
    """The ranking a generation is measured on.

    A generation with agent steps is measured on first-touch order; any other on its pool,
    falling back to its final candidates when it recorded no pool.
    """
    if generation.steps:
        return first_touch_ranking(generation.steps, exclude=exclude)
    source = generation.pool or generation.candidates
    return ranked_files(source, exclude=exclude)


def recall_at_k(files: Sequence[str], gold: Collection[str], k: int) -> float | None:
    """Fraction of gold files within the first ``k`` ranked files.

    Edge cases: ``None`` for an empty gold; a ranking shorter than ``k`` is simply taken whole.
    """
    if not gold:
        return None
    wanted = set(gold)
    return len(wanted.intersection(files[:k])) / len(wanted)


def mrr(files: Sequence[str], gold: Collection[str]) -> float | None:
    """Reciprocal rank of the first gold file; 0 when none is ranked; ``None`` for empty gold."""
    if not gold:
        return None
    wanted = set(gold)
    for position, path in enumerate(files, start=1):
        if path in wanted:
            return 1.0 / position
    return 0.0


def ndcg_at_k(files: Sequence[str], gold: Collection[str], k: int) -> float | None:
    """Normalised discounted cumulative gain at ``k`` with binary relevance.

    Gain 1 for a gold file, discount ``1/log2(rank + 1)``, ideal DCG over ``min(k, |gold|)``
    relevant files at the top. ``None`` for an empty gold; ``files`` holds distinct files so a
    gold file cannot score twice.
    """
    if not gold:
        return None
    wanted = set(gold)
    dcg = sum(
        1.0 / math.log2(position + 1)
        for position, path in enumerate(files[:k], start=1)
        if path in wanted
    )
    ideal = sum(1.0 / math.log2(position + 1) for position in range(1, min(k, len(wanted)) + 1))
    return dcg / ideal


def retrieval_scores(
    ranking: Ranking, gold: Collection[str], ks: Sequence[int] = KS
) -> RetrievalScores:
    """Recall, MRR and nDCG of one ranking.

    Args:
        ranking: The ranked files.
        gold: The required files (use :func:`item_gold`).
        ks: Cut-offs.

    Returns:
        The scores; metrics are ``None`` when the gold is empty.
    """
    return RetrievalScores(
        recall={k: recall_at_k(ranking.files, gold, k) for k in ks},
        mrr=mrr(ranking.files, gold),
        ndcg={k: ndcg_at_k(ranking.files, gold, k) for k in ks},
        n_ranked=len(ranking.files),
        unmapped=ranking.unmapped,
        malformed=ranking.malformed,
    )


def item_gold(item: GoldItem, *, include_tests: bool = True) -> frozenset[str]:
    """The gold a retrieval metric is scored against: the answer's required files."""
    return scored_gold(item, include_tests=include_tests)


def generation_retrieval_scores(
    item: GoldItem,
    generation: Generation,
    ks: Sequence[int] = KS,
    *,
    include_tests: bool = True,
) -> RetrievalScores:
    """Retrieval metrics of a generation against an item, the anchor left out of both sides.

    Raises:
        ValueError: If the generation is an error record.
    """
    if generation.status != "ok":
        raise ValueError("an error generation is never scored")
    exclude = {item.anchor_file} if item.anchor_file else set()
    ranking = generation_ranking(generation, exclude=exclude)
    return retrieval_scores(ranking, item_gold(item, include_tests=include_tests), ks)


__all__ = [
    "KS",
    "Ranking",
    "RetrievalScores",
    "first_touch_files",
    "first_touch_ranking",
    "generation_ranking",
    "generation_retrieval_scores",
    "item_gold",
    "key_file",
    "mrr",
    "ndcg_at_k",
    "ranked_files",
    "read_path",
    "recall_at_k",
    "retrieval_scores",
    "step_files",
]
