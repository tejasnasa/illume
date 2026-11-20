"""A synthetic run directory for the report tests: two repositories and every family of item.

The generator is deterministic. Each arm has a base chance of listing each gold file and a base
cost, so the arms differ in a known direction; the numbers are pseudo-random around those. Every
file the report reads is written the way the generate command and the judge write them.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from app.services.retrieval.citations import code_key
from evals.arms import AUTO, get_arm
from evals.gold.schema import GoldItem, make_item, write_jsonl
from evals.gold.verify import Label, append_label
from evals.manifest import write_manifest
from evals.models import GENERATOR_MODEL, JUDGE_MODEL
from evals.report.load import (
    CORPUS_COUNTS,
    FILES_AT_BASE,
    GOLD_COPY,
    GOLD_LABELS_COPY,
    GRAPH,
    default_judge_slug,
)
from evals.run.generate import GENERATIONS, ROUTES
from evals.run.judge_validation import HumanLabel
from evals.run.judge_validation import append_label as append_judge_label
from evals.run.records import (
    CandidateRecord,
    Generation,
    JudgeVersion,
    Judgment,
    RouteRecord,
    RunTokens,
    StepRecordOut,
    Usage,
    composed_record_key,
    judgment_key,
)

PILOT_ARMS = (
    "classic",
    "hybrid",
    "hybrid_rerank",
    "hybrid_hyde",
    "hybrid_multiquery",
    "structural",
    "structural_-cochange",
    "structural_rerank",
    "agent",
    AUTO,
)
FULL_ARMS = (
    "classic",
    "hybrid",
    "hybrid_rerank",
    "hybrid_jev",
    "hybrid_hyde",
    "hybrid_multiquery",
    "structural",
    "structural_-graph",
    "structural_-cochange",
    "structural_-history",
    "structural_-grep",
    "structural_rerank",
    "agent",
    "agent_text_tools",
    "agent_workers",
    AUTO,
)
REPOS = {"repo-py": "Python", "repo-ts": "TypeScript"}

RECALL = {
    "classic": 0.30,
    "hybrid": 0.42,
    "hybrid_rerank": 0.50,
    "hybrid_jev": 0.49,
    "hybrid_hyde": 0.44,
    "hybrid_multiquery": 0.45,
    "structural": 0.60,
    "structural_-graph": 0.55,
    "structural_-cochange": 0.48,
    "structural_-history": 0.56,
    "structural_-grep": 0.54,
    "structural_rerank": 0.66,
    "agent": 0.80,
    "agent_text_tools": 0.70,
    "agent_workers": 0.79,
}
COST = {
    "classic": 0.0004,
    "hybrid": 0.0006,
    "hybrid_rerank": 0.0007,
    "hybrid_jev": 0.0007,
    "hybrid_hyde": 0.0012,
    "hybrid_multiquery": 0.0013,
    "structural": 0.0008,
    "structural_-graph": 0.0008,
    "structural_-cochange": 0.0008,
    "structural_-history": 0.0008,
    "structural_-grep": 0.0008,
    "structural_rerank": 0.0009,
    "agent": 0.011,
    "agent_text_tools": 0.009,
    "agent_workers": 0.014,
}
FILE_POOL = 30
RUN_NAME = "synthetic"
JUDGED_ON = "2026-11-01"


def _digest(*parts: object) -> str:
    return hashlib.sha256(":".join(str(p) for p in parts).encode()).hexdigest()[:16]


def _files(repo: str) -> list[str]:
    ext = "py" if REPOS[repo] == "Python" else "ts"
    pool = [f"src/{repo}/mod{n}.{ext}" for n in range(FILE_POOL)]
    return pool + [f"tests/{repo}/test_mod{n}.{ext}" for n in range(0, FILE_POOL, 5)]


def make_items(
    n_prs: int, n_rationale: int, n_hand: int, n_structural: int, rng: random.Random
) -> list[GoldItem]:
    """Change-set items (anchor and blind per pull request) and the other families."""
    items: list[GoldItem] = []
    for pr in range(n_prs):
        repo = list(REPOS)[pr % 2]
        files = _files(repo)
        gold = sorted(rng.sample(files, rng.randint(2, 6)))
        for template in ("anchor", "blind"):
            fields: dict[str, Any] = {
                "repo": repo,
                "base_commit": "a" * 40,
                "family": "changeset",
                "template": f"changeset.{template}",
                "question": f"What changes for pull request {pr} ({template})?",
                "question_seed": f"seed pr {pr}",
                "gold_files": tuple(gold),
                "gold_test_files": tuple(g for g in gold if g.startswith("tests/")),
                "gold_prs": (pr,),
                "post_cutoff": pr % 4 == 0,
                "merges_since_base": (pr * 7) % 100,
                "cluster": f"{repo}#{pr}",
            }
            if template == "anchor":
                extra = next(f for f in files if f not in gold)
                fields["anchor_file"] = extra
            items.append(make_item(**fields))
    for family, count, circular in (
        ("rationale", n_rationale, ("history",)),
        ("hand", n_hand, ()),
        ("structural", n_structural, ("graph",)),
    ):
        for n in range(count):
            repo = list(REPOS)[n % 2]
            files = _files(repo)
            items.append(
                make_item(
                    repo=repo,
                    base_commit="a" * 40,
                    family=family,
                    template=f"{family}.t",
                    question=f"A {family} question number {n}?",
                    question_seed=f"{family} {n}",
                    gold_files=tuple(sorted(rng.sample(files, 2))),
                    gold_answer_notes=(f"A fact about {family} {n}.",),
                    circular_with=circular,
                )
            )
    return items


def _answer(item: GoldItem, arm: str, rng: random.Random, files: list[str]) -> str:
    if rng.random() < 0.03:
        return "I could not work out which files change."
    base = RECALL.get(arm, 0.5)
    listed = [g for g in item.gold_files if g != item.anchor_file and rng.random() < base]
    listed += rng.sample(files, rng.randint(0, 2))
    if item.anchor_file and rng.random() < 0.5:
        listed.append(item.anchor_file)
    bullets = "\n".join(f"- {path}" for path in dict.fromkeys(listed))
    return f"The change touches these areas.\n\nFiles:\n{bullets}\n"


def _steps(
    item: GoldItem, rng: random.Random, files: list[str], workers: bool
) -> list[StepRecordOut]:
    seed_files = rng.sample(files, 2)
    steps = [
        StepRecordOut(
            index=0, kind="seed", node="seed", evidence_keys=[code_key(f) for f in seed_files]
        )
    ]
    reach_at = rng.randint(1, 8) if rng.random() < 0.85 else None
    for index in range(1, rng.randint(4, 10)):
        target = item.gold_files[0] if reach_at == index and item.gold_files else rng.choice(files)
        steps.append(
            StepRecordOut(
                index=index,
                kind="tool_call",
                node="tools",
                tool="read_file" if index % 2 else "search_code",
                arguments=json.dumps({"path": target}) if index % 2 else None,
                evidence_keys=[] if index % 2 else [code_key(target)],
                worker_id=f"w{index % 2}" if workers else None,
            )
        )
    return steps


def _usages(arm: str, rng: random.Random) -> tuple[list[Usage], float]:
    cost = COST.get(arm, 0.001) * rng.uniform(0.7, 1.3)
    kind = "agent" if arm.startswith("agent") else "generate"
    usage = Usage(
        provider="deepseek",
        model=GENERATOR_MODEL,
        kind=kind,
        input_tokens=int(cost * 1_000_000),
        output_tokens=int(cost * 100_000),
        latency_ms=rng.uniform(800, 4000) * (6 if arm.startswith("agent") else 1),
    )
    return [usage], cost


def _generation(
    item: GoldItem, arm: str, rng: random.Random, files: list[str], *, error: bool
) -> Generation:
    config = get_arm(arm)
    usages, cost = _usages(arm, rng)
    common: dict[str, Any] = {
        "record_key": _digest("gen", item.id, arm),
        "item_id": item.id,
        "arm": arm,
        "config_hash": config.config_hash(),
        "model": config.model,
        "usages": usages,
        "cost_usd": cost,
        "latency_ms": usages[0].latency_ms,
    }
    if error:
        return Generation(status="error", error="provider unavailable", **common)
    answer = _answer(item, arm, rng, files)
    if config.is_agent:
        return Generation(
            answer=answer,
            steps=_steps(item, rng, files, workers=arm == "agent_workers"),
            stop_reason="finished",
            run_tokens=RunTokens(input_tokens=usages[0].input_tokens),
            **common,
        )
    ranked = list(item.gold_files[: int(len(item.gold_files) * RECALL.get(arm, 0.5)) + 1])
    ranked += rng.sample(files, 8)
    pool = [
        CandidateRecord(key=code_key(path), rank=rank, source_type="file", file_path=path)
        for rank, path in enumerate(dict.fromkeys(ranked), start=1)
    ]
    return Generation(answer=answer, candidates=pool[:10], pool=pool, **common)


def build_synthetic_run(
    root: Path,
    *,
    arms: tuple[str, ...] = PILOT_ARMS,
    n_prs: int = 38,
    n_rationale: int = 15,
    n_hand: int = 10,
    n_structural: int = 6,
    seed: int = 0,
    error_arm: str | None = "hybrid_hyde",
    with_judge: bool = True,
    n_labels: int = 45,
) -> Path:
    """Write a complete synthetic run and return its directory.

    Args:
        root: The output directory; the run goes in ``root / "runs" / "synthetic"``.
        arms: The arms to generate; ``auto`` is composed from the arms it routes to.
        n_prs: Pull requests (each gives an anchor and a blind item).
        n_rationale: Rationale items.
        n_hand: Hand-written items.
        n_structural: Structural items.
        seed: The seed of every random choice.
        error_arm: An arm that fails on a few items, to exercise the exclusions.
        with_judge: Write judgments, hand labels of the judge and gold verdicts.
        n_labels: How many judged answers get a hand label.

    Returns:
        The run directory.
    """
    rng = random.Random(seed)
    run_dir = root / "runs" / RUN_NAME
    run_dir.mkdir(parents=True, exist_ok=True)
    items = make_items(n_prs, n_rationale, n_hand, n_structural, rng)
    write_jsonl(run_dir / GOLD_COPY, items)
    files = {repo: _files(repo) for repo in REPOS}

    generations: dict[tuple[str, str], Generation] = {}
    for arm in arms:
        if arm == AUTO:
            continue
        for item in items:
            failing = arm == error_arm and rng.random() < 0.08
            generations[(item.id, arm)] = _generation(
                item, arm, rng, files[item.repo], error=failing
            )

    routes: list[RouteRecord] = []
    if AUTO in arms:
        for item in items:
            fallback = rng.random() < 0.05
            route = rng.choice(["local", "relational", "history"])
            target = (
                "structural_rerank"
                if fallback
                else {
                    "local": "hybrid_rerank",
                    "relational": "structural_rerank",
                    "history": "agent",
                }[route]
            )
            source = generations.get((item.id, target))
            if source is None or source.status != "ok":
                continue
            decision = RouteRecord(
                item_id=item.id,
                route=None if fallback else route,
                confidence=None if fallback else 0.9,
                resolved_preset=target,
                target_arm=target,
                fallback_reason="timeout" if fallback else None,
                cost_usd=0.00004,
            )
            routes.append(decision)
            generations[(item.id, AUTO)] = source.model_copy(
                update={
                    "record_key": composed_record_key(source.record_key, decision),
                    "arm": AUTO,
                    "composed_from": target,
                    "route": decision,
                    "cost_usd": (source.cost_usd or 0.0) + 0.00004,
                }
            )

    with (run_dir / GENERATIONS).open("w", encoding="utf-8") as handle:
        for generation in generations.values():
            handle.write(generation.model_dump_json() + "\n")
    with (run_dir / ROUTES).open("w", encoding="utf-8") as handle:
        for decision in routes:
            handle.write(
                json.dumps(
                    {
                        "key": _digest("route", decision.item_id),
                        "route": decision.model_dump(mode="json"),
                    }
                )
                + "\n"
            )

    counts = {
        repo: {
            "files": len(files[repo]),
            "symbols": 10 * len(files[repo]),
            "edges": 2 * len(files[repo]),
            "commits": 120,
            "prs": 80,
            "cochange_pairs": 40,
            "embeddings": {"symbol": 100},
            "language": language,
        }
        for repo, language in REPOS.items()
    }
    (run_dir / CORPUS_COUNTS).write_text(json.dumps(counts), encoding="utf-8")
    (run_dir / FILES_AT_BASE).write_text(json.dumps(files), encoding="utf-8")
    graph = {
        repo: {
            path: [paths[(n + 1) % len(paths)], paths[(n + 3) % len(paths)]]
            for n, path in enumerate(paths)
        }
        for repo, paths in files.items()
    }
    (run_dir / GRAPH).write_text(json.dumps(graph), encoding="utf-8")

    write_manifest(
        run_dir,
        arms={a: get_arm(a).config_hash() for a in arms},
        prompt_version="synthetic",
        models={"generator": GENERATOR_MODEL, "judge": JUDGE_MODEL},
        reported_snapshots={},
        price_table_version="synthetic",
        agent_token_cap=300_000,
        corpus_pins={repo: "a" * 40 for repo in REPOS},
        split_hash="synthetic",
        eval_instruction="Files:",
        git={"sha": "0" * 40, "dirty": False},
        uv_lock_sha256="0" * 64,
        extra={"kind": "generate", "slice": "pilot"},
    )

    if with_judge:
        _write_judging(run_dir, items, generations, rng, n_labels)
    return run_dir


def _write_judging(
    run_dir: Path,
    items: list[GoldItem],
    generations: dict[tuple[str, str], Generation],
    rng: random.Random,
    n_labels: int,
) -> None:
    version = JudgeVersion(
        prompt_version="1", model=JUDGE_MODEL, host="openai", judged_on=JUDGED_ON
    )
    by_id = {i.id: i for i in items}
    judgments: list[Judgment] = []
    for (item_id, arm), generation in sorted(generations.items()):
        item = by_id[item_id]
        if generation.status != "ok":
            continue
        if item.family == "changeset" and rng.random() > 0.2:
            continue
        skill = RECALL.get(arm, 0.5)
        correct = min(3, max(0, round(skill * 3 + rng.uniform(-1, 1))))
        judgments.append(
            Judgment(
                judgment_key=judgment_key(
                    generation_key=generation.record_key,
                    prompt_version="1",
                    model=JUDGE_MODEL,
                    host="openai",
                ),
                generation_key=generation.record_key,
                item_id=item_id,
                family=item.family,
                arm=arm,
                judge=version,
                correct=correct,
                faithful=min(3, max(0, correct + rng.choice([-1, 0, 0, 1]))),
                abstained=rng.random() < 0.05,
                rationale="synthetic",
                cost_usd=0.0001,
            )
        )
    path = run_dir / f"judgments.{default_judge_slug()}.jsonl"
    path.write_text("".join(j.model_dump_json() + "\n" for j in judgments), encoding="utf-8")

    labelled = rng.sample(judgments, min(n_labels, len(judgments)))
    labels_file = run_dir / "judge_labels.jsonl"
    for judgment in labelled:
        assert judgment.correct is not None and judgment.faithful is not None
        append_judge_label(
            labels_file,
            HumanLabel(
                generation_key=judgment.generation_key,
                item_id=judgment.item_id,
                family=judgment.family,
                correct=min(3, max(0, judgment.correct + rng.choice([-1, 0, 0, 0, 1]))),
                faithful=min(3, max(0, judgment.faithful + rng.choice([-1, 0, 0, 0, 1]))),
            ),
        )

    gold_labels = run_dir / GOLD_LABELS_COPY
    for index, item in enumerate(sorted(items, key=lambda i: i.id)):
        verdict = "wrong" if index % 11 == 3 else "ambiguous" if index == 5 else "correct"
        append_label(gold_labels, Label(item_id=item.id, label=verdict))  # type: ignore[arg-type]
