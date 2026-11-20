"""Hand-computed checks of every metric and its edge cases.

Importing this module registers the cases with :mod:`evals.selftest_registry`; the report and
``python -m evals selftest`` run them. Each expected value is worked out by hand in the case, so
a failure means the arithmetic changed, not that two copies of the same code agree. Nothing here
touches a database or the network.
"""

from __future__ import annotations

import math
from typing import Any

from evals.gold.schema import GoldItem, make_item
from evals.metrics.answer import answer_file_scores
from evals.metrics.citations import citation_scores
from evals.metrics.cost import (
    correct_count,
    cost_summary,
    dollars_per_correct,
    percentile,
)
from evals.metrics.files_list import parse_files_list
from evals.metrics.retrieval import (
    Ranking,
    first_touch_files,
    mrr,
    ndcg_at_k,
    ranked_files,
    recall_at_k,
    retrieval_scores,
)
from evals.metrics.routing import ArmOutcome, best_arm, routing_summary
from evals.metrics.trajectory import (
    gold_never_reached,
    shortest_path_nodes,
    steps_to_first_gold,
    stop_reasons,
    tool_call_counts,
    wasted_reads,
    worker_overlap,
)
from evals.run.records import (
    CandidateRecord,
    Generation,
    RouteRecord,
    StepRecordOut,
    Usage,
)
from evals.selftest_registry import register

BASE = "b" * 40
TOLERANCE = 1e-9


def _same(actual: float | None, expected: float | None, label: str = "") -> None:
    if actual is None or expected is None:
        assert actual is expected, f"{label}: expected {expected}, got {actual}"
        return
    assert math.isclose(actual, expected, abs_tol=TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def _item(gold: tuple[str, ...] = ("a.py", "b.py"), **fields: Any) -> GoldItem:
    base: dict[str, Any] = {
        "repo": "r",
        "base_commit": BASE,
        "family": "hand",
        "template": "hand.flow",
        "question": "q",
        "question_seed": "q",
        "gold_files": gold,
    }
    base.update(fields)
    return make_item(**base)


def _gen(answer: str = "", **fields: Any) -> Generation:
    base: dict[str, Any] = {
        "record_key": "k",
        "item_id": "i",
        "arm": "x",
        "config_hash": "h",
        "model": "m",
        "answer": answer,
    }
    base.update(fields)
    return Generation(**base)


def _cand(key: str, rank: int, file_path: str | None = None) -> CandidateRecord:
    return CandidateRecord(key=key, rank=rank, source_type="symbol", file_path=file_path)


def _step(index: int, kind: str = "tool_call", **fields: Any) -> StepRecordOut:
    return StepRecordOut(index=index, kind=kind, node="n", **fields)


def _read(index: int, path: str, worker: str | None = None) -> StepRecordOut:
    return _step(
        index,
        tool="read_file",
        arguments=f'{{"path": "{path}"}}',
        evidence_keys=[f"F:{path}:1-9"],
        worker_id=worker,
    )


AT_BASE = {"a.py", "b.py", "c.py", "d.py", "x.py", "tests/test_a.py", "z.py"}


@register("files list: bullets, backticks and numbering")
def _bullets() -> None:
    parsed = parse_files_list("Done.\n\nFiles:\n- `a.py`\n* b/c.py\n1. d.py\n2) e.py")
    assert parsed.found and parsed.paths == ("a.py", "b/c.py", "d.py", "e.py"), parsed


@register("files list: ranges, anchors, links, Windows separators and ./")
def _decorations() -> None:
    text = (
        "**Files:**\n- a.py:10-20\n- b.py#L3-L9\n- [c.py](c.py)\n"
        "- d\\e.py (lines 3–9)\n- ./f.py\n- `g.py` - the entry point"
    )
    assert parse_files_list(text).paths == ("a.py", "b.py", "c.py", "d/e.py", "f.py", "g.py")


@register("files list: comma list on the heading line, last block wins")
def _last_block() -> None:
    text = "Files: x.py\n\nOn reflection:\n\nfiles: a.py, b.py, c.py:4-5"
    assert parse_files_list(text).paths == ("a.py", "b.py", "c.py")


@register("files list: a missing heading is a format failure, an empty one is not")
def _missing() -> None:
    assert parse_files_list("I changed a.py and b.py.") == parse_files_list("")
    assert parse_files_list("no list").found is False
    empty = parse_files_list("Files: none")
    assert empty.found and empty.paths == ()


@register("answer: recall 2/4 and precision 2/3")
def _basic() -> None:
    item = _item(("a.py", "b.py", "c.py", "d.py"))
    scores = answer_file_scores(item, _gen("Files:\n- a.py\n- b.py\n- x.py"), AT_BASE)
    _same(scores.recall, 0.5, "recall")
    _same(scores.precision, 2 / 3, "precision")
    assert (scores.tp, scores.listed, scores.gold_n) == (2, 3, 4)
    assert not scores.format_failure and scores.nonexistent_listed == 0


@register("answer: a listed path absent at the base counts against precision")
def _nonexistent() -> None:
    scores = answer_file_scores(_item(), _gen("Files: a.py, ghost.py"), AT_BASE)
    _same(scores.recall, 0.5, "recall")
    _same(scores.precision, 0.5, "precision")
    assert scores.nonexistent_listed == 1


@register("answer: the anchor is never scored")
def _anchor() -> None:
    item = _item(
        ("a.py", "b.py"),
        template="changeset.anchor",
        anchor_file="z.py",
        family="changeset",
        cluster="r#1",
        merges_since_base=0,
    )
    scores = answer_file_scores(item, _gen("Files: z.py, a.py"), AT_BASE)
    _same(scores.recall, 0.5, "recall")
    _same(scores.precision, 1.0, "precision")
    assert scores.listed == 1 and scores.gold_n == 2


@register("answer: test files drop from both sides when excluded")
def _tests() -> None:
    item = _item(("a.py", "tests/test_a.py"), gold_test_files=("tests/test_a.py",))
    text = "Files: a.py, tests/test_a.py, tests/test_other.py"
    with_tests = answer_file_scores(item, _gen(text), AT_BASE)
    _same(with_tests.recall, 1.0, "recall with tests")
    _same(with_tests.precision, 2 / 3, "precision with tests")
    without = answer_file_scores(item, _gen(text), AT_BASE, include_tests=False)
    _same(without.recall, 1.0, "recall without tests")
    _same(without.precision, 1.0, "precision without tests")
    assert without.gold_n == 1 and without.listed == 1


@register("answer: acceptable files are neither hits nor misses")
def _acceptable() -> None:
    item = _item(("a.py",), acceptable_files=("b.py",))
    scores = answer_file_scores(item, _gen("Files: a.py, b.py, c.py"), AT_BASE)
    _same(scores.recall, 1.0, "recall")
    _same(scores.precision, 0.5, "precision")


@register("answer: empty gold has no recall; no list is recall 0 and a format failure")
def _empty_and_format() -> None:
    unanswerable = answer_file_scores(_item(()), _gen("Files: a.py"), AT_BASE)
    assert unanswerable.recall is None and unanswerable.precision is None
    missing = answer_file_scores(_item(), _gen("no list here"), AT_BASE)
    _same(missing.recall, 0.0, "recall")
    assert missing.precision is None and missing.format_failure
    assert answer_file_scores(_item(()), _gen("nothing"), AT_BASE).recall is None


@register("answer: an error generation is never scored")
def _error_generation() -> None:
    try:
        answer_file_scores(_item(), _gen(status="error", error="boom"), AT_BASE)
    except ValueError:
        return
    raise AssertionError("an error generation was scored")


@register("retrieval: ties keep list order, duplicates keep the best, odd keys are counted")
def _ranking() -> None:
    ranking = ranked_files(
        [
            _cand("F:b.py", 2),
            _cand("F:a.py:1-5", 1),
            _cand("F:a.py:10-20", 2),
            _cand("C:abcd1234", 3),
            _cand("garbage", 4),
            _cand("PR:7", 5, file_path="c.py"),
        ]
    )
    assert ranking == Ranking(files=("a.py", "b.py", "c.py"), unmapped=1, malformed=1), ranking


@register("retrieval: recall at k, hand-computed")
def _recall() -> None:
    files = ["x.py", "a.py", "y.py", "b.py", "z.py"]
    gold = {"a.py", "b.py", "c.py"}
    _same(recall_at_k(files, gold, 2), 1 / 3, "k=2")
    _same(recall_at_k(files, gold, 5), 2 / 3, "k=5")
    _same(recall_at_k(files, gold, 20), 2 / 3, "k beyond the list")
    _same(recall_at_k(files, set(), 5), None, "empty gold")


@register("retrieval: reciprocal rank")
def _mrr() -> None:
    _same(mrr(["x.py", "a.py"], {"a.py"}), 0.5, "second place")
    _same(mrr(["x.py"], {"a.py"}), 0.0, "absent")
    _same(mrr(["x.py"], set()), None, "empty gold")


@register("retrieval: nDCG, perfect ranking is 1 and a late hit is discounted")
def _ndcg() -> None:
    _same(ndcg_at_k(["a.py", "b.py", "x.py"], {"a.py", "b.py"}, 5), 1.0, "perfect")
    _same(ndcg_at_k(["x.py", "a.py"], {"a.py"}, 5), 1 / math.log2(3), "rank 2, one gold")
    _same(ndcg_at_k(["a.py", "b.py"], {"a.py", "b.py", "c.py"}, 2), 1.0, "ideal over min(k, gold)")
    # gold at ranks 1 and 3 of two: dcg 1 + 1/2, ideal 1 + 1/log2(3)
    expected = 1.5 / (1 + 1 / math.log2(3))
    _same(ndcg_at_k(["a.py", "x.py", "b.py"], {"a.py", "b.py"}, 3), expected, "split")
    scores = retrieval_scores(Ranking(("a.py",)), {"a.py"})
    assert set(scores.recall) == {5, 10, 20} and scores.mrr == 1.0


@register("retrieval: first-touch order over evidence keys and read paths")
def _first_touch() -> None:
    steps = [
        _step(0, "seed", evidence_keys=["F:a.py:1-2", "C:abcd1234"]),
        _step(1, evidence_keys=["F:d.py:1-5", "F:a.py:9-12"]),
        _read(2, "b/c.py"),
    ]
    assert first_touch_files(steps) == ["a.py", "d.py", "b/c.py"]
    assert first_touch_files([]) == []


@register("citations: unresolved and missing-at-base rates")
def _citations() -> None:
    generation = _gen(
        "See [F:a.py:1-5], [F:z.py] and [C:deadbeef]; again [F:a.py:1-5].",
        candidates=[_cand("F:a.py:3-8", 1)],
    )
    scores = citation_scores(generation, {"a.py"})
    assert (scores.cited, scores.unresolved, scores.missing_at_base) == (3, 2, 1)
    _same(scores.unresolved_rate, 2 / 3, "unresolved")
    _same(scores.missing_rate, 0.5, "missing")
    assert citation_scores(_gen("no keys"), {"a.py"}).unresolved_rate is None


@register("trajectory: steps to the first gold file and gold never reached")
def _steps_to_gold() -> None:
    steps = [
        _step(0, "seed", evidence_keys=["F:a.py:1-2"]),
        _step(1, tool="search_code", evidence_keys=["F:b.py:1-2"]),
        _read(2, "c.py"),
    ]
    assert steps_to_first_gold(steps, {"c.py", "d.py"}) == 2
    assert steps_to_first_gold(steps, {"a.py"}) == 0
    assert steps_to_first_gold(steps, {"d.py"}) is None
    assert gold_never_reached(steps, {"d.py"}) and not gold_never_reached(steps, {"b.py"})
    assert not gold_never_reached(steps, set())


@register("trajectory: wasted reads on a toy import graph")
def _wasted() -> None:
    adjacency = {
        "seed.py": ["mid.py", "side.py"],
        "mid.py": ["gold.py"],
        "gold.py": ["seed2.py"],
        "hub.py": ["seed2.py"],
    }
    steps = [
        _step(0, "seed", evidence_keys=["F:seed.py:1-9"]),
        _read(1, "mid.py"),
        _read(2, "side.py"),
        _read(3, "gold.py"),
        _read(4, "other.py"),
        _read(5, "mid.py"),
    ]
    result = wasted_reads(steps, {"gold.py"}, adjacency)
    assert result.reads == 4 and result.wasted_files == ("side.py", "other.py")
    _same(result.rate, 0.5, "rate")
    assert wasted_reads([], {"gold.py"}, adjacency).rate is None
    assert wasted_reads(steps, set(), adjacency).rate is None


@register("trajectory: shortest chains follow the product's find_path rule")
def _chains() -> None:
    diamond = {"a.py": ["b.py", "c.py"], "b.py": ["d.py"], "c.py": ["d.py"]}
    assert shortest_path_nodes(diamond, "a.py", "d.py") == {"a.py", "b.py", "c.py", "d.py"}
    assert shortest_path_nodes(diamond, "d.py", "a.py") == {"a.py", "b.py", "c.py", "d.py"}
    shorter_back = {"s.py": ["x.py"], "x.py": ["y.py"], "y.py": ["t.py"], "t.py": ["s.py"]}
    assert shortest_path_nodes(shorter_back, "s.py", "t.py") == {"s.py", "t.py"}
    assert shortest_path_nodes(shorter_back, "t.py", "s.py") == {"t.py", "s.py"}
    assert shortest_path_nodes(diamond, "a.py", "nowhere.py") == set()
    assert shortest_path_nodes(diamond, "a.py", "d.py", max_depth=1) == set()


@register("trajectory: tool counts, stop reasons and worker overlap")
def _tools_and_workers() -> None:
    steps = [
        _step(0, "seed"),
        _step(1, tool="search_code"),
        _step(2, tool="search_code"),
        _read(3, "a.py", worker="w1"),
        _read(4, "b.py", worker="w1"),
        _read(5, "b.py", worker="w2"),
        _read(6, "c.py", worker="w2"),
    ]
    counts = tool_call_counts(steps)
    assert counts["search_code"] == 2 and counts["read_file"] == 4
    reasons = stop_reasons(
        [_gen(steps=[_step(0)], stop_reason="finish"), _gen(steps=[_step(0)]), _gen()]
    )
    assert dict(reasons) == {"finish": 1, "unknown": 1}
    overlap = worker_overlap(steps)
    assert overlap.workers == 2 and overlap.shared_files == 1
    _same(overlap.mean_jaccard, 1 / 3, "jaccard")
    assert worker_overlap([_read(0, "a.py", worker="w1")]).mean_jaccard is None


@register("cost: percentiles, per-question dollars, tokens and dollars per correct")
def _cost() -> None:
    _same(percentile([100, 200, 300, 400, 1000], 50), 300, "p50")
    _same(percentile([100, 200, 300, 400, 1000], 95), 880, "p95")
    _same(percentile([7], 95), 7, "single value")
    assert percentile([], 50) is None
    usage = Usage(
        provider="p",
        model="m",
        kind="generate",
        input_tokens=100,
        cached_input_tokens=40,
        output_tokens=10,
    )
    one = _gen(cost_usd=0.10, latency_ms=100, usages=[usage])
    two = _gen(cost_usd=0.20, latency_ms=300, usages=[usage, usage])
    summary = cost_summary([one, two])
    _same(summary.per_question_usd, 0.15, "per question")
    assert (summary.tokens.input, summary.tokens.cached, summary.tokens.output) == (300, 120, 30)
    _same(summary.latency_p50_ms, 200, "p50 latency")
    assert cost_summary([]).per_question_usd is None
    scores = [
        answer_file_scores(_item(("a.py", "b.py")), _gen("Files: a.py, b.py"), AT_BASE),
        answer_file_scores(_item(("a.py", "b.py")), _gen("Files: a.py"), AT_BASE),
        None,
    ]
    assert correct_count(scores) == 1 and correct_count(scores, 0.5) == 2
    _same(dollars_per_correct(0.30, scores), 0.30, "per correct")
    assert dollars_per_correct(0.30, scores[1:]) is None


@register("routing: distribution, fallbacks, comparison and confusion")
def _routing() -> None:
    def auto(item: str, arm: str, route: str | None, reason: str | None = None) -> Generation:
        record = RouteRecord(
            item_id=item, route=route, resolved_preset="p", target_arm=arm, fallback_reason=reason
        )
        return _gen(item_id=item, arm="auto", route=record, composed_from=arm)

    records = [
        auto("i1", "agent", "deep"),
        auto("i2", "agent", "deep"),
        auto("i3", "structural_rerank", None, "decision_failed"),
    ]
    outcomes = {
        "agent": {
            "i1": ArmOutcome(1.0, 1.0),
            "i2": ArmOutcome(1.0, 1.0),
            "i3": ArmOutcome(0.5, 1.0),
        },
        "structural_rerank": {
            "i1": ArmOutcome(1.0, 0.1),
            "i2": ArmOutcome(0.5, 0.1),
            "i3": ArmOutcome(0.5, 0.1),
        },
        "auto": {
            "i1": ArmOutcome(1.0, 1.0),
            "i2": ArmOutcome(1.0, 1.0),
            "i3": ArmOutcome(0.5, 0.1),
        },
    }
    assert best_arm("i1", outcomes) == "structural_rerank"  # tie on recall, cheaper wins
    assert best_arm("i2", outcomes) == "agent"
    assert best_arm("missing", outcomes) is None
    summary = routing_summary(records, outcomes)
    assert dict(summary.route_distribution) == {"deep": 2, "none": 1}
    assert dict(summary.fallbacks) == {"decision_failed": 1} and summary.fallback_count == 1
    assert summary.confusion == {
        ("agent", "structural_rerank"): 1,
        ("agent", "agent"): 1,
        ("structural_rerank", "structural_rerank"): 1,
    }
    _same(summary.agreement, 2 / 3, "agreement")
    by_arm = {row.arm: row for row in summary.comparison}
    _same(by_arm["auto"].mean_recall, 2.5 / 3, "auto recall")
    _same(by_arm["agent"].mean_cost_usd, 1.0, "agent cost")
    assert all(row.n == 3 for row in summary.comparison)


@register("structural items: metrics agree with the graph they were built from")
def _structural() -> None:
    adjacency = {"app.py": ["svc.py"], "svc.py": ["db.py"], "cli.py": ["svc.py"]}
    path_item = make_item(
        repo="r",
        base_commit=BASE,
        family="structural",
        template="structural.path",
        question_seed="q",
        gold_files=("app.py", "svc.py", "db.py"),
        circular_with=("graph",),
    )
    on_chain = shortest_path_nodes(adjacency, "app.py", "db.py")
    assert on_chain == set(path_item.gold_files)
    importers = make_item(
        repo="r",
        base_commit=BASE,
        family="structural",
        template="structural.importers",
        question_seed="q",
        gold_files=("app.py", "cli.py"),
        circular_with=("graph",),
    )
    reverse = {"svc.py": {"app.py", "cli.py"}}
    assert set(importers.gold_files) == reverse["svc.py"]
    full = answer_file_scores(
        importers, _gen("Files:\n- app.py\n- cli.py"), {"app.py", "cli.py", "svc.py", "db.py"}
    )
    _same(full.recall, 1.0, "recall")
    _same(full.precision, 1.0, "precision")
    ranking = Ranking(("app.py", "cli.py", "svc.py"))
    scores = retrieval_scores(ranking, set(importers.gold_files))
    _same(scores.ndcg[5], 1.0, "ndcg")
    _same(scores.mrr, 1.0, "mrr")
