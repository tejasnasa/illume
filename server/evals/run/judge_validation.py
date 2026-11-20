"""Checking the judge: a small blind hand-labelled sample, and how well DeepEval agrees with it.

A sample of 30 judged answers is drawn without regard to the judge's scores, spread across arms and
question kinds, and written to a labelling sheet that carries the question, the reference notes,
the gold files, the answer and the cited evidence but neither the scores nor the arm. A person
labels each one ``correct``, ``partly`` or ``wrong``, and whether the answer made something up.
The labels are compared with the binned DeepEval scores: correctness by quadratically weighted
kappa with a bootstrap interval and by raw agreement, and made-something-up (against
``UNFAITHFUL_BELOW``) the same way. A family whose correctness kappa is below ``EXPLORATORY_BELOW``
has its judged numbers reported as exploratory. The same table compares two judges on the same
generations.

Labels are appended to ``judge_labels.jsonl`` as they are given, so a session that stops resumes
where it left off. Library code here takes nothing from ``evals.settings``.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from evals.gold.schema import canonical_json
from evals.run.judge import (
    EvidenceText,
    Grade,
    JudgePair,
    grades_by_generation,
    render_evidence,
)
from evals.run.judge_metrics import reference_answer
from evals.run.records import Judgment
from evals.stats import weighted_kappa, weighted_kappa_interval

LABELS_NAME = "judge_labels.jsonl"
SHEET_NAME = "judge_sample.jsonl"
DEFAULT_ANNOTATOR = "primary"

LABEL_SAMPLE_SIZE = 30
"""How many answers are hand-labelled to check the judge."""
MIN_LABELS = LABEL_SAMPLE_SIZE
"""The fewest hand labels the report accepts."""
EXPLORATORY_BELOW = 0.6
UNFAITHFUL_BELOW = 0.8
"""A faithfulness score under this counts as the judge saying the answer made something up."""

Correctness = Literal["correct", "partly", "wrong"]
CORRECTNESS_LEVELS: dict[str, int] = {"wrong": 0, "partly": 1, "correct": 2}
"""The three correctness labels as positions on an ordered scale."""
RUBRIC_TO_LEVEL: dict[int, int] = {0: 0, 1: 1, 2: 2, 3: 2}
"""A 0 to 3 correctness rubric value as a label level: 0 wrong, 1 partly, 2 and 3 correct."""
DIMENSIONS = ("correct", "made_up")
CORRECT_SCALE = (0, 1, 2)
MADE_UP_SCALE = (0, 1)

RULES = """\
Labelling rule: correctness first, then whether the answer made anything up, then an
optional note.
  correct   c = right: it says what the reference says and names the needed files
            p = partly right: the main point is there but a key part is missing, vague or wrong
            w = wrong, off topic or empty
  made up   y = it states something the cited evidence does not support, or invents it
            n = every claim is backed by the cited evidence (an answer citing nothing is y if it
                states specifics)
Example:  p y the second claim has no support in the cited text
  s  skip for now          q  quit (labels so far are saved)
"""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SheetEntry(_Model):
    """One answer to label, with nothing that reveals the judge's scores or the arm.

    Attributes:
        generation_key: The generation labelled.
        item_id: The gold item.
        family: The item's family.
        question: The question.
        unanswerable: Whether the question cannot be answered from the repository.
        notes: The reference notes.
        gold_files: The files a correct answer relies on.
        acceptable_files: Other acceptable files.
        answer: The answer.
        evidence: The cited evidence as the judge was shown it.
    """

    generation_key: str
    item_id: str
    family: str
    question: str
    unanswerable: bool = False
    notes: list[str] = Field(default_factory=list)
    gold_files: list[str] = Field(default_factory=list)
    acceptable_files: list[str] = Field(default_factory=list)
    answer: str
    evidence: str


class HumanLabel(_Model):
    """A person's grade of one answer.

    Attributes:
        generation_key: The generation labelled.
        item_id: The gold item.
        family: The item's family.
        correct: ``correct``, ``partly`` or ``wrong``.
        made_something_up: Whether the answer states something the cited evidence does not
            support.
        note: Free text, possibly empty.
        annotator: Who labelled it.
    """

    generation_key: str
    item_id: str
    family: str
    correct: Correctness
    made_something_up: bool
    note: str = ""
    annotator: str = DEFAULT_ANNOTATOR


@dataclass(frozen=True)
class LabelOutcome:
    """How a labelling session ended.

    Attributes:
        labelled: Labels written this session.
        remaining: Sampled answers still unlabelled.
        quit: Whether the annotator quit (or input ended) before finishing.
    """

    labelled: int
    remaining: int
    quit: bool


@dataclass(frozen=True)
class AgreementEntry:
    """Agreement on one dimension in one family.

    Attributes:
        family: The family, or ``all``.
        dimension: ``correct`` (three bins) or ``made_up`` (two).
        n: Answers both raters graded.
        agreement: The share graded identically; ``None`` without answers.
        kappa: Quadratically weighted kappa (plain kappa on two bins); ``None`` with fewer than
            two answers.
        lower: The bootstrap interval's lower bound.
        upper: The bootstrap interval's upper bound.
        exploratory: Whether the family's judged numbers must be reported as exploratory:
            kappa unknown or below ``EXPLORATORY_BELOW``.
    """

    family: str
    dimension: str
    n: int
    agreement: float | None
    kappa: float | None
    lower: float | None
    upper: float | None
    exploratory: bool


@dataclass(frozen=True)
class AgreementReport:
    """Agreement per family and dimension.

    Attributes:
        entries: One per family and dimension, then the pooled ``all`` rows.
        n: Answers both raters graded.
        minimum: The fewest answers the report needs to count.
    """

    entries: list[AgreementEntry]
    n: int
    minimum: int

    @property
    def meets_minimum(self) -> bool:
        """Whether enough answers were compared."""
        return self.n >= self.minimum

    @property
    def exploratory_families(self) -> frozenset[str]:
        """The families flagged exploratory on either dimension (pooled row excluded)."""
        return frozenset(e.family for e in self.entries if e.exploratory and e.family != "all")


# --- sampling and the sheet ------------------------------------------------------------


def _rank(seed: int, key: str) -> str:
    return hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()


def sample_for_labelling(grades: Iterable[Grade], *, n: int, seed: int) -> list[Grade]:
    """A stratified blind sample of the judged answers, spread across arms and question kinds.

    The strata are the family and the arm. The draw takes one answer from each stratum in turn,
    in a seeded order, until ``n`` are chosen or the strata run dry, so no stratum is taken from
    twice before every other has been taken from once. It looks only at each answer's arm,
    family and key, never at the scores. Answers whose grades were copied from another answer's,
    and answers without grades for both correctness and faithfulness, are left out. Within a
    stratum the order is a hash of the seed and the generation key, so it does not depend on
    input order and a smaller sample is a prefix of a larger one.

    Args:
        grades: One row per judged generation.
        n: The sample size.
        seed: The seed of the draw.

    Returns:
        The sampled rows, in a shuffled order that mixes the strata.
    """
    strata: dict[tuple[str, str], list[Grade]] = defaultdict(list)
    seen: set[str] = set()
    for grade in grades:
        if grade.status != "ok" or grade.reused or grade.generation_key in seen:
            continue
        seen.add(grade.generation_key)
        strata[(grade.family, grade.arm)].append(grade)
    for members in strata.values():
        members.sort(key=lambda g: _rank(seed, g.generation_key))
    order = sorted(strata, key=lambda stratum: (_rank(seed, "/".join(stratum)), stratum))
    chosen: list[Grade] = []
    depth = 0
    while len(chosen) < n and any(len(strata[s]) > depth for s in order):
        for stratum in order:
            if len(chosen) >= n:
                break
            if len(strata[stratum]) > depth:
                chosen.append(strata[stratum][depth])
        depth += 1
    return sorted(chosen, key=lambda g: _rank(seed, g.generation_key))


def build_sheet(
    sample: Iterable[Grade],
    pairs: Iterable[JudgePair],
    *,
    evidence_for: Callable[[JudgePair], EvidenceText] | None = None,
) -> list[SheetEntry]:
    """The labelling sheet for a sample: what a person needs, without the judge's scores.

    Args:
        sample: The sampled rows; only their generation keys are used.
        pairs: The generations and items they came from.
        evidence_for: Gives, for a pair, the lookup from a citation key to its text.

    Returns:
        One entry per sampled answer, in the sample's order. A sampled answer with no matching
        pair is left out.
    """
    by_key = {pair.generation.record_key: pair for pair in pairs}
    entries: list[SheetEntry] = []
    for graded in sample:
        pair = by_key.get(graded.generation_key)
        if pair is None:
            continue
        item = pair.item
        lookup: EvidenceText = evidence_for(pair) if evidence_for is not None else (lambda k: None)
        entries.append(
            SheetEntry(
                generation_key=pair.generation.record_key,
                item_id=item.id,
                family=item.family,
                question=item.question or item.question_seed,
                unanswerable="unanswerable" in item.tags,
                notes=[reference_answer(item)],
                gold_files=list(item.gold_files),
                acceptable_files=list(item.acceptable_files),
                answer=pair.generation.answer,
                evidence=render_evidence(pair.generation, lookup),
            )
        )
    return entries


def write_sheet(path: Path, entries: Iterable[SheetEntry]) -> Path:
    """Writes the labelling sheet as JSONL, replacing any earlier one."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(canonical_json(e.model_dump(mode="json")) + "\n" for e in entries)
    target.write_bytes(text.encode("utf-8"))
    return target


def read_sheet(path: Path) -> list[SheetEntry]:
    """Reads a labelling sheet; a missing file reads as empty."""
    if not Path(path).exists():
        return []
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [SheetEntry.model_validate_json(line) for line in lines if line.strip()]


# --- labels on disk --------------------------------------------------------------------


def labels_path(directory: Path, annotator: str | None = None) -> Path:
    """Where an annotator's labels live: ``judge_labels.jsonl`` or ``judge_labels.<name>.jsonl``."""
    if not annotator:
        return Path(directory) / LABELS_NAME
    return Path(directory) / f"judge_labels.{annotator}.jsonl"


def read_labels(path: Path) -> list[HumanLabel]:
    """Reads a labels file; when an answer was labelled twice the last labels win."""
    if not Path(path).exists():
        return []
    latest: dict[str, HumanLabel] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            label = HumanLabel.model_validate(json.loads(line))
            latest[label.generation_key] = label
    return list(latest.values())


def append_label(path: Path, label: HumanLabel) -> None:
    """Appends one label to a labels file, creating it if needed."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(label.model_dump(mode="json")) + "\n")


# --- the interactive loop --------------------------------------------------------------


def describe_entry(entry: SheetEntry, *, index: int, total: int) -> str:
    """Renders one answer for the annotator, with no judge scores and no arm."""
    lines = [
        "",
        f"[{index}/{total}] {entry.family}   id {entry.item_id}",
        f"Question: {entry.question}",
    ]
    if entry.unanswerable:
        lines.append("(unanswerable: the repository does not contain the answer)")
    lines.append("Reference notes:")
    lines += [f"  - {note}" for note in entry.notes] or ["  (none)"]
    lines.append("Gold files:")
    lines += [f"  {path}" for path in entry.gold_files] or ["  (none)"]
    if entry.acceptable_files:
        lines.append("Also acceptable:")
        lines += [f"  {path}" for path in entry.acceptable_files]
    lines += ["Answer:", entry.answer.strip() or "(empty)", "Cited evidence:", entry.evidence]
    return "\n".join(lines)


_CORRECT_CODES: dict[str, Correctness] = {"c": "correct", "p": "partly", "w": "wrong"}


def parse_scores(text: str) -> tuple[Correctness, bool, str] | str | None:
    """Parses one line of input.

    Args:
        text: What the annotator typed.

    Returns:
        ``(correct, made_something_up, note)`` for ``c``, ``p`` or ``w``, then ``y`` or ``n``,
        and an optional note; ``"s"`` or ``"q"`` for those commands; and ``None`` for anything
        else.
    """
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.lower() in ("s", "q"):
        return stripped.lower()
    parts = stripped.split(None, 2)
    if len(parts) < 2:
        return None
    if parts[0].lower() not in _CORRECT_CODES or parts[1].lower() not in ("y", "n"):
        return None
    return (
        _CORRECT_CODES[parts[0].lower()],
        parts[1].lower() == "y",
        parts[2].strip() if len(parts) > 2 else "",
    )


def run_labelling(
    entries: Sequence[SheetEntry],
    *,
    path: Path,
    annotator: str = DEFAULT_ANNOTATOR,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
) -> LabelOutcome:
    """Shows each unlabelled answer and records the scores.

    Answers already in ``path`` are skipped, so a stopped session resumes. A skipped answer is
    not recorded and appears again next session.

    Args:
        entries: The sheet.
        path: The labels file to append to.
        annotator: Recorded with each label.
        input_fn: Reads a line; ``EOFError`` ends the session like ``q``.
        print_fn: Prints a block of text.

    Returns:
        How many labels were written and how many sampled answers remain unlabelled.
    """
    done = {label.generation_key for label in read_labels(path)}
    pending = [entry for entry in entries if entry.generation_key not in done]
    print_fn(RULES)
    written = 0
    quit_early = False
    for position, entry in enumerate(pending, start=1):
        print_fn(describe_entry(entry, index=position, total=len(pending)))
        while True:
            try:
                answer = parse_scores(input_fn("c|p|w y|n [note] / s / q> "))
            except EOFError:
                answer = "q"
            if answer is not None:
                break
            print_fn("Type c, p or w, then y or n (then a note), or s, or q.")
        if answer == "q":
            quit_early = True
            break
        if answer == "s":
            continue
        assert isinstance(answer, tuple)
        correct, made_up, note = answer
        append_label(
            path,
            HumanLabel(
                generation_key=entry.generation_key,
                item_id=entry.item_id,
                family=entry.family,
                correct=correct,
                made_something_up=made_up,
                note=note,
                annotator=annotator,
            ),
        )
        written += 1
    return LabelOutcome(labelled=written, remaining=len(pending) - written, quit=quit_early)


# --- agreement -------------------------------------------------------------------------


Pairs = tuple[list[int], list[int]]


def _entry(
    family: str,
    dimension: str,
    a: list[int],
    b: list[int],
    scale: Sequence[int],
    *,
    resamples: int,
    seed: int,
) -> AgreementEntry:
    n = len(a)
    if n < 2:
        return AgreementEntry(family, dimension, n, None, None, None, None, True)
    kappa = weighted_kappa(a, b, scale, "quadratic")
    lower, upper = weighted_kappa_interval(a, b, scale, "quadratic", resamples=resamples, seed=seed)
    exact = sum(x == y for x, y in zip(a, b, strict=True)) / n
    return AgreementEntry(
        family, dimension, n, exact, kappa, lower, upper, kappa < EXPLORATORY_BELOW
    )


def _report(
    rows: Mapping[str, Mapping[str, Pairs]], *, resamples: int, seed: int, minimum: int
) -> AgreementReport:
    scales = {"correct": CORRECT_SCALE, "made_up": MADE_UP_SCALE}
    entries: list[AgreementEntry] = []
    pooled: dict[str, Pairs] = {d: ([], []) for d in DIMENSIONS}
    for family in sorted(rows):
        for dimension in DIMENSIONS:
            a, b = rows[family][dimension]
            entries.append(
                _entry(family, dimension, a, b, scales[dimension], resamples=resamples, seed=seed)
            )
            pooled[dimension][0].extend(a)
            pooled[dimension][1].extend(b)
    for dimension in DIMENSIONS:
        a, b = pooled[dimension]
        entries.append(
            _entry("all", dimension, a, b, scales[dimension], resamples=resamples, seed=seed)
        )
    return AgreementReport(entries=entries, n=len(pooled["correct"][0]), minimum=minimum)


def _new_rows() -> defaultdict[str, dict[str, Pairs]]:
    return defaultdict(lambda: {d: ([], []) for d in DIMENSIONS})


def judge_levels(grade: Grade) -> tuple[int, int]:
    """DeepEval's grades as the label scales: ``(correctness level, made-something-up)``.

    Correctness is the rubric value binned by ``RUBRIC_TO_LEVEL``; made-something-up is 1 when the
    faithfulness score is below ``UNFAITHFUL_BELOW``.

    Raises:
        ValueError: When the row lacks a correctness or faithfulness grade.
    """
    if grade.correct is None or grade.faithful_score is None:
        raise ValueError("the answer has no correctness and faithfulness grades")
    return RUBRIC_TO_LEVEL[grade.correct], int(grade.faithful_score < UNFAITHFUL_BELOW)


def judge_vs_human(
    grades: Iterable[Grade],
    labels: Iterable[HumanLabel],
    *,
    resamples: int = 2000,
    seed: int = 0,
    minimum: int = MIN_LABELS,
) -> AgreementReport:
    """Agreement between one judge and the hand labels, per family.

    Only answers both graded are compared.

    Args:
        grades: One judge's per-generation rows.
        labels: The hand labels.
        resamples: Bootstrap samples for each interval.
        seed: The bootstrap seed.
        minimum: The fewest compared answers the report needs to count.
    """
    graded = {g.generation_key: g for g in grades if g.status == "ok"}
    rows = _new_rows()
    for label in sorted(labels, key=lambda lab: lab.generation_key):
        grade = graded.get(label.generation_key)
        if grade is None:
            continue
        correct, made_up = judge_levels(grade)
        row = rows[grade.family]
        row["correct"][0].append(correct)
        row["correct"][1].append(CORRECTNESS_LEVELS[label.correct])
        row["made_up"][0].append(made_up)
        row["made_up"][1].append(int(label.made_something_up))
    return _report(rows, resamples=resamples, seed=seed, minimum=minimum)


def judge_vs_judge(
    first: Iterable[Judgment],
    second: Iterable[Judgment],
    *,
    resamples: int = 2000,
    seed: int = 0,
    minimum: int = MIN_LABELS,
) -> AgreementReport:
    """Agreement between two judges on the generations both graded, per family."""
    a = {g.generation_key: g for g in grades_by_generation(first) if g.status == "ok"}
    b = {g.generation_key: g for g in grades_by_generation(second) if g.status == "ok"}
    rows = _new_rows()
    for key in sorted(a.keys() & b.keys()):
        left, right = a[key], b[key]
        (lc, lm), (rc, rm) = judge_levels(left), judge_levels(right)
        row = rows[left.family]
        row["correct"][0].append(lc)
        row["correct"][1].append(rc)
        row["made_up"][0].append(lm)
        row["made_up"][1].append(rm)
    return _report(rows, resamples=resamples, seed=seed, minimum=minimum)


def format_agreement(report: AgreementReport, *, title: str) -> str:
    """Renders an agreement report as a text table."""
    header = (
        f"{'family':<12}{'scale':<10}{'n':>5}{'exact':>8}{'kappa':>8}{'95% interval':>20}  note"
    )
    rows = [title, header]
    for entry in report.entries:
        if entry.kappa is None:
            kappa, interval, exact = "-", "-", "-"
        else:
            kappa = f"{entry.kappa:.2f}"
            interval = f"{entry.lower:.2f} to {entry.upper:.2f}"
            exact = f"{entry.agreement:.0%}" if entry.agreement is not None else "-"
        note = "exploratory" if entry.exploratory and entry.family != "all" else ""
        rows.append(
            f"{entry.family:<12}{entry.dimension:<10}{entry.n:>5}{exact:>8}{kappa:>8}"
            f"{interval:>20}  {note}"
        )
    if not report.meets_minimum:
        rows.append(f"only {report.n} compared; at least {report.minimum} are needed")
    return "\n".join(rows)


__all__ = [
    "CORRECTNESS_LEVELS",
    "DIMENSIONS",
    "EXPLORATORY_BELOW",
    "LABELS_NAME",
    "LABEL_SAMPLE_SIZE",
    "MIN_LABELS",
    "RUBRIC_TO_LEVEL",
    "SHEET_NAME",
    "UNFAITHFUL_BELOW",
    "AgreementEntry",
    "AgreementReport",
    "HumanLabel",
    "LabelOutcome",
    "SheetEntry",
    "append_label",
    "build_sheet",
    "describe_entry",
    "format_agreement",
    "judge_levels",
    "judge_vs_human",
    "judge_vs_judge",
    "labels_path",
    "parse_scores",
    "read_labels",
    "read_sheet",
    "run_labelling",
    "sample_for_labelling",
    "write_sheet",
]
