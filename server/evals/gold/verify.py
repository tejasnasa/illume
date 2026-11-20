"""Human verification of a sample of the gold set.

A stratified sample of each family is labelled correct, wrong or ambiguous by a person who
sees the question, the seed it came from and GitHub links to the gold files at the base
commit. The labels give each family's and template's gold error rate with a Wilson
interval; a family or template whose upper bound is above ``DROP_UPPER_BOUND`` is dropped,
judged only on samples of at least ``MIN_JUDGED``. Two annotators' labels give Cohen's kappa.

Labels are appended to ``labels.jsonl`` (or ``labels.<annotator>.jsonl``) as they are given,
so a session that stops resumes where it left off.
"""

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from evals.gold.schema import GoldItem, Verdict, canonical_json
from evals.stats import cohen_kappa, wilson_interval

DEFAULT_FRACTION = 0.15
MIN_PER_FAMILY = 50
MIN_JUDGED = 50
DROP_UPPER_BOUND = 0.20
DEFAULT_ANNOTATOR = "primary"

_ANSWERS: dict[str, Verdict] = {"c": "correct", "w": "wrong", "a": "ambiguous"}

RULES = """\
Labelling rule
  c  correct    every gold file is plausibly required by the question as written
  a  ambiguous  the question does not pin the change down; a reasonable developer could
                change different files
  w  wrong      the gold includes files unrelated to the question (drive-by changes), or
                misses files the question clearly needs
  s  skip       come back to it later          q  quit (labels so far are saved)
Add a note after the letter, for example: w the last file is an unrelated rename
"""


@dataclass(frozen=True)
class Label:
    """One person's verdict on one item.

    Attributes:
        item_id: The item labelled.
        label: ``correct``, ``wrong`` or ``ambiguous``.
        note: Free text, possibly empty.
        annotator: Who labelled it.
    """

    item_id: str
    label: Verdict
    note: str = ""
    annotator: str = DEFAULT_ANNOTATOR


@dataclass(frozen=True)
class GroupStats:
    """The error rate of one family or template.

    Attributes:
        name: The family or template.
        n_labelled: Items labelled, ambiguous ones included.
        n_ambiguous: Items labelled ambiguous; kept out of the rate's denominator.
        n_wrong: Items labelled wrong.
        n_scored: Items labelled correct or wrong.
        rate: ``n_wrong / n_scored``; ``None`` when nothing was scored.
        lower: The Wilson 95% interval's lower bound.
        upper: The Wilson 95% interval's upper bound.
        judged: Whether the sample is large enough (``MIN_JUDGED`` labelled) for the drop
            rule to apply.
        dropped: Whether the drop rule fires: judged and ``upper`` above the threshold.
    """

    name: str
    n_labelled: int
    n_ambiguous: int
    n_wrong: int
    n_scored: int
    rate: float | None
    lower: float
    upper: float
    judged: bool
    dropped: bool


@dataclass(frozen=True)
class ErrorReport:
    """Gold error rates per family and per template.

    Attributes:
        families: Statistics by family.
        templates: Statistics by template; a template with fewer than ``MIN_JUDGED`` labels
            is never dropped on its own, only through its family, which pools it.
    """

    families: dict[str, GroupStats] = field(default_factory=dict)
    templates: dict[str, GroupStats] = field(default_factory=dict)

    @property
    def dropped_families(self) -> frozenset[str]:
        """The families the drop rule removes."""
        return frozenset(name for name, stats in self.families.items() if stats.dropped)

    @property
    def dropped_templates(self) -> frozenset[str]:
        """The templates the drop rule removes on their own sample."""
        return frozenset(name for name, stats in self.templates.items() if stats.dropped)


@dataclass(frozen=True)
class AgreementReport:
    """Agreement between two annotators.

    Attributes:
        n: Items both labelled.
        agreement: The share of those items labelled identically; ``None`` when ``n`` is 0.
        kappa: Cohen's kappa over them; ``None`` when ``n`` is 0.
    """

    n: int
    agreement: float | None
    kappa: float | None


@dataclass(frozen=True)
class VerifyOutcome:
    """How an interactive session ended.

    Attributes:
        labelled: Labels written this session.
        remaining: Sampled items still unlabelled.
        quit: Whether the annotator quit (or input ended) before finishing.
    """

    labelled: int
    remaining: int
    quit: bool


# --- sampling -----------------------------------------------------------------------


def _rank(seed: int, item_id: str) -> str:
    return hashlib.sha256(f"{seed}:{item_id}".encode()).hexdigest()


def sample_for_verification(
    items: Iterable[GoldItem],
    *,
    seed: int,
    fraction: float = DEFAULT_FRACTION,
    min_per_family: int = MIN_PER_FAMILY,
) -> list[GoldItem]:
    """Pick the items to label, stratified by family.

    A family with at most ``min_per_family`` items is taken whole; a larger one contributes
    ``max(ceil(fraction * size), min_per_family)`` items, chosen by a hash of the seed and
    the item id so the sample does not depend on input order.

    Args:
        items: Every item.
        seed: Sampling seed.
        fraction: The share of a large family to label.
        min_per_family: The smallest sample drawn from a family.

    Returns:
        The sampled items, sorted by family then id.
    """
    by_family: dict[str, list[GoldItem]] = defaultdict(list)
    for item in items:
        by_family[item.family].append(item)
    sampled: list[GoldItem] = []
    for family in sorted(by_family):
        members = by_family[family]
        if len(members) <= min_per_family:
            chosen = members
        else:
            take = max(math.ceil(fraction * len(members)), min_per_family)
            chosen = sorted(members, key=lambda item: _rank(seed, item.id))[:take]
        sampled.extend(sorted(chosen, key=lambda item: item.id))
    return sampled


# --- labels on disk -------------------------------------------------------------------


def labels_path(directory: Path, annotator: str | None = None) -> Path:
    """Where an annotator's labels live: ``labels.jsonl`` or ``labels.<annotator>.jsonl``."""
    if not annotator:
        return Path(directory) / "labels.jsonl"
    return Path(directory) / f"labels.{annotator}.jsonl"


def read_labels(path: Path) -> list[Label]:
    """Read a labels file; when an item was labelled twice the last verdict wins.

    Args:
        path: A ``labels`` file; a missing file reads as empty.

    Returns:
        One label per item, in the order the items first appeared.
    """
    if not Path(path).exists():
        return []
    latest: dict[str, Label] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        latest[record["item_id"]] = Label(
            item_id=record["item_id"],
            label=record["label"],
            note=record.get("note", ""),
            annotator=record.get("annotator", DEFAULT_ANNOTATOR),
        )
    return list(latest.values())


def append_label(path: Path, label: Label) -> None:
    """Append one label to a labels file, creating it if needed."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "item_id": label.item_id,
        "label": label.label,
        "note": label.note,
        "annotator": label.annotator,
    }
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(record) + "\n")


# --- the interactive loop -----------------------------------------------------------


def blob_url(slug: str, sha: str, path: str) -> str:
    """The GitHub link to a file at a commit."""
    return f"https://github.com/{slug}/blob/{sha}/{path}"


def describe_item(item: GoldItem, *, slug: str, index: int, total: int) -> str:
    """Render one item for the annotator.

    Args:
        item: The item.
        slug: The ``owner/repo`` GitHub slug.
        index: This item's 1-based position in the session.
        total: How many items the session covers.

    Returns:
        The question, the seed when it differs, the gold files as links at the base commit
        (tests marked), the anchor, and links to the pull requests and commits.
    """
    lines = [
        "",
        f"[{index}/{total}] {item.family} / {item.template}   id {item.id}",
        f"Question: {item.question or item.question_seed}",
    ]
    if item.question and item.question != item.question_seed:
        lines.append(f"Seed:     {item.question_seed}")
    if item.anchor_file:
        lines.append(f"Anchor (named in the question): {item.anchor_file}")
    lines.append("Gold files:")
    tests = set(item.gold_test_files)
    for path in item.gold_files:
        mark = "  [test]" if path in tests else ""
        lines.append(f"  {blob_url(slug, item.base_commit, path)}{mark}")
    if not item.gold_files:
        lines.append("  (none: the question should be unanswerable)")
    for number in item.gold_prs:
        lines.append(f"PR: https://github.com/{slug}/pull/{number}")
    for commit in item.gold_commits:
        lines.append(f"Commit: https://github.com/{slug}/commit/{commit}")
    for note in item.gold_answer_notes:
        lines.append(f"Fact: {note}")
    return "\n".join(lines)


def parse_answer(text: str) -> tuple[str, str] | None:
    """Parse one line of input.

    Args:
        text: What the annotator typed.

    Returns:
        ``(command, note)`` where the command is ``c``, ``w``, ``a``, ``s`` or ``q``; ``None``
        when the input is not a command.
    """
    stripped = text.strip()
    if not stripped:
        return None
    command, _, note = stripped.partition(" ")
    command = command.lower()
    if command not in {*_ANSWERS, "s", "q"}:
        return None
    return command, note.strip()


def run_verification(
    items: Sequence[GoldItem],
    *,
    slug: str,
    path: Path,
    annotator: str = DEFAULT_ANNOTATOR,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
) -> VerifyOutcome:
    """Show each unlabelled item and record the verdicts.

    Items already in ``path`` are skipped, so a stopped session resumes. A skipped item is
    not recorded and appears again in the next session.

    Args:
        items: The sampled items.
        slug: The ``owner/repo`` GitHub slug, for the links.
        path: The labels file to append to.
        annotator: Recorded with each label.
        input_fn: Reads a line; ``EOFError`` ends the session like ``q``.
        print_fn: Prints a block of text.

    Returns:
        How many labels were written and how many sampled items remain unlabelled.
    """
    done = {label.item_id for label in read_labels(path)}
    pending = [item for item in items if item.id not in done]
    total = len(pending)
    print_fn(RULES)
    written = 0
    quit_early = False
    for position, item in enumerate(pending, start=1):
        print_fn(describe_item(item, slug=slug, index=position, total=total))
        while True:
            try:
                answer = parse_answer(input_fn("label [c/w/a/s/q]> "))
            except EOFError:
                answer = ("q", "")
            if answer is not None:
                break
            print_fn("Type c, w, a, s or q, optionally followed by a note.")
        command, note = answer
        if command == "q":
            quit_early = True
            break
        if command == "s":
            continue
        append_label(
            path, Label(item_id=item.id, label=_ANSWERS[command], note=note, annotator=annotator)
        )
        written += 1
    remaining = total - written
    return VerifyOutcome(labelled=written, remaining=remaining, quit=quit_early)


# --- reports --------------------------------------------------------------------------


def _stats(name: str, verdicts: list[str]) -> GroupStats:
    n_labelled = len(verdicts)
    n_ambiguous = verdicts.count("ambiguous")
    n_wrong = verdicts.count("wrong")
    n_scored = n_labelled - n_ambiguous
    lower, upper = wilson_interval(n_wrong, n_scored)
    judged = n_labelled >= MIN_JUDGED
    return GroupStats(
        name=name,
        n_labelled=n_labelled,
        n_ambiguous=n_ambiguous,
        n_wrong=n_wrong,
        n_scored=n_scored,
        rate=(n_wrong / n_scored) if n_scored else None,
        lower=lower,
        upper=upper,
        judged=judged,
        dropped=judged and upper > DROP_UPPER_BOUND,
    )


def gold_error_report(items: Iterable[GoldItem], labels: Iterable[Label]) -> ErrorReport:
    """Per family and per template: how many were labelled wrong, with a Wilson interval.

    Ambiguous items are left out of the denominator and counted separately. The drop rule
    applies to a group whose labelled sample is at least ``MIN_JUDGED``; the family
    statistics pool every template of the family, so a small template is judged there.

    Args:
        items: The items.
        labels: The verdicts; labels for unknown items are ignored.

    Returns:
        The statistics, family by family and template by template.
    """
    verdict_of = {label.item_id: label.label for label in labels}
    by_family: dict[str, list[str]] = defaultdict(list)
    by_template: dict[str, list[str]] = defaultdict(list)
    for item in items:
        verdict = verdict_of.get(item.id)
        if verdict is None:
            continue
        by_family[item.family].append(verdict)
        by_template[item.template].append(verdict)
    return ErrorReport(
        families={name: _stats(name, by_family[name]) for name in sorted(by_family)},
        templates={name: _stats(name, by_template[name]) for name in sorted(by_template)},
    )


def agreement_report(labels_a: Iterable[Label], labels_b: Iterable[Label]) -> AgreementReport:
    """Cohen's kappa between two annotators on the items both labelled.

    Args:
        labels_a: The first annotator's labels.
        labels_b: The second annotator's labels.

    Returns:
        The overlap size, the raw agreement and kappa.
    """
    first = {label.item_id: label.label for label in labels_a}
    second = {label.item_id: label.label for label in labels_b}
    shared = sorted(first.keys() & second.keys())
    if not shared:
        return AgreementReport(n=0, agreement=None, kappa=None)
    a = [first[item_id] for item_id in shared]
    b = [second[item_id] for item_id in shared]
    agreement = sum(x == y for x, y in zip(a, b, strict=True)) / len(shared)
    return AgreementReport(n=len(shared), agreement=agreement, kappa=cohen_kappa(a, b))


def apply_labels(items: Iterable[GoldItem], labels: Iterable[Label]) -> list[GoldItem]:
    """Build the scoreable set from the labels.

    Labelled items get ``verified`` set; ambiguous and wrong ones are removed, and so is
    every item of a dropped family or template. Items that were not sampled stay, unverified:
    the sample's error rate stands for them.

    Args:
        items: The items.
        labels: The verdicts.

    Returns:
        The surviving items in input order.
    """
    items = list(items)
    labels = list(labels)
    report = gold_error_report(items, labels)
    verdict_of = {label.item_id: label.label for label in labels}
    dropped_families = report.dropped_families
    dropped_templates = report.dropped_templates
    kept: list[GoldItem] = []
    for item in items:
        if item.family in dropped_families or item.template in dropped_templates:
            continue
        verdict = verdict_of.get(item.id)
        if verdict in ("wrong", "ambiguous"):
            continue
        kept.append(item.model_copy(update={"verified": verdict}) if verdict else item)
    return kept


def format_error_report(report: ErrorReport) -> str:
    """Render the error report as a text table."""
    header = f"{'group':<28}{'n':>5}{'amb':>5}{'wrong':>6}{'rate':>8}{'95% interval':>20}  verdict"
    rows = [header]
    for title, group in (("family", report.families), ("template", report.templates)):
        rows.append(f"-- {title}")
        for stats in group.values():
            rate = "-" if stats.rate is None else f"{stats.rate:.1%}"
            interval = f"{stats.lower:.1%} to {stats.upper:.1%}"
            if stats.dropped:
                verdict = "DROP"
            elif not stats.judged:
                verdict = f"not judged (< {MIN_JUDGED} labelled)"
            else:
                verdict = "keep"
            rows.append(
                f"{stats.name:<28}{stats.n_labelled:>5}{stats.n_ambiguous:>5}"
                f"{stats.n_wrong:>6}{rate:>8}{interval:>20}  {verdict}"
            )
    return "\n".join(rows)
