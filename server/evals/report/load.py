"""Reading a run directory: everything the report needs, from files alone.

A run directory holds ``generations.jsonl``, ``routes.jsonl``, one ``judgments.<judge>.jsonl`` per
judge, the hand labels of the judge, and the manifest. The generate command also captures the
run's context into it: ``gold.jsonl`` (the slice's items), ``gold_labels.jsonl`` (the hand
verdicts on the gold), ``corpus_counts.json``, ``files_at_base.json``, ``graph.json`` (the
import adjacency) and ``style.json`` (how the codebases differ). Where a context file is absent
the loader falls back to the output directory's own layout for the gold, and leaves anything else
empty; the report leaves the sections that need it out.

Library code here takes nothing from ``evals.settings``.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evals.corpus.style import read_style
from evals.gold.check import all_checks, final_checks
from evals.gold.schema import GoldItem, read_jsonl
from evals.gold.verify import Label
from evals.gold.verify import read_labels as read_gold_labels
from evals.manifest import MANIFEST_NAME
from evals.models import JUDGE_MODEL
from evals.run.endpoint import JudgeEndpoint
from evals.run.generate import GENERATIONS, ROUTES, final_records, read_generations, read_routes
from evals.run.judge import Grade, grades_by_generation, read_judgments
from evals.run.judge_validation import HumanLabel, read_labels
from evals.run.records import Generation, RouteRecord

GOLD_COPY = "gold.jsonl"
GOLD_LABELS_COPY = "gold_labels.jsonl"
CORPUS_COUNTS = "corpus_counts.json"
FILES_AT_BASE = "files_at_base.json"
GRAPH = "graph.json"
STYLE = "style.json"


class RunNotFound(FileNotFoundError):
    """The run directory has no generations to report on."""


@dataclass
class RunData:
    """Everything one report is built from.

    Attributes:
        run_dir: The run directory.
        name: The run's name (the directory's name).
        manifest: The run's manifest, or an empty mapping.
        judge_manifest: The chosen judge's manifest, when present.
        slice_name: The slice the run generated, from the manifest.
        items: The slice's gold items by id.
        generations: The final record per key, first repeat only.
        repeat_records: How many final records belong to later repeats.
        routes: The routing decisions by key.
        judge_slug: The judge whose judgments were loaded, or ``None``.
        judgments: That judge's per-generation grades, with the metrics that errored named.
        judge_labels: The hand labels of the judge's answers.
        gold_labels: The hand verdicts on the gold items.
        corpus: Counts per repository (and its language when recorded).
        files_at_base: Every file at the base commit, per repository.
        graph: The import adjacency per repository, file to the files it imports.
        style: How the codebases differ, per repository.
        deepeval_versions: The DeepEval releases the loaded judgments were produced under.
        checks: How the independent check of the explain answer keys came out: a count per
            verdict, plus ``errors``; empty when no check was recorded.
        notes: What was missing, for the report's own record.
    """

    run_dir: Path
    name: str
    manifest: dict[str, Any]
    judge_manifest: dict[str, Any] | None
    slice_name: str
    items: dict[str, GoldItem]
    generations: list[Generation]
    repeat_records: int
    routes: dict[str, RouteRecord]
    judge_slug: str | None
    judgments: list[Grade]
    judge_labels: list[HumanLabel]
    gold_labels: list[Label]
    corpus: dict[str, dict[str, Any]]
    files_at_base: dict[str, list[str]]
    graph: dict[str, dict[str, list[str]]]
    style: dict[str, dict[str, Any]] = field(default_factory=dict)
    deepeval_versions: list[str] = field(default_factory=list)
    checks: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def default_judge_slug() -> str:
    """The slug of the pinned default judge on the SDK's default endpoint."""
    return JudgeEndpoint(model=JUDGE_MODEL).slug


def choose_judge(run_dir: Path, requested: str | None) -> str | None:
    """Which judge's judgments file a report reads.

    The requested slug when one is given; otherwise the default judge's file when it exists, and
    otherwise the only judgments file there is. Judges are never mixed.

    Args:
        run_dir: The run directory.
        requested: ``--judge-slug``, if any.

    Returns:
        The slug, or ``None`` when no single judge can be chosen.

    Raises:
        FileNotFoundError: If a requested slug has no judgments file.
    """
    if requested:
        if not (run_dir / f"judgments.{requested}.jsonl").is_file():
            raise FileNotFoundError(f"no judgments for judge {requested!r} in {run_dir}")
        return requested
    default = default_judge_slug()
    if (run_dir / f"judgments.{default}.jsonl").is_file():
        return default
    found = sorted(run_dir.glob("judgments.*.jsonl"))
    if len(found) == 1:
        return found[0].name[len("judgments.") : -len(".jsonl")]
    return None


def _load_items(run_dir: Path, out_dir: Path, slice_name: str) -> dict[str, GoldItem]:
    for candidate in (run_dir / GOLD_COPY, out_dir / "gold" / f"{slice_name}.jsonl"):
        if candidate.is_file():
            return {item.id: item for item in read_jsonl(candidate)}
    return {}


def _load_gold_labels(run_dir: Path, out_dir: Path, repos: set[str]) -> list[Label]:
    copy = run_dir / GOLD_LABELS_COPY
    if copy.is_file():
        return read_gold_labels(copy)
    labels: dict[str, Label] = {}
    for repo in sorted(repos):
        directory = out_dir / "gold" / repo
        for path in sorted(directory.glob("labels*.jsonl")) if directory.is_dir() else []:
            for label in read_gold_labels(path):
                labels.setdefault(label.item_id, label)
    return list(labels.values())


def _load_judge_labels(run_dir: Path) -> list[HumanLabel]:
    direct = run_dir / "judge_labels.jsonl"
    if direct.is_file():
        return read_labels(direct)
    found = sorted(run_dir.glob("judge_labels.*.jsonl"))
    return read_labels(found[0]) if found else []


def _load_checks(out_dir: Path, repos: set[str]) -> dict[str, int]:
    """Verdict counts of the independent check, across the repositories' gold directories."""
    records = []
    for repo in sorted(repos):
        directory = out_dir / "gold" / repo
        if directory.is_dir():
            records.extend(all_checks(directory))
    final = final_checks(records)
    if not final:
        return {}
    counts = Counter(r.verdict for r in final if r.status == "ok")
    result = {
        name: counts.get(name, 0) for name in ("supported", "partly_supported", "unsupported")
    }
    result["errors"] = sum(1 for r in final if r.status == "error")
    return result


def load_run(
    run_dir: Path, *, out_dir: Path | None = None, judge_slug: str | None = None
) -> RunData:
    """Read a run directory.

    Args:
        run_dir: ``<out>/runs/<name>``.
        out_dir: The eval output directory, for the gold files when the run directory carries no
            copy; ``<run_dir>/../..`` when omitted.
        judge_slug: A judge to read instead of the default.

    Returns:
        The loaded data. Superseded records are dropped (the last record per key wins) and only
        the first repeat of each pair is kept.

    Raises:
        RunNotFound: If the run has no generations.
        FileNotFoundError: If ``judge_slug`` has no judgments file.
    """
    run_dir = Path(run_dir)
    out = Path(out_dir) if out_dir is not None else run_dir.parent.parent
    raw = read_generations(run_dir / GENERATIONS)
    if not raw:
        raise RunNotFound(f"no generations in {run_dir / GENERATIONS}")
    finals = final_records(raw)
    manifest = _json(run_dir / MANIFEST_NAME) or {}
    slice_name = str((manifest.get("run") or {}).get("slice") or "")
    items = _load_items(run_dir, out, slice_name)
    notes: list[str] = []
    if not items:
        notes.append("no gold items found")

    slug = choose_judge(run_dir, judge_slug)
    records = read_judgments(run_dir / f"judgments.{slug}.jsonl") if slug else []
    judgments = grades_by_generation(records)
    deepeval_versions = sorted({r.judge.deepeval_version for r in records})
    judge_manifest = _json(run_dir / f"manifest.judge.{slug}.json") if slug else None

    corpus = _json(run_dir / CORPUS_COUNTS) or {}
    files = _json(run_dir / FILES_AT_BASE) or {}
    graph = _json(run_dir / GRAPH) or {}
    for name, present in (("corpus counts", corpus), ("files at base", files), ("graph", graph)):
        if not present:
            notes.append(f"no {name} captured in the run directory")

    return RunData(
        run_dir=run_dir,
        name=run_dir.name,
        manifest=manifest,
        judge_manifest=judge_manifest,
        slice_name=slice_name,
        items=items,
        generations=[g for g in finals if g.repeat == 0],
        repeat_records=sum(1 for g in finals if g.repeat > 0),
        routes=read_routes(run_dir / ROUTES),
        judge_slug=slug,
        judgments=judgments,
        judge_labels=_load_judge_labels(run_dir),
        gold_labels=_load_gold_labels(run_dir, out, {i.repo for i in items.values()}),
        corpus=corpus,
        files_at_base=files,
        graph=graph,
        style=read_style(run_dir / STYLE),
        deepeval_versions=deepeval_versions,
        checks=_load_checks(out, {i.repo for i in items.values()}),
        notes=notes,
    )


__all__ = [
    "CORPUS_COUNTS",
    "FILES_AT_BASE",
    "GOLD_COPY",
    "GOLD_LABELS_COPY",
    "GRAPH",
    "STYLE",
    "RunData",
    "RunNotFound",
    "choose_judge",
    "default_judge_slug",
    "load_run",
]
