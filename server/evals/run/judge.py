"""The judge pass: grade recorded answers with DeepEval metrics, resumably and on a budget.

Three metrics are judged for every selected generation: ``correctness`` (G-Eval against the
reference answer), ``faithfulness`` (claim by claim against the cited evidence) and
``answer_relevancy``. Each is called directly through its ``a_measure`` and judged and cached
separately; see :mod:`evals.run.judge_metrics` for what each is shown. The judge never sees which
arm, which configuration or which model produced the answer.

Judgments are appended to a JSONL file per judge identity, one record per generation and metric,
keyed by the generation, the metric, a hash of that metric's settings, the DeepEval release, the
judge model and the judge host. Changing any of those grades that metric again and leaves the
others, and ``generations.jsonl``, alone. A metric that raises, times out or returns unusable
output is stored as an error record and tried again on the next run; it is never scored.

Every call goes through :class:`evals.run.judge_model.MeteredJudgeModel`, so spend reaches the
budget and the meter and the judge model stays configurable.

Library code here takes nothing from ``evals.settings``.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from evals.gold.schema import GoldItem
from evals.run.budget import Budget, BudgetStop, UnpricedSpend
from evals.run.deepeval_env import deepeval_version
from evals.run.endpoint import JudgeEndpoint
from evals.run.generate import final_records
from evals.run.judge_batch import BatchPending, track_served
from evals.run.judge_metrics import (
    ANSWER_CHAR_BUDGET,
    EVIDENCE_CHAR_BUDGET,
    NO_EVIDENCE,
    UNANSWERABLE_TAG,
    UNAVAILABLE,
    UNMATCHED,
    EvidenceText,
    MetricSpec,
    default_metrics,
    render_evidence,
    rubric_value,
)
from evals.run.judge_model import JudgeOutputError, MeteredJudgeModel
from evals.run.metering import Meter
from evals.run.pricing import PriceTable, UnpricedUsage
from evals.run.records import RUBRIC_MAX, Generation, JudgeVersion, Judgment, Usage, judgment_key

CHANGESET_FRACTION = 1.0
"""The share of change-set clusters judged; every one by default."""
METRIC_TIMEOUT_SECONDS = 900.0
"""The longest one metric may take, all its calls together."""
FAITHFUL_RUBRIC_SCALE = RUBRIC_MAX
"""Faithfulness is shown on the same 0 to 3 scale as correctness: its score times this, rounded."""

ClientFactory = Callable[..., Any]


@dataclass(frozen=True)
class JudgePair:
    """One generation to grade, with the gold item it answers.

    Attributes:
        item: The gold item.
        generation: The recorded answer.
    """

    item: GoldItem
    generation: Generation


# --- selection -----------------------------------------------------------------------


def _rank(seed: int, name: str) -> str:
    return hashlib.sha256(f"{seed}:{name}".encode()).hexdigest()


def select_for_judging(
    items: Iterable[GoldItem],
    generations: Iterable[Generation],
    *,
    seed: int,
    changeset_fraction: float = CHANGESET_FRACTION,
    include_unanswerable: bool = False,
) -> list[JudgePair]:
    """The generations to grade.

    Every item is graded, except that ``unanswerable`` items are left out unless asked for (a
    correct answer to one is a refusal, which the metrics do not model), and that a share of the
    change-set clusters below one is drawn deterministically by cluster so both variants of a pull
    request are in or out together. The clusters are drawn from the items, not the generations, so
    adding an arm does not change which questions are chosen. Error generations are skipped, and
    where a key was written more than once the last record counts.

    Args:
        items: The slice's gold items.
        generations: Recorded generations.
        seed: The seed of the cluster draw.
        changeset_fraction: The share of change-set clusters to grade; 1.0 grades all.
        include_unanswerable: Grade the ``unanswerable`` items too.

    Returns:
        The pairs, ordered by item, arm and repeat.
    """
    by_id = {item.id: item for item in items}
    clusters = sorted(
        {item.cluster for item in by_id.values() if item.family == "changeset" and item.cluster}
    )
    take = math.ceil(changeset_fraction * len(clusters)) if clusters else 0
    chosen = set(sorted(clusters, key=lambda c: (_rank(seed, c), c))[:take])

    pairs: list[JudgePair] = []
    for generation in final_records(generations):
        item = by_id.get(generation.item_id)
        if item is None or generation.status != "ok":
            continue
        if not include_unanswerable and UNANSWERABLE_TAG in item.tags:
            continue
        if item.family != "changeset" or item.cluster in chosen:
            pairs.append(JudgePair(item, generation))
    pairs.sort(key=lambda p: (p.item.id, p.generation.arm, p.generation.repeat))
    return pairs


# --- the files -----------------------------------------------------------------------


def judgments_path(run_dir: Path, endpoint: JudgeEndpoint) -> Path:
    """Where one judge's judgments live: ``judgments.<model>--<host>--<hash>.jsonl``."""
    return Path(run_dir) / f"judgments.{endpoint.slug}.jsonl"


def read_judgments(path: Path) -> list[Judgment]:
    """Every record in a judgments file, in file order; a line cut short is skipped."""
    if not Path(path).exists():
        return []
    records: list[Judgment] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            records.append(Judgment.model_validate_json(text))
        except ValueError:
            continue
    return records


def final_judgments(judgments: Iterable[Judgment]) -> list[Judgment]:
    """One record per key, the last one written, in the order each key first appeared."""
    latest: dict[str, Judgment] = {}
    for judgment in judgments:
        latest[judgment.judgment_key] = judgment
    return list(latest.values())


def all_judgments(run_dir: Path) -> list[Judgment]:
    """Every record of every judge's file in a run directory."""
    records: list[Judgment] = []
    for path in sorted(Path(run_dir).glob("judgments.*.jsonl")):
        records.extend(read_judgments(path))
    return records


def _append(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(payload + "\n")
        handle.flush()


# --- one generation's grades ---------------------------------------------------------


@dataclass(frozen=True)
class Grade:
    """The metrics of one generation under one judge, gathered into one row.

    Attributes:
        generation_key: The generation graded.
        item_id: The gold item.
        family: The item's family.
        arm: The generation's arm, for analysis only.
        correct: The correctness rubric value, 0 to 3, or ``None`` when that metric has no usable
            grade.
        correct_score: The raw correctness score, 0 to 1.
        faithful_score: The raw faithfulness score, 0 to 1, or ``None``.
        relevancy_score: The raw answer-relevancy score, 0 to 1, or ``None``.
        errors: Names of the metrics whose latest record is an error.
        reused: Whether the grades were copied from the answer's target rather than judged, for a
            composed generation whose answer is identical to it.
        not_applicable: Names of the metrics that do not apply to this answer, so their scores are
            left out rather than counted (see :func:`exclude_empty_answers`).
    """

    generation_key: str
    item_id: str
    family: str
    arm: str
    correct: int | None = None
    correct_score: float | None = None
    faithful_score: float | None = None
    relevancy_score: float | None = None
    errors: tuple[str, ...] = ()
    reused: bool = False
    not_applicable: tuple[str, ...] = ()

    @property
    def faithful(self) -> int | None:
        """The faithfulness score on the 0 to 3 scale, rounded; ``None`` without one."""
        if self.faithful_score is None:
            return None
        return round(self.faithful_score * FAITHFUL_RUBRIC_SCALE)

    @property
    def status(self) -> str:
        """``ok`` when correctness and faithfulness both have a grade, otherwise ``error``.

        A faithfulness that does not apply counts as graded, so an empty answer is not an error.
        """
        faithful = self.faithful_score is not None or "faithfulness" in self.not_applicable
        return "ok" if self.correct is not None and faithful else "error"


def grades_by_generation(judgments: Iterable[Judgment]) -> list[Grade]:
    """One row per generation from the final per-metric records.

    A generation with a metric that has no record at all is still returned, with that field
    ``None``; one whose latest record for a metric is an error lists it in ``errors``.

    Args:
        judgments: Records of one judge, possibly with superseded ones.

    Returns:
        The rows, in the order each generation first appeared.
    """
    grouped: dict[str, dict[str, Judgment]] = {}
    order: list[str] = []
    for judgment in final_judgments(judgments):
        if judgment.generation_key not in grouped:
            grouped[judgment.generation_key] = {}
            order.append(judgment.generation_key)
        grouped[judgment.generation_key][judgment.metric] = judgment
    rows: list[Grade] = []
    for key in order:
        metrics = grouped[key]
        any_record = next(iter(metrics.values()))

        def ok_score(name: str, metrics: dict[str, Judgment] = metrics) -> float | None:
            record = metrics.get(name)
            return record.score if record is not None and record.status == "ok" else None

        correctness = metrics.get("correctness")
        correct: int | None = None
        if correctness is not None and correctness.status == "ok" and correctness.score is not None:
            correct = (
                correctness.rubric
                if correctness.rubric is not None
                else round(correctness.score * RUBRIC_MAX)
            )
        rows.append(
            Grade(
                generation_key=key,
                item_id=any_record.item_id,
                family=any_record.family,
                arm=any_record.arm,
                correct=correct,
                correct_score=ok_score("correctness"),
                faithful_score=ok_score("faithfulness"),
                relevancy_score=ok_score("answer_relevancy"),
                errors=tuple(sorted(n for n, j in metrics.items() if j.status == "error")),
                reused=any(j.reused_from is not None for j in metrics.values()),
            )
        )
    return rows


NOT_APPLICABLE_WHEN_EMPTY = ("answer_relevancy", "faithfulness")
"""The metrics an empty answer has no score for: with no claims or statements, DeepEval would
score both 1.0, which says nothing about the answer. Correctness still grades it (as 0)."""


def is_empty_answer(answer: str | None) -> bool:
    """Whether an answer has no text at all once whitespace is removed."""
    return not (answer or "").strip()


def exclude_empty_answers(
    grades: Iterable[Grade], generations: Iterable[Generation]
) -> list[Grade]:
    """Drop faithfulness and relevancy from the grades of empty answers.

    Args:
        grades: One judge's rows.
        generations: The run's records; a grade whose record is missing is kept as it is.

    Returns:
        The rows, in order. An empty answer's row has both scores set to ``None``, the metrics
        named in ``not_applicable`` and removed from ``errors``.
    """
    empty = {g.record_key for g in generations if g.status == "ok" and is_empty_answer(g.answer)}
    rows: list[Grade] = []
    for grade in grades:
        if grade.generation_key not in empty:
            rows.append(grade)
            continue
        rows.append(
            replace(
                grade,
                faithful_score=None,
                relevancy_score=None,
                errors=tuple(e for e in grade.errors if e not in NOT_APPLICABLE_WHEN_EMPTY),
                not_applicable=NOT_APPLICABLE_WHEN_EMPTY,
            )
        )
    return rows


# --- the runner ----------------------------------------------------------------------


@dataclass
class JudgeResult:
    """What a judge run did.

    Attributes:
        planned: Metric gradings the run was asked to do (pairs times metrics).
        skipped: Gradings already done.
        ok: Gradings done this run.
        reused: Gradings given a copy of their target's grade.
        errors: Gradings that failed; they are tried again next run.
        pending: Gradings waiting on a batch reply; they carry on next run.
        spent_usd: Spend so far, including what was on disk.
        stopped: Why the run stopped early, or ``None``.
        reported_models: The model names the provider reported.
    """

    planned: int = 0
    skipped: int = 0
    ok: int = 0
    reused: int = 0
    errors: int = 0
    pending: int = 0
    spent_usd: float = 0.0
    stopped: str | None = None
    reported_models: set[str] = field(default_factory=set)


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def judge_all(
    pairs: Sequence[JudgePair],
    *,
    endpoint: JudgeEndpoint,
    out_path: Path,
    budget: Budget,
    table: PriceTable,
    client_factory: ClientFactory = AsyncOpenAI,
    meter: Meter | None = None,
    evidence_for: Callable[[GoldItem], EvidenceText] | None = None,
    concurrency: int = 1,
    clock: Callable[[], datetime] = _utcnow,
    metrics: Sequence[MetricSpec] | None = None,
    metric_timeout: float = METRIC_TIMEOUT_SECONDS,
    deepeval_release: str | None = None,
    batch: bool = False,
) -> JudgeResult:
    """Grades each pair on each metric, appending one judgment per pair and metric to ``out_path``.

    A metric already graded ``ok`` under the same generation, settings, DeepEval release, model
    and host is skipped; an error record is tried again. Generations are only read. A composed
    record whose answer is identical to its target's takes a copy of the target's grade instead of
    paying for a second one. Every call the metric makes is metered; its usage is charged to
    ``budget``, which the caller has restored from the records already on disk, and the run stops
    cleanly before a metric once the stop is reached.

    Args:
        pairs: The generations to grade.
        endpoint: The judge.
        out_path: The judgments file of this judge.
        budget: The spend limits.
        table: The price table; it must price ``endpoint.model``.
        client_factory: Builds the client from ``AsyncOpenAI``-style keyword arguments.
        meter: Also receives the usage of every call.
        evidence_for: Gives, for an item, the lookup from a citation key to its text.
        concurrency: How many metric gradings run at once.
        clock: The wall clock.
        metrics: The metrics to run; the shipped three when omitted.
        metric_timeout: The longest one metric may take, in seconds.
        deepeval_release: The DeepEval version recorded in the keys; the installed one when
            omitted.
        batch: The client answers from a batch reply store (see :mod:`evals.run.judge_batch`).
            A metric that meets a request with no reply yet is left for the next run, unrecorded
            and uncharged. Spend is not charged here either: replies are paid for when their
            batch runs, so the caller counts them in ``budget`` from the store. A composed record
            whose target is still pending waits for it rather than asking the same questions.

    Returns:
        What the run did.
    """
    specs = tuple(metrics) if metrics is not None else default_metrics()
    release = deepeval_release or deepeval_version()
    result = JudgeResult(planned=len(pairs) * len(specs))
    existing = {j.judgment_key: j for j in final_judgments(read_judgments(out_path))}
    client = client_factory(**endpoint.client_kwargs())
    stop: list[BudgetStop] = []

    def key_of(pair: JudgePair, spec: MetricSpec) -> str:
        return judgment_key(
            generation_key=pair.generation.record_key,
            metric=spec.name,
            settings_hash=spec.settings_hash,
            deepeval_version=release,
            model=endpoint.model,
            host=endpoint.host,
        )

    def identity(spec: MetricSpec) -> JudgeVersion:
        return JudgeVersion(
            deepeval_version=release,
            settings_hash=spec.settings_hash,
            model=endpoint.model,
            host=endpoint.host,
            api_style=endpoint.api_style,
            judged_on=clock().date().isoformat(),
        )

    def record(judgment: Judgment) -> None:
        _append(out_path, judgment.model_dump_json())
        existing[judgment.judgment_key] = judgment

    def price(usages: list[Usage]) -> float:
        total = 0.0
        for usage in usages:
            try:
                total += table.cost(usage, clock())
            except UnpricedUsage:
                continue
        return total

    def charge(usages: list[Usage]) -> float:
        if not usages:
            return 0.0
        if meter is not None:
            meter.extend(usages)
        if batch:
            return price(usages)
        try:
            return budget.charge(usages, table, clock())
        except UnpricedSpend as unpriced:
            if not stop:
                stop.append(
                    BudgetStop(f"no price for {', '.join(unpriced.models)}", budget.spent_usd)
                )
            return unpriced.cost_usd

    async def grade(pair: JudgePair, spec: MetricSpec, key: str) -> None:
        item, generation = pair.item, pair.generation
        lookup = evidence_for(item) if evidence_for is not None else None
        model = MeteredJudgeModel(client, endpoint)
        common: dict[str, Any] = {
            "judgment_key": key,
            "generation_key": generation.record_key,
            "item_id": item.id,
            "family": item.family,
            "arm": generation.arm,
            "repeat": generation.repeat,
            "metric": spec.name,
            "judge": identity(spec),
        }
        score: float | None = None
        failure: str | None = None
        served = track_served() if batch else None
        try:
            test_case = spec.case(item, generation, lookup or (lambda _: None))
            measured = spec.build(model, spec.settings)
            async with asyncio.timeout(metric_timeout):
                value = await measured.a_measure(test_case, _show_indicator=False)
            score = _valid_score(value)
        except BatchPending:
            result.pending += 1
            return
        except JudgeOutputError as problem:
            failure = str(problem)
            reject = getattr(client, "reject_served", None)
            if served and reject is not None and reject(served, failure):
                result.pending += 1
                return
        except TimeoutError:
            failure = f"the metric did not finish within {metric_timeout:.0f} seconds"
        except Exception as problem:
            failure = f"{type(problem).__name__}: {problem}"[:500]
        cost = charge(model.usages)
        if meter is not None:
            for _ in range(model.unmetered):
                meter.note_unmetered("response_without_usage:judge")
        result.reported_models |= model.reported_models
        reported = ",".join(sorted(model.reported_models)) or None
        usages = list(model.usages)
        if score is not None and failure is None:
            record(
                Judgment(
                    **common,
                    score=score,
                    rubric=rubric_value(score) if spec.name == "correctness" else None,
                    reported_model=reported,
                    usages=usages,
                    cost_usd=cost,
                )
            )
            result.ok += 1
        else:
            record(
                Judgment(
                    **common,
                    status="error",
                    error=failure or "the metric returned no score",
                    reported_model=reported,
                    usages=usages,
                    cost_usd=cost,
                )
            )
            result.errors += 1

    async def worker(queue: Iterable[tuple[JudgePair, MetricSpec, str]]) -> None:
        for pair, spec, key in queue:
            if stop:
                return
            try:
                budget.check_before_next()
            except BudgetStop as reached:
                stop.append(reached)
                return
            await grade(pair, spec, key)

    async def drain(queue: list[tuple[JudgePair, MetricSpec, str]]) -> None:
        iterator = iter(queue)
        workers = max(1, min(concurrency, len(queue)))
        await asyncio.gather(*(worker(iterator) for _ in range(workers)))

    # Non-composed records are graded first so composed ones can reuse their grades.
    direct: list[tuple[JudgePair, MetricSpec, str]] = []
    composed: list[tuple[JudgePair, MetricSpec, str]] = []
    for pair in pairs:
        for spec in specs:
            key = key_of(pair, spec)
            found = existing.get(key)
            if found is not None and found.status == "ok":
                result.skipped += 1
            elif pair.generation.composed_from is None:
                direct.append((pair, spec, key))
            else:
                composed.append((pair, spec, key))
    await drain(direct)

    target_of = {(p.item.id, p.generation.arm, p.generation.repeat): p for p in pairs}
    leftover: list[tuple[JudgePair, MetricSpec, str]] = []
    for pair, spec, key in composed:
        generation = pair.generation
        target = target_of.get((pair.item.id, generation.composed_from or "", 0))
        grade_of = existing.get(key_of(target, spec)) if target is not None else None
        if (
            target is not None
            and grade_of is not None
            and grade_of.status == "ok"
            and target.generation.answer == generation.answer
        ):
            record(
                grade_of.model_copy(
                    update={
                        "judgment_key": key,
                        "generation_key": generation.record_key,
                        "arm": generation.arm,
                        "repeat": generation.repeat,
                        "judge": identity(spec),
                        "usages": [],
                        "cost_usd": 0.0,
                        "reused_from": grade_of.judgment_key,
                    }
                )
            )
            result.reused += 1
        elif (
            batch
            and target is not None
            and grade_of is None
            and target.generation.answer == generation.answer
            and target.generation.composed_from is None
        ):
            result.pending += 1
        else:
            leftover.append((pair, spec, key))
    await drain(leftover)

    result.spent_usd = budget.spent_usd
    if stop:
        result.stopped = stop[0].reason
    return result


def _valid_score(value: Any) -> float:
    """The metric's score as a float from 0 to 1.

    Raises:
        JudgeOutputError: When it is missing, not a number, or outside that range.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise JudgeOutputError(f"the metric returned no usable score: {value!r}")
    number = float(value)
    if math.isnan(number) or not 0.0 <= number <= 1.0:
        raise JudgeOutputError(f"the metric's score is outside 0 to 1: {number!r}")
    return number


__all__ = [
    "ANSWER_CHAR_BUDGET",
    "CHANGESET_FRACTION",
    "EVIDENCE_CHAR_BUDGET",
    "METRIC_TIMEOUT_SECONDS",
    "NO_EVIDENCE",
    "UNAVAILABLE",
    "UNMATCHED",
    "EvidenceText",
    "Grade",
    "JudgePair",
    "JudgeResult",
    "all_judgments",
    "final_judgments",
    "grades_by_generation",
    "judge_all",
    "judgments_path",
    "read_judgments",
    "render_evidence",
    "select_for_judging",
]
