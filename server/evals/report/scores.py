"""Per-item, per-arm scores for the change-set items, computed once and read many times.

Every table, comparison and figure in the report draws on the same :class:`Scores`, so a number
cannot differ between two places. An error record has a row (with its reason) but no metric: it
is excluded from every comparison involving its arm and listed. An arm that never reached an
item has no row for it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from evals.gold.schema import GoldItem
from evals.metrics.answer import AnswerScores, answer_file_scores
from evals.metrics.cost import Tokens, generation_cost, token_totals
from evals.metrics.retrieval import KS, generation_retrieval_scores
from evals.metrics.trajectory import steps_to_first_gold
from evals.report.comparisons import ItemRef
from evals.report.load import RunData
from evals.run.records import Generation

CHANGESET = "changeset"


@dataclass(frozen=True)
class Score:
    """One arm's result on one change-set item.

    Attributes:
        item_id: The item.
        arm: The arm.
        ok: Whether the record is usable; an error record is not.
        error: Why an error record failed.
        generation: The record itself.
        answer: The file scores with test files in the gold; ``None`` on an error.
        answer_nt: The file scores without test files in the gold.
        recall_at: File recall at each cut-off of the arm's retrieval ranking.
        mrr: Reciprocal rank of the first gold file.
        ndcg_at: nDCG at each cut-off.
        steps: Steps to the first gold file for an agent run, censored at the run's step count
            when none was reached.
        reached: Whether an agent run reached a gold file; ``None`` for a non-agent arm.
        cost: What the pair cost, in dollars.
        latency_ms: Wall time of the generation.
        tokens: Metered tokens.
    """

    item_id: str
    arm: str
    ok: bool
    error: str | None
    generation: Generation
    answer: AnswerScores | None = None
    answer_nt: AnswerScores | None = None
    recall_at: Mapping[int, float | None] = field(default_factory=dict)
    mrr: float | None = None
    ndcg_at: Mapping[int, float | None] = field(default_factory=dict)
    steps: float | None = None
    reached: bool | None = None
    cost: float = 0.0
    latency_ms: float = 0.0
    tokens: Tokens = field(default_factory=Tokens)


def _score(item: GoldItem, generation: Generation, files: list[str]) -> Score:
    cost = generation_cost(generation)
    base = {
        "item_id": item.id,
        "arm": generation.arm,
        "generation": generation,
        "cost": cost,
        "latency_ms": generation.latency_ms,
        "tokens": token_totals(generation),
    }
    if generation.status != "ok":
        return Score(ok=False, error=generation.error, **base)  # type: ignore[arg-type]
    answer = answer_file_scores(item, generation, files)
    answer_nt = answer_file_scores(item, generation, files, include_tests=False)
    retrieval = generation_retrieval_scores(item, generation, KS)
    steps: float | None = None
    reached: bool | None = None
    if generation.steps:
        from evals.metrics.answer import scored_gold

        first = steps_to_first_gold(generation.steps, scored_gold(item))
        reached = first is not None
        steps = float(first) if first is not None else float(len(generation.steps))
    return Score(
        ok=True,
        error=None,
        answer=answer,
        answer_nt=answer_nt,
        recall_at=dict(retrieval.recall),
        mrr=retrieval.mrr,
        ndcg_at=dict(retrieval.ndcg),
        steps=steps,
        reached=reached,
        **base,  # type: ignore[arg-type]
    )


class Scores:
    """Scores of every arm on every change-set item of a run.

    Attributes:
        items: The change-set items, sorted by id.
        refs: Their pairing identities, in the same order.
        rows: Arm to item id to :class:`Score`.
    """

    def __init__(self, items: list[GoldItem], rows: dict[str, dict[str, Score]]) -> None:
        self.items = items
        self.refs = [ItemRef(i.id, i.repo, i.cluster or i.id) for i in items]
        self.rows = rows

    @classmethod
    def build(cls, data: RunData) -> Scores:
        """Score the change-set records of a run.

        Args:
            data: The loaded run.

        Returns:
            The scores. Generations of other families or of unknown items are ignored.
        """
        items = sorted(
            (i for i in data.items.values() if i.family == CHANGESET), key=lambda i: i.id
        )
        by_id = {i.id: i for i in items}
        rows: dict[str, dict[str, Score]] = {}
        for generation in data.generations:
            item = by_id.get(generation.item_id)
            if item is None:
                continue
            files = data.files_at_base.get(item.repo, [])
            rows.setdefault(generation.arm, {})[item.id] = _score(item, generation, files)
        return cls(items, rows)

    def arms(self) -> list[str]:
        """Arms with at least one change-set record, in the order of the arm table."""
        from evals.arms import ARMS

        known = [name for name in ARMS if name in self.rows]
        return known + sorted(name for name in self.rows if name not in ARMS)

    def get(self, arm: str, item_id: str, metric: str) -> float | None:
        """One metric of one arm on one item; ``None`` for an error or an item not reached."""
        row = self.rows.get(arm, {}).get(item_id)
        if row is None or not row.ok:
            return None
        if metric == "cost":
            return row.cost
        if metric == "steps":
            return row.steps
        if metric == "recall":
            return row.answer.recall if row.answer else None
        if metric == "recall_nt":
            return row.answer_nt.recall if row.answer_nt else None
        if metric == "recall10":
            return row.recall_at.get(10)
        raise KeyError(f"unknown metric {metric!r}")

    def ok_rows(self, arm: str) -> list[Score]:
        """The usable rows of an arm, in item order."""
        return [r for r in self.rows.get(arm, {}).values() if r.ok]


__all__ = ["CHANGESET", "Score", "Scores"]
