"""Checking the judge: a blind hand-labelled sample, and how well the judge agrees with it.

A stratified sample of graded answers is drawn without regard to the judge's scores, written to a
labelling sheet that carries the question, the reference notes, the gold files, the answer and the
cited evidence but neither the judge's scores nor the arm, and labelled by a person with
``correct`` and ``faithful`` from 0 to 3. Agreement between the judge and the labels is the
quadratically weighted kappa with a bootstrap interval, per family; a family whose kappa is below
``EXPLORATORY_BELOW`` has its answer-quality numbers reported as exploratory. The same table
compares two judges on the same generations.

Labels are appended to ``judge_labels.jsonl`` as they are given, so a session that stops resumes
where it left off. Library code here takes nothing from ``evals.settings``.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from evals.gold.schema import canonical_json
from evals.run.judge import EvidenceText, JudgePair, final_judgments, render_evidence
from evals.run.records import Judgment
from evals.stats import weighted_kappa, weighted_kappa_interval

LABELS_NAME = "judge_labels.jsonl"
SHEET_NAME = "judge_sample.jsonl"
DEFAULT_ANNOTATOR = "primary"

PILOT_MIN_LABELS = 40
"""The fewest hand labels the pilot report accepts."""
FULL_PER_FAMILY = 150
"""Labels per family in the full run."""
EXPLORATORY_BELOW = 0.6
DIMENSIONS = ("correct", "faithful")
SCALE = (0, 1, 2, 3)

RULES = """\
Labelling rule: give two scores from 0 to 3, correct then faithful, then an optional note.
  correct   3 fully right, 2 mostly right, 1 partly right, 0 wrong, off topic or empty.
            A question marked unanswerable is answered correctly by saying the repository
            does not contain the answer.
  faithful  3 every claim is supported by the cited evidence, 2 nearly all, 1 several are not,
            0 mostly invented. An answer that cites nothing scores at most 2.
Example:  3 2 the second claim has no support in the cited text
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
        correct: 0 to 3.
        faithful: 0 to 3.
        note: Free text, possibly empty.
        annotator: Who labelled it.
    """

    generation_key: str
    item_id: str
    family: str
    correct: int = Field(ge=0, le=3)
    faithful: int = Field(ge=0, le=3)
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
        dimension: ``correct`` or ``faithful``.
        n: Answers both raters graded.
        agreement: The share graded identically; ``None`` without answers.
        kappa: Quadratically weighted kappa; ``None`` with fewer than two answers.
        lower: The bootstrap interval's lower bound.
        upper: The bootstrap interval's upper bound.
        exploratory: Whether the family's answer-quality numbers must be reported as
            exploratory: kappa unknown or below ``EXPLORATORY_BELOW``.
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


def sample_for_labelling(
    judgments: Iterable[Judgment], *, n: int, seed: int, per_family_min: int = 0
) -> list[Judgment]:
    """A stratified blind sample of the graded answers.

    The sample looks only at each answer's family and key, never at the judge's scores. Every
    family contributes at least ``min(per_family_min, available)``; the rest of ``n`` is shared
    in proportion to what each family has left. When the minimums alone exceed ``n`` they win.
    Judgments reused from another record are left out (the answer was already drawn through its
    target), and so are error records. The order within a family is a hash of the seed and the
    generation key, so it does not depend on input order and a smaller sample is a prefix of a
    larger one.

    Args:
        judgments: The judgments to sample from.
        n: The sample size to aim for.
        seed: The seed of the draw.
        per_family_min: The fewest answers taken from each family.

    Returns:
        The sampled judgments, in a shuffled order that mixes the families.
    """
    pool: dict[str, Judgment] = {}
    for judgment in final_judgments(judgments):
        if judgment.status == "ok" and judgment.reused_from is None:
            pool.setdefault(judgment.generation_key, judgment)
    by_family: dict[str, list[Judgment]] = defaultdict(list)
    for judgment in pool.values():
        by_family[judgment.family].append(judgment)
    for members in by_family.values():
        members.sort(key=lambda j: _rank(seed, j.generation_key))

    take = {family: min(per_family_min, len(members)) for family, members in by_family.items()}
    extra = max(0, min(n, len(pool)) - sum(take.values()))
    room = {family: len(members) - take[family] for family, members in by_family.items()}
    total_room = sum(room.values())
    if extra and total_room:
        shares = {family: extra * room[family] / total_room for family in room}
        for family in room:
            take[family] += min(room[family], math.floor(shares[family]))
        leftover = extra - sum(math.floor(shares[family]) for family in room)
        for family in sorted(room, key=lambda f: (-(shares[f] % 1), f)):
            if leftover <= 0:
                break
            if take[family] < len(by_family[family]):
                take[family] += 1
                leftover -= 1

    chosen = [j for family, members in by_family.items() for j in members[: take[family]]]
    return sorted(chosen, key=lambda j: _rank(seed, j.generation_key))


def build_sheet(
    sample: Iterable[Judgment],
    pairs: Iterable[JudgePair],
    *,
    evidence_for: Callable[[JudgePair], EvidenceText] | None = None,
) -> list[SheetEntry]:
    """The labelling sheet for a sample: what a person needs, without the judge's scores.

    Args:
        sample: The sampled judgments; only their generation keys are used.
        pairs: The generations and items they came from.
        evidence_for: Gives, for a pair, the lookup from a citation key to its text.

    Returns:
        One entry per sampled answer, in the sample's order. A sampled answer with no matching
        pair is left out.
    """
    by_key = {pair.generation.record_key: pair for pair in pairs}
    entries: list[SheetEntry] = []
    for judgment in sample:
        pair = by_key.get(judgment.generation_key)
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
                notes=list(item.gold_answer_notes),
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


def parse_scores(text: str) -> tuple[int, int, str] | str | None:
    """Parses one line of input.

    Args:
        text: What the annotator typed.

    Returns:
        ``(correct, faithful, note)`` for two scores from 0 to 3 and an optional note, ``"s"``
        or ``"q"`` for those commands, and ``None`` for anything else.
    """
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.lower() in ("s", "q"):
        return stripped.lower()
    parts = stripped.split(None, 2)
    if len(parts) < 2 or not all(p in {"0", "1", "2", "3"} for p in parts[:2]):
        return None
    return int(parts[0]), int(parts[1]), parts[2].strip() if len(parts) > 2 else ""


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
                answer = parse_scores(input_fn("correct faithful [note] / s / q> "))
            except EOFError:
                answer = "q"
            if answer is not None:
                break
            print_fn("Type two scores from 0 to 3, or s, or q.")
        if answer == "q":
            quit_early = True
            break
        if answer == "s":
            continue
        assert isinstance(answer, tuple)
        correct, faithful, note = answer
        append_label(
            path,
            HumanLabel(
                generation_key=entry.generation_key,
                item_id=entry.item_id,
                family=entry.family,
                correct=correct,
                faithful=faithful,
                note=note,
                annotator=annotator,
            ),
        )
        written += 1
    return LabelOutcome(labelled=written, remaining=len(pending) - written, quit=quit_early)


# --- agreement -------------------------------------------------------------------------


def _entry(
    family: str, dimension: str, a: list[int], b: list[int], *, resamples: int, seed: int
) -> AgreementEntry:
    n = len(a)
    if n < 2:
        return AgreementEntry(family, dimension, n, None, None, None, None, True)
    kappa = weighted_kappa(a, b, SCALE, "quadratic")
    lower, upper = weighted_kappa_interval(a, b, SCALE, "quadratic", resamples=resamples, seed=seed)
    exact = sum(x == y for x, y in zip(a, b, strict=True)) / n
    return AgreementEntry(
        family, dimension, n, exact, kappa, lower, upper, kappa < EXPLORATORY_BELOW
    )


def _report(
    rows: Mapping[str, tuple[list[int], list[int], list[int], list[int]]],
    *,
    resamples: int,
    seed: int,
    minimum: int,
) -> AgreementReport:
    entries: list[AgreementEntry] = []
    pooled: dict[str, tuple[list[int], list[int]]] = {d: ([], []) for d in DIMENSIONS}
    for family in sorted(rows):
        ca, cb, fa, fb = rows[family]
        entries.append(_entry(family, "correct", ca, cb, resamples=resamples, seed=seed))
        entries.append(_entry(family, "faithful", fa, fb, resamples=resamples, seed=seed))
        pooled["correct"][0].extend(ca)
        pooled["correct"][1].extend(cb)
        pooled["faithful"][0].extend(fa)
        pooled["faithful"][1].extend(fb)
    for dimension in DIMENSIONS:
        a, b = pooled[dimension]
        entries.append(_entry("all", dimension, a, b, resamples=resamples, seed=seed))
    return AgreementReport(entries=entries, n=len(pooled["correct"][0]), minimum=minimum)


def judge_vs_human(
    judgments: Iterable[Judgment],
    labels: Iterable[HumanLabel],
    *,
    resamples: int = 2000,
    seed: int = 0,
    minimum: int = PILOT_MIN_LABELS,
) -> AgreementReport:
    """Agreement between one judge and the hand labels, per family.

    Only answers both graded are compared; error records are ignored.

    Args:
        judgments: One judge's judgments.
        labels: The hand labels.
        resamples: Bootstrap samples for each interval.
        seed: The bootstrap seed.
        minimum: The fewest compared answers the report needs to count.
    """
    graded = {j.generation_key: j for j in final_judgments(judgments) if j.status == "ok"}
    rows: dict[str, tuple[list[int], list[int], list[int], list[int]]] = defaultdict(
        lambda: ([], [], [], [])
    )
    for label in sorted(labels, key=lambda lab: lab.generation_key):
        judgment = graded.get(label.generation_key)
        if judgment is None:
            continue
        assert judgment.correct is not None and judgment.faithful is not None
        row = rows[judgment.family]
        row[0].append(judgment.correct)
        row[1].append(label.correct)
        row[2].append(judgment.faithful)
        row[3].append(label.faithful)
    return _report(rows, resamples=resamples, seed=seed, minimum=minimum)


def judge_vs_judge(
    first: Iterable[Judgment],
    second: Iterable[Judgment],
    *,
    resamples: int = 2000,
    seed: int = 0,
    minimum: int = PILOT_MIN_LABELS,
) -> AgreementReport:
    """Agreement between two judges on the generations both graded, per family."""
    a = {j.generation_key: j for j in final_judgments(first) if j.status == "ok"}
    b = {j.generation_key: j for j in final_judgments(second) if j.status == "ok"}
    rows: dict[str, tuple[list[int], list[int], list[int], list[int]]] = defaultdict(
        lambda: ([], [], [], [])
    )
    for key in sorted(a.keys() & b.keys()):
        left, right = a[key], b[key]
        assert left.correct is not None and left.faithful is not None
        assert right.correct is not None and right.faithful is not None
        row = rows[left.family]
        row[0].append(left.correct)
        row[1].append(right.correct)
        row[2].append(left.faithful)
        row[3].append(right.faithful)
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
    "DIMENSIONS",
    "EXPLORATORY_BELOW",
    "FULL_PER_FAMILY",
    "LABELS_NAME",
    "PILOT_MIN_LABELS",
    "SHEET_NAME",
    "AgreementEntry",
    "AgreementReport",
    "HumanLabel",
    "LabelOutcome",
    "SheetEntry",
    "append_label",
    "build_sheet",
    "describe_entry",
    "format_agreement",
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
