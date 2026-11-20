"""``run judge``, ``run judge-label`` and ``run judge-agreement``: the judge pass from the CLI.

``run judge`` grades the selected generations of a run with the chosen judge (three DeepEval
metrics each), writes that judge's own ``judgments.<judge>.jsonl`` and a judge manifest beside the
run's, and draws the blind sample of 30 answers a person labels. ``judge-label`` is the
interactive labelling session. ``judge-agreement`` reports how well a judge agrees with the
labels, or with a second judge, per family.

Nothing here touches ``generations.jsonl``. Tests inject the client, the price table and the
evidence lookup; the real ones are used only when they are omitted.

Library code here takes nothing from ``evals.settings``; the entry point passes in what it needs.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from evals.cli.run_commands import run_dir_for
from evals.corpus.corpus import CORPUS_PATH, CorpusError, load_corpus
from evals.gold.schema import GoldItem, read_jsonl
from evals.manifest import MANIFEST_NAME, write_manifest
from evals.run.budget import Budget
from evals.run.endpoint import JudgeConfigError, JudgeEndpoint
from evals.run.evidence import evidence_for_items
from evals.run.generate import GENERATIONS, ROUTES, read_generations, read_routes
from evals.run.judge import (
    CHANGESET_FRACTION,
    EvidenceText,
    all_judgments,
    final_judgments,
    grades_by_generation,
    judge_all,
    judgments_path,
    read_judgments,
    select_for_judging,
)
from evals.run.judge_metrics import metric_configs
from evals.run.judge_validation import (
    LABEL_SAMPLE_SIZE,
    MIN_LABELS,
    SHEET_NAME,
    build_sheet,
    format_agreement,
    judge_vs_human,
    judge_vs_judge,
    labels_path,
    read_labels,
    read_sheet,
    run_labelling,
    sample_for_labelling,
    write_sheet,
)
from evals.run.metering import Meter
from evals.run.pricing import PRICES_PATH, PricesIncomplete, PriceTable

DEFAULT_SAMPLE_SIZE = LABEL_SAMPLE_SIZE


def judge_manifest_name(endpoint: JudgeEndpoint) -> str:
    """The judge manifest's file name; it sits beside the run's own ``manifest.json``."""
    return f"manifest.judge.{endpoint.slug}.json"


def _load_items(out_dir: Path, run_dir: Path) -> list[GoldItem] | None:
    """The gold items of the slice a run was generated from, or ``None`` with a message printed."""
    manifest = run_dir / MANIFEST_NAME
    if not manifest.exists():
        print(f"{manifest} not found; generate the run first", file=sys.stderr)
        return None
    slice_name = (json.loads(manifest.read_text(encoding="utf-8")).get("run") or {}).get("slice")
    source = Path(out_dir) / "gold" / f"{slice_name}.jsonl"
    if not slice_name or not source.exists():
        print(f"the run's slice {slice_name!r} has no gold file at {source}", file=sys.stderr)
        return None
    return read_jsonl(source)


def _write_judge_manifest(
    run_dir: Path,
    endpoint: JudgeEndpoint,
    table: PriceTable,
    reported: set[str],
    judged_on: str,
) -> None:
    """Writes the judge's manifest, carrying over the run's own pins and recording the judge."""
    base: dict[str, Any] = {}
    manifest = run_dir / MANIFEST_NAME
    if manifest.exists():
        base = json.loads(manifest.read_text(encoding="utf-8"))
    models = dict(base.get("models") or {})
    models["judge"] = endpoint.model
    write_manifest(
        run_dir,
        name=judge_manifest_name(endpoint),
        arms=base.get("arms") or {},
        prompt_version=base.get("prompt_version") or "",
        models=models,
        reported_snapshots={"judge": ",".join(sorted(reported))} if reported else {},
        price_table_version=table.version,
        agent_token_cap=base.get("agent_token_cap") or 0,
        corpus_pins=base.get("corpus_pins") or {},
        split_hash=base.get("split_hash") or "",
        eval_instruction=base.get("eval_instruction") or "",
        extra={
            "kind": "judge",
            "judge": {
                **metric_configs(),
                "model": endpoint.model,
                "host": endpoint.host,
                "api_style": endpoint.api_style,
                "judged_on": judged_on,
            },
        },
    )


def cmd_run_judge(
    *,
    out_dir: Path,
    run_name: str,
    endpoint: JudgeEndpoint,
    budget_usd: float,
    stop_usd: float,
    sample_only: bool = False,
    seed: int = 0,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    include_unanswerable: bool = False,
    changeset_fraction: float = CHANGESET_FRACTION,
    concurrency: int = 4,
    table: PriceTable | None = None,
    client_factory: Callable[..., Any] = AsyncOpenAI,
    evidence_for: Callable[[GoldItem], EvidenceText] | None = None,
    clones_dir: Path | None = None,
    corpus_path: Path = CORPUS_PATH,
    clock: Callable[[], Any] | None = None,
) -> int:
    """Grade a run's selected generations and draw the blind sample to label.

    Args:
        out_dir: The eval output directory.
        run_name: The run to judge.
        endpoint: The judge.
        budget_usd: The spending cap; the run's generation spend counts against it.
        stop_usd: The spend at which judging stops cleanly.
        sample_only: Draw the labelling sample from existing judgments without calling a judge.
        seed: The seed of the change-set cluster draw and the labelling sample.
        sample_size: How many answers to put on the labelling sheet.
        include_unanswerable: Also grade the items marked unanswerable.
        changeset_fraction: The share of change-set clusters to grade; every one by default.
        concurrency: Pairs graded at once.
        table: The price table; the shipped one when omitted.
        client_factory: Builds the judge client; ``AsyncOpenAI`` by default.
        evidence_for: Gives an item's lookup from a citation key to its text; read from the
            clones and the pull request cache when omitted.
        clones_dir: Where the harness clones live; needed when ``evidence_for`` is omitted.
        corpus_path: The corpus file.
        clock: The wall clock, replaced in tests.

    Returns:
        The process exit status: 0 on success, 1 when something stopped it or any grade
        failed, 2 for a bad argument.
    """
    run_dir = run_dir_for(out_dir, run_name)
    generations = read_generations(run_dir / GENERATIONS)
    if not generations:
        print(f"no generations under {run_dir}", file=sys.stderr)
        return 1
    items = _load_items(out_dir, run_dir)
    if items is None:
        return 1
    try:
        budget = Budget(cap_usd=budget_usd, stop_usd=stop_usd)
    except ValueError as failure:
        print(str(failure), file=sys.stderr)
        return 2

    pairs = select_for_judging(
        items,
        generations,
        seed=seed,
        changeset_fraction=changeset_fraction,
        include_unanswerable=include_unanswerable,
    )
    path = judgments_path(run_dir, endpoint)
    prices = table or PriceTable.load(PRICES_PATH)
    status = 0
    reported: set[str] = set()

    if not sample_only:
        try:
            endpoint.require_key()
            prices.require_complete([endpoint.model])
        except (JudgeConfigError, PricesIncomplete) as failure:
            print(str(failure), file=sys.stderr)
            return 1
        if evidence_for is None:
            try:
                evidence_for = _real_evidence(out_dir, clones_dir, corpus_path, items)
            except (CorpusError, ValueError) as failure:
                print(str(failure), file=sys.stderr)
                return 1
        budget.restore(
            generations,
            read_routes(run_dir / ROUTES).values(),
            judgments=final_judgments(all_judgments(run_dir)),
        )
        kwargs: dict[str, Any] = {} if clock is None else {"clock": clock}
        result = asyncio.run(
            judge_all(
                pairs,
                endpoint=endpoint,
                out_path=path,
                budget=budget,
                table=prices,
                client_factory=client_factory,
                meter=Meter(),
                evidence_for=evidence_for,
                concurrency=concurrency,
                **kwargs,
            )
        )
        reported = result.reported_models
        _write_judge_manifest(
            run_dir,
            endpoint,
            prices,
            reported,
            (clock() if clock else datetime.now(UTC)).date().isoformat(),
        )
        print(
            f"{result.ok} metrics graded, {result.reused} reused, {result.errors} errors, "
            f"{result.skipped} already done; spent ${result.spent_usd:.4f} of ${budget.cap_usd:.2f}"
        )
        if result.stopped:
            print(f"stopped: {result.stopped}")
        if result.errors:
            print("some metrics failed; running the command again retries them")
        status = 1 if (result.errors or result.stopped) else 0
        print(f"judgments: {path}")

    sample = sample_for_labelling(
        grades_by_generation(read_judgments(path)), n=sample_size, seed=seed
    )
    lookup_for = evidence_for
    entries = build_sheet(
        sample,
        pairs,
        evidence_for=(lambda pair: lookup_for(pair.item)) if lookup_for is not None else None,
    )
    if entries or not sample_only:
        write_sheet(run_dir / SHEET_NAME, entries)
        print(f"labelling sheet: {run_dir / SHEET_NAME} ({len(entries)} answers)")
    else:
        print("no graded answers to sample; run `run judge` first", file=sys.stderr)
        status = 1
    return status


def _real_evidence(
    out_dir: Path, clones_dir: Path | None, corpus_path: Path, items: list[GoldItem]
) -> Callable[[GoldItem], EvidenceText]:
    if clones_dir is None:
        raise ValueError("reading the evidence needs a clones directory")
    corpus = load_corpus(corpus_path)
    repos = {}
    for name in sorted({item.repo for item in items}):
        entry = corpus.get(name)
        repos[name] = (entry.slug, entry.base_commit)
    return evidence_for_items(
        clones_dir=clones_dir, github_cache_dir=Path(out_dir) / "github", repos=repos
    )


def cmd_judge_label(
    *,
    out_dir: Path,
    run_name: str,
    annotator: str | None = None,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
) -> int:
    """Label the sampled answers, blind to the judge's scores.

    Args:
        out_dir: The eval output directory.
        run_name: The run whose sheet to label.
        annotator: Recorded with each label; labels go to ``judge_labels.<annotator>.jsonl``.
        input_fn: Reads a line.
        print_fn: Prints a block of text.

    Returns:
        The process exit status: 0 when the sheet is fully labelled, 1 otherwise.
    """
    run_dir = run_dir_for(out_dir, run_name)
    entries = read_sheet(run_dir / SHEET_NAME)
    if not entries:
        print(
            f"no labelling sheet at {run_dir / SHEET_NAME}; run `run judge` first", file=sys.stderr
        )
        return 1
    outcome = run_labelling(
        entries,
        path=labels_path(run_dir, annotator),
        annotator=annotator or "primary",
        input_fn=input_fn,
        print_fn=print_fn,
    )
    print_fn(f"{outcome.labelled} labelled, {outcome.remaining} remaining")
    return 1 if outcome.remaining else 0


def cmd_judge_agreement(
    *,
    out_dir: Path,
    run_name: str,
    endpoint: JudgeEndpoint,
    compare: JudgeEndpoint | None = None,
    annotator: str | None = None,
    resamples: int = 2000,
    seed: int = 0,
    minimum: int = MIN_LABELS,
    print_fn: Callable[[str], None] = print,
) -> int:
    """Report how well a judge agrees with the hand labels, or with a second judge.

    Args:
        out_dir: The eval output directory.
        run_name: The run.
        endpoint: The judge to report on.
        compare: A second judge; when given, the report is judge against judge.
        annotator: Whose labels to read.
        resamples: Bootstrap samples per interval.
        seed: The bootstrap seed.
        minimum: The fewest compared answers the report needs.
        print_fn: Prints a line.

    Returns:
        The process exit status: 0 on a report, 1 when there is nothing to compare.
    """
    run_dir = run_dir_for(out_dir, run_name)
    mine = read_judgments(judgments_path(run_dir, endpoint))
    if compare is not None:
        other = read_judgments(judgments_path(run_dir, compare))
        report = judge_vs_judge(mine, other, resamples=resamples, seed=seed, minimum=minimum)
        title = f"{endpoint.model}@{endpoint.host} against {compare.model}@{compare.host}"
    else:
        labels = read_labels(labels_path(run_dir, annotator))
        report = judge_vs_human(
            grades_by_generation(mine), labels, resamples=resamples, seed=seed, minimum=minimum
        )
        title = f"{endpoint.model}@{endpoint.host} against hand labels"
    if report.n == 0:
        print("nothing to compare: no answers graded and labelled by both", file=sys.stderr)
        return 1
    print_fn(format_agreement(report, title=title))
    flagged = sorted(report.exploratory_families)
    if flagged:
        print_fn(f"exploratory (kappa below 0.6 or too few): {', '.join(flagged)}")
    print_fn(f"the check labels {LABEL_SAMPLE_SIZE} answers across arms and question kinds")
    return 0


__all__ = [
    "DEFAULT_SAMPLE_SIZE",
    "cmd_judge_agreement",
    "cmd_judge_label",
    "cmd_run_judge",
    "judge_manifest_name",
]
