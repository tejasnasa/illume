"""The report: wording, comparisons, limitations and the two modes, on a synthetic run."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

import evals.report.comparisons as comparisons_module
from evals import selftest_registry
from evals.report import ReportError, build_report
from evals.report.comparisons import (
    FULL_COMPARISONS,
    PILOT_COMPARISONS,
    SIMPLE_COMPARISONS,
    ItemRef,
    StatConfig,
    run_comparisons,
)
from evals.report.limitations import build_limitations
from evals.report.ratio import RatioObs, ratio_bootstrap
from evals.report.wording import check_wording, comparison_sentence
from tests.evals.synthetic_run import FULL_ARMS, PILOT_ARMS, build_synthetic_run

pytestmark = pytest.mark.unit

PREREG = Path(__file__).resolve().parents[2] / "evals" / "prereg"
FAST = {"n_boot": 200, "n_perm": 200, "n_boot_mean": 100}


@pytest.fixture(scope="module")
def pilot(tmp_path_factory):
    root = tmp_path_factory.mktemp("pilot")
    run = build_synthetic_run(root, arms=PILOT_ARMS)
    return build_report(run, mode="pilot", out_dir=root / "out", **FAST)


@pytest.fixture(scope="module")
def full(tmp_path_factory):
    root = tmp_path_factory.mktemp("full")
    run = build_synthetic_run(root, arms=FULL_ARMS, n_prs=20, n_rationale=8, n_hand=6)
    return build_report(run, mode="full", out_dir=root / "out", **FAST)


# --- every number in the markdown is in the json ---------------------------------------

_NUMBER = re.compile(r"(?<![\w@#/.$-])-?\d+(?:\.\d+)?(?![\w@])")
_CODE = re.compile(r"`[^`]*`")


def _json_numbers(value, out: set[float]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, int | float):
        out.add(abs(float(value)))
    elif isinstance(value, dict):
        for key, inner in value.items():
            try:
                out.add(abs(float(key)))
            except ValueError:
                pass
            _json_numbers(inner, out)
    elif isinstance(value, list):
        for inner in value:
            _json_numbers(inner, out)


def _missing_numbers(markdown: str, data: dict) -> list[str]:
    known: set[float] = set()
    _json_numbers(data, known)
    text = _CODE.sub("", markdown)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    missing = []
    for token in _NUMBER.findall(text):
        places = len(token.split(".")[1]) if "." in token else 0
        wanted = abs(float(token))
        tolerance = 0.5 * 10**-places + 1e-9
        if not any(
            abs(value * scale - wanted) <= tolerance
            for value in known
            for scale in (1.0, 100.0, 0.001)
        ):
            missing.append(token)
    return missing


def test_full_report_has_every_section_and_every_number_is_in_the_json(full):
    sections = set(full.data["sections"])
    assert {
        "comparisons",
        "corpus",
        "gold_quality",
        "main_results",
        "retrieval",
        "ablation",
        "rerankers",
        "trajectory",
        "cost",
        "pareto",
        "routing",
        "drift",
        "cutoff",
        "judge_results",
        "judge_agreement",
        "exclusions",
    } <= sections
    assert "limitations" not in sections and "findings" not in sections
    assert {"pareto", "ablation", "steps_to_gold", "drift"} <= set(full.data["figures"])
    for figure in full.data["figures"].values():
        assert (full.out_dir / figure["path"]).read_text(encoding="utf-8").startswith("<svg")
    assert (full.out_dir / "trajectory_graph.json").is_file()
    assert (full.out_dir / "manifest.json").is_file()
    assert _missing_numbers(full.markdown, full.data) == []


def test_full_mode_states_one_result_per_hypothesis(full):
    ids = {c["id"] for c in full.data["comparisons"]}
    assert ids == {s.id for s in FULL_COMPARISONS}
    by_id = {c["id"]: c for c in full.data["comparisons"]}
    assert by_id["H5"]["tost"]["margin"] == 0.03 and by_id["H5"]["p_adjusted"] is None
    assert by_id["H6-hyde"]["gap"]["cost_fraction"]["criterion"] == 0.25
    assert by_id["H1b"]["criterion"] == 5.0 and by_id["H7-recall"]["criterion"] == 0.9
    assert by_id["H7-recall"]["verdict"] == by_id["H7-cost"]["verdict"]
    assert "Hypotheses" in full.markdown


# --- the pilot -------------------------------------------------------------------------


def test_pilot_report_fills_every_applicable_section_and_nothing_empty(pilot):
    sections = set(pilot.data["sections"])
    assert {
        "findings",
        "comparisons",
        "corpus",
        "gold_quality",
        "main_results",
        "retrieval",
        "ablation",
        "trajectory",
        "cost",
        "pareto",
        "routing",
        "drift",
        "cutoff",
        "judge_results",
        "judge_agreement",
        "limitations",
    } <= sections
    assert pilot.data["scope"]["n_changeset"] == 76
    assert _missing_numbers(pilot.markdown, pilot.data) == []
    for word in ("TBD", "placeholder", "TODO"):
        assert word not in pilot.markdown
    lines = pilot.markdown.splitlines()
    for index, line in enumerate(lines):
        if re.fullmatch(r"\|( --- \|)+", line):
            assert index + 1 < len(lines) and lines[index + 1].startswith("|")


def test_sections_for_arms_that_were_not_run_are_absent(pilot):
    pairs = {(r["arm_a"], r["arm_b"]) for r in pilot.data["rerankers"]["rows"]}
    assert pairs == {("hybrid_rerank", "hybrid"), ("structural_rerank", "structural")}
    channels = {r["channel"] for r in pilot.data["ablation"]["rows"]}
    assert channels == {"cochange"}
    assert set(pilot.data["trajectory"]["by_arm"]) == {"agent"}
    assert "agent_workers" not in pilot.data["main_results"]["by_arm"]
    assert "H5" not in {c["id"] for c in pilot.data["comparisons"]}


def test_pilot_comparisons_have_separate_holm_families_and_mdd(pilot):
    comparisons = {c["id"]: c for c in pilot.data["comparisons"]}
    assert set(comparisons) == {s.id for s in PILOT_COMPARISONS}
    assert comparisons["P1a"]["family_size_run"] == 6
    assert comparisons["S1"]["family_size_run"] == 4
    assert all(c["mdd"] is not None for c in comparisons.values())
    assert "MDD" in pilot.markdown


def test_limitations_contain_every_row_filled_from_the_data(pilot):
    rows = {r["id"]: r for r in pilot.data["limitations"]}
    assert len(rows) == 11
    for row in rows.values():
        assert row["what"] and row["effect"] and row["full_run"]
    text = {
        k: " ".join((r["title"], r["what"], r["effect"], r["full_run"])) for k, r in rows.items()
    }
    overall = pilot.data["gold_quality"]["overall"]
    assert f"{overall['rate'] * 100:.1f}%" in text["gold_error"]
    mdds = [c["mdd"] for c in pilot.data["comparisons"] if c["metric"] == "recall"]
    assert f"{min(mdds) * 100:.1f}" in text["changeset_size"]
    assert "76 change-set questions" in text["changeset_size"]
    for missing in ("hybrid_jev", "agent_workers", "agent_text_tools", "structural_-graph"):
        assert missing in text["arms_not_run"]
    kappa = next(e for e in pilot.data["judge_agreement"]["entries"] if e["family"] == "all")
    assert f"{kappa['kappa']:.2f}" in text["judge"]
    assert str(pilot.data["scope"]["n_post_cutoff"]) in text["cutoff_mix"]
    assert "does not address this either" in text["one_generator"]
    for row in rows.values():
        assert f"### {row['title']}" in pilot.markdown


def test_pilot_findings_carry_n_and_interval_and_scope(pilot):
    findings = pilot.data["findings"]
    assert 3 <= len(findings) <= 5
    for finding in findings:
        assert re.search(r"n = \d+", finding["text"])
        assert "95% CI" in finding["text"]
    assert len(pilot.data["scope_lines"]) == 2
    assert "pilot" in pilot.data["scope_lines"][0]


def test_an_interval_spanning_zero_never_says_found_more(pilot):
    for c in pilot.data["comparisons"]:
        if not c["resolved"]:
            assert "found more" not in c["sentence"] and "found fewer" not in c["sentence"]
            assert c["sentence"].startswith("Not resolved at this sample size")
        else:
            assert re.search(r"n = \d+", c["sentence"]) and "95% CI" in c["sentence"]


# --- wording ---------------------------------------------------------------------------


def test_check_wording_flags_forbidden_phrasings():
    assert check_wording("The gap is significant.")
    assert check_wording("It is significant (permutation test, n = 40).") == []
    assert check_wording("This holds in general.")
    assert check_wording("It holds for repositories in general.")
    assert check_wording("Retrieval always helps.")
    assert check_wording("Not resolved at this sample size (n = 4).") == []


def test_sentences_follow_the_wording_rules():
    base = {"arm_a": "a", "arm_b": "b", "metric": "recall", "n": 80, "mdd": 0.071}
    up = comparison_sentence({**base, "estimate": 0.05, "ci_lo": 0.01, "ci_hi": 0.09}, 2)
    assert up == (
        "On these two repositories, `a` found more of the changed files than `b` "
        "(+5.0 points, 95% CI 1.0 to 9.0, n = 80)."
    )
    down = comparison_sentence({**base, "estimate": -0.05, "ci_lo": -0.09, "ci_hi": -0.01}, 2)
    assert "found fewer" in down and "-5.0 points" in down
    flat = comparison_sentence({**base, "estimate": 0.01, "ci_lo": -0.02, "ci_hi": 0.04}, 2)
    assert flat == (
        "Not resolved at this sample size (minimum detectable difference ≈ 7.1 points, n = 80)."
    )
    cost = comparison_sentence(
        {**base, "metric": "cost", "estimate": -0.002, "ci_lo": -0.003, "ci_hi": -0.001}, 3
    )
    assert "On these three repositories" in cost and "cost less per question than" in cost


# --- statistics, end to end ------------------------------------------------------------


def test_the_minimum_detectable_difference_matches_a_hand_computed_case(monkeypatch):
    diffs = {"a": 0.1, "b": 0.3, "c": 0.2, "d": 0.4}
    items = [ItemRef(k, "r", k) for k in diffs]
    spec = PILOT_COMPARISONS[2]
    monkeypatch.setattr(comparisons_module, "specs_for", lambda mode: (spec,))

    def get(arm: str, item_id: str, metric: str) -> float:
        return diffs[item_id] if arm == spec.arm_a else 0.0

    records = run_comparisons(
        "pilot",
        items,
        get,
        [spec.arm_a, spec.arm_b],
        StatConfig(n_boot=100, n_perm=100),
        repositories=1,
    )
    # Cluster means .1 .3 .2 .4: sd = sqrt(.05 / 3), se = sd / 2, mdd = (1.959964 + 0.841621) * se.
    assert records[0]["mdd"] == pytest.approx(0.180842, abs=1e-5)
    assert records[0]["estimate"] == pytest.approx(0.25)
    assert records[0]["n"] == 4 and records[0]["n_clusters"] == 4


def test_the_ratio_bootstrap_matches_a_hand_computed_estimate():
    pairs = [(2, 1), (4, 2), (6, 3)]
    rows = [RatioObs("r", str(i), num, den) for i, (num, den) in enumerate(pairs)]
    result = ratio_bootstrap(rows, n_boot=200, seed=1)
    assert result.estimate == pytest.approx(2.0)
    assert result.lo == pytest.approx(2.0) and result.hi == pytest.approx(2.0)
    assert result.n == 3 and result.n_clusters == 3
    missing = ratio_bootstrap([*rows, RatioObs("r", "x", None, 1.0)], n_boot=50, seed=1)
    assert missing.n_excluded == 1


def _table_rows(path: str) -> list[list[str]]:
    table = []
    for line in (PREREG / path).read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and re.fullmatch(r"[PSH]\d[ab]?", cells[0]):
            table.append(cells)
    return table


def test_the_comparison_lists_match_the_preregistrations():
    text = (PREREG / "pilot.md").read_text(encoding="utf-8")
    assert re.findall(r"`([^`]+)` vs `([^`]+)`", text) == list(SIMPLE_COMPARISONS)
    full_rows = _table_rows("v1.md")
    assert [c[0] for c in full_rows] == ["H1a", "H1b", "H2", "H3", "H4", "H5", "H6", "H7"]
    for cells in full_rows:
        arms = set(re.findall(r"`([^`]+)`", cells[1] + cells[3]))
        for spec in FULL_COMPARISONS:
            if spec.hypothesis == cells[0]:
                assert {spec.arm_a, spec.arm_b} <= arms


# --- gate ------------------------------------------------------------------------------


def test_the_builder_refuses_when_the_selftest_fails(tmp_path, monkeypatch):
    run = build_synthetic_run(tmp_path, arms=("classic", "hybrid"), n_prs=6, with_judge=False)

    def failing() -> None:
        raise AssertionError("arithmetic changed")

    monkeypatch.setitem(selftest_registry._CASES, "report: broken case", failing)
    with pytest.raises(ReportError, match="broken case"):
        build_report(run, mode="pilot", out_dir=tmp_path / "out", **FAST)
    assert not (tmp_path / "out" / "report.md").exists()


def test_limitations_report_unknowns_without_labels(tmp_path):
    run = build_synthetic_run(tmp_path, arms=("classic", "structural"), n_prs=6, with_judge=False)
    report = build_report(run, mode="pilot", out_dir=tmp_path / "out", **FAST)
    rows = {r["id"]: r for r in report.data["limitations"]}
    assert "unknown" in rows["gold_error"]["effect"]
    assert "unknown" in rows["judge"]["effect"]
    assert "judge_results" not in report.data
    written = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert written["mode"] == "pilot"
    facts = {**report.data, "comparisons": report.data.get("comparisons", [])}
    assert len(build_limitations(facts)) == 11


def test_the_report_command_takes_a_run_a_mode_and_an_output_directory():
    server_root = Path(__file__).resolve().parents[2]
    help_text = subprocess.run(
        [sys.executable, "-m", "evals", "report", "--help"],
        cwd=server_root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert help_text.returncode == 0
    for flag in ("--run", "--mode", "--out", "--judge-slug"):
        assert flag in help_text.stdout
    assert "simple" in help_text.stdout
    missing = subprocess.run(
        [sys.executable, "-m", "evals", "report"],
        cwd=server_root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert missing.returncode == 2
