"""The default report: sections, comparisons, wording and the codebase measurements."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from evals.corpus.style import (
    CommitRow,
    SymbolRow,
    ai_in_trailers,
    code_style,
    comment_lines,
    commit_ai_signals,
    documentation_lines,
    history_style,
    is_ai_author,
    read_commits,
    read_style,
    repo_style,
    write_style,
)
from evals.report import ReportError, build_report
from evals.report.comparisons import SIMPLE_COMPARISONS
from evals.report.simple import diff_text, sentence, verdict_of
from tests.evals.synthetic_run import ERAS, PILOT_ARMS, SIMPLE_REPOS, build_simple_run
from tests.evals.test_report import _missing_numbers

pytestmark = pytest.mark.unit

PREREG = Path(__file__).resolve().parents[2] / "evals" / "prereg"
FAST = {"n_boot": 300, "n_boot_mean": 200}

SECTIONS = [
    "scope",
    "tables",
    "comparisons",
    "style",
    "cost_quality",
    "judge_check",
    "limitations",
]
HEADINGS = [
    "## Scope",
    "## Results",
    "## Head-to-head comparisons",
    "## Change against explain",
    "## How the codebases differ",
    "## Cost against quality",
    "## Judge check",
    "## Limitations",
]


@pytest.fixture(scope="module")
def simple(tmp_path_factory):
    root = tmp_path_factory.mktemp("simple")
    run = build_simple_run(root)
    return build_report(run, out_dir=root / "out", **FAST)


# --- the sections ----------------------------------------------------------------------


def test_simple_is_the_default_mode_and_every_section_is_present(simple):
    assert simple.data["mode"] == "simple"
    assert simple.data["sections"] == SECTIONS
    for heading in HEADINGS:
        assert heading in simple.markdown, heading
    assert {"report.json", "report.md", "figures/cost_quality.svg"} <= set(simple.paths)
    written = json.loads((simple.out_dir / "report.json").read_text(encoding="utf-8"))
    assert written["sections"] == SECTIONS


def test_scope_lists_each_repository_with_its_era_and_the_models(simple):
    scope = simple.data["scope"]
    assert [r["name"] for r in scope["repositories"]] == sorted(SIMPLE_REPOS)
    assert {r["name"]: r["era"] for r in scope["repositories"]} == ERAS
    assert all(r["questions"] == {"change": 12, "explain": 6} for r in scope["repositories"])
    assert scope["questions"] == {"change": 36, "explain": 18}
    assert scope["n_arms"] == 10 and scope["judge_model"]
    assert scope["deepeval_versions"] == ["4.3.2"]
    for era in ERAS.values():
        assert era in simple.markdown
    assert "DeepEval 4.3.2" in simple.markdown


def test_the_overall_table_has_every_arm_and_metric_with_its_n(simple):
    tables = simple.data["tables"]
    assert set(tables["overall"]["arms"]) == set(PILOT_ARMS)
    assert tables["metrics"] == [
        "recall",
        "precision",
        "correctness",
        "faithfulness",
        "relevancy",
        "cost",
        "speed",
        "steps",
    ]
    for arm, entry in tables["overall"]["arms"].items():
        for metric in ("recall", "precision", "correctness", "faithfulness", "relevancy"):
            cell = entry[metric]
            assert cell["n"] > 0 and cell["lo"] <= cell["mean"] <= cell["hi"], (arm, metric)
        assert entry["format_failures"]["n"] > 0
    assert tables["overall"]["arms"]["hybrid_hyde"]["n_errors"] > 0
    steps = {a: e["steps"] for a, e in tables["overall"]["arms"].items()}
    assert steps["agent"] and steps["classic"] is None
    for header in ("File recall", "Correctness", "Faithfulness", "Answer relevancy"):
        assert header in simple.markdown


def test_there_is_one_table_per_repository_and_one_per_kind(simple):
    tables = simple.data["tables"]
    assert sorted(tables["by_repo"]) == sorted(SIMPLE_REPOS)
    for repo, table in tables["by_repo"].items():
        assert table["n_questions"] == 18
        assert f"`{repo}` ({ERAS[repo]})" in simple.markdown
    assert sorted(tables["by_kind"]) == ["change", "explain"]
    assert tables["by_kind"]["change"]["n_questions"] == 36
    assert tables["by_kind"]["explain"]["n_questions"] == 18


def test_explain_questions_are_scored_on_their_required_files(simple):
    # Every arm's explain recall is a real mean, so the hand items' files were used.
    for entry in simple.data["tables"]["by_kind"]["explain"]["arms"].values():
        assert entry["recall"]["n"] >= 12


# --- head to head ----------------------------------------------------------------------


def test_the_comparison_rows_are_the_preregistered_pairs_in_order(simple):
    pilot = (PREREG / "pilot.md").read_text(encoding="utf-8")
    stated = re.findall(r"`([^`]+)` vs `([^`]+)`", pilot)
    seen: list[tuple[str, str]] = []
    for record in simple.data["comparisons"]:
        pair = (record["arm_a"], record["arm_b"])
        if pair not in seen:
            seen.append(pair)
    assert seen == stated == list(SIMPLE_COMPARISONS)
    for pair in SIMPLE_COMPARISONS:
        for metric in ("recall", "correctness", "cost"):
            scopes = {
                r["scope"]
                for r in simple.data["comparisons"]
                if (r["arm_a"], r["arm_b"]) == pair and r["metric"] == metric
            }
            assert scopes == {"overall", *SIMPLE_REPOS}, (pair, metric)


def test_comparisons_whose_arms_were_not_run_are_left_out(tmp_path):
    arms = ("classic", "hybrid", "hybrid_rerank")
    run = build_simple_run(tmp_path, arms=arms, n_change=8, n_explain=4)
    report = build_report(run, out_dir=tmp_path / "out", **FAST)
    pairs = {(r["arm_a"], r["arm_b"]) for r in report.data["comparisons"]}
    assert pairs == {("hybrid", "classic"), ("hybrid_rerank", "hybrid")}


def test_a_difference_is_stated_only_when_its_interval_excludes_zero(simple):
    resolved = unresolved = 0
    for record in simple.data["comparisons"]:
        spans = record["ci_lo"] <= 0 <= record["ci_hi"]
        text = record["sentence"]
        assert f"n = {record['n']}" in text
        if spans:
            unresolved += 1
            assert record["verdict"] == "not resolved"
            assert text.startswith("Not resolved at this sample size")
            assert "higher" not in text and "more per answer" not in text
        else:
            resolved += 1
            assert record["verdict"] in ("A higher", "B higher")
            assert "95% CI" in text and text.startswith("On ")
            assert ("scored higher than" in text) or ("cost more per answer than" in text)
    assert resolved and unresolved


def test_the_wording_rule_on_hand_built_records():
    base = {
        "arm_a": "agent",
        "arm_b": "auto",
        "metric": "recall",
        "scope": "overall",
        "n": 40,
        "estimate": 0.10,
    }
    spanning = {**base, "ci_lo": -0.02, "ci_hi": 0.22, "verdict": verdict_of(-0.02, 0.22)}
    assert spanning["verdict"] == "not resolved"
    assert "higher" not in sentence(spanning, 3)
    assert "not resolved" in sentence(spanning, 3).lower()
    higher = {**base, "ci_lo": 0.03, "ci_hi": 0.17, "verdict": verdict_of(0.03, 0.17)}
    assert sentence(higher, 3) == (
        "On these three repositories, `agent` scored higher than `auto` on file recall "
        "(+0.100, 95% CI 0.030 to 0.170, n = 40)."
    )
    lower = {
        **base,
        "estimate": -0.10,
        "ci_lo": -0.17,
        "ci_hi": -0.03,
        "verdict": verdict_of(-0.17, -0.03),
    }
    assert lower["verdict"] == "B higher"
    assert sentence(lower, 3).startswith(
        "On these three repositories, `auto` scored higher than `agent` on file recall (+0.100"
    )
    assert verdict_of(0.0, 0.1) == "not resolved" and verdict_of(-0.1, 0.0) == "not resolved"
    assert diff_text("cost", -0.00024) == "-$0.00024"
    assert diff_text("recall", 0.0004, signed=True) == "+0.000"


def test_no_forbidden_wording_appears(simple):
    from evals.report.wording import check_wording

    assert check_wording(simple.markdown) == []
    assert "significan" not in simple.markdown.lower()
    assert "permutation" not in simple.markdown.lower() and "Holm" not in simple.markdown


def test_every_number_in_the_markdown_is_in_the_json(simple):
    assert _missing_numbers(simple.markdown, simple.data) == []


# --- the other sections ----------------------------------------------------------------


def test_the_cost_against_quality_section_has_a_figure_and_a_frontier(simple):
    section = simple.data["cost_quality"]
    assert {p["arm"] for p in section["points"]} == set(PILOT_ARMS)
    assert section["frontier"] and set(section["frontier"]) <= set(PILOT_ARMS)
    assert "![" in simple.markdown and "figures/cost_quality.svg" in simple.markdown
    svg = (simple.out_dir / "figures" / "cost_quality.svg").read_text(encoding="utf-8")
    assert svg.startswith("<svg") and "agent" in svg


def test_the_judge_check_reports_the_hand_scored_agreement(simple):
    check = simple.data["judge_check"]
    assert check["done"] and check["n"] == 40 and check["meets_minimum"]
    assert {e["dimension"] for e in check["entries"]} == {"correct", "made_up"}
    assert "hand-scored answers" in simple.markdown


def test_the_codebase_section_lists_every_measure_and_the_ai_lower_bound(simple):
    style = simple.data["style"]["repos"]
    assert sorted(style) == sorted(SIMPLE_REPOS)
    assert style["repo-go"]["ai_involvement"]["all"]["k"] > 0
    assert style["repo-py"]["ai_involvement"]["all"]["k"] == 0
    assert "lower bound" in simple.markdown
    for column in (
        "Comments and docstrings per function",
        "Average function length",
        "Average file length",
        "Average identifier length",
        "Median commit message",
        "Median PR description",
        "Median files changed per PR",
        "last 12 months",
    ):
        assert column in simple.markdown, column
    observations = simple.data["observations"]
    assert observations["n_repositories"] == 3
    assert "observations on 3 repositories" in simple.markdown
    assert "does not test why" in simple.markdown


def test_the_limitations_carry_the_runs_own_numbers(simple):
    by_id = {item["id"]: item for item in simple.data["limitations"]}
    assert set(by_id) == {
        "repositories",
        "generator",
        "explain_keys",
        "same_model",
        "judge",
        "errors",
    }
    assert "one per era (latest AI, before AI, early AI)" in by_id["repositories"]["text"]
    checks = by_id["explain_keys"]["facts"]["checks"]
    assert checks["supported"] + checks["partly_supported"] + checks["unsupported"] == 18
    assert f"{checks['unsupported']} unsupported of 18 checked" in by_id["explain_keys"]["text"]
    facts = by_id["errors"]["facts"]
    assert facts["errors"] > 0 and facts["generations"] == 540
    assert "weighted kappa" in by_id["judge"]["text"]


# --- missing data ----------------------------------------------------------------------


def test_sections_for_missing_data_are_left_out_cleanly(tmp_path):
    run = build_simple_run(
        tmp_path,
        arms=("classic", "hybrid"),
        n_explain=0,
        with_judge=False,
        with_style=False,
        with_checks=False,
    )
    report = build_report(run, out_dir=tmp_path / "out", **FAST)
    assert report.data["sections"] == ["scope", "tables", "comparisons", "limitations"]
    text = report.markdown
    for absent in (
        "How the codebases differ",
        "Cost against quality",
        "Judge check",
        "Change against explain",
        "Correctness",
        "Faithfulness",
    ):
        assert absent not in text, absent
    assert "TBD" not in text and "TODO" not in text
    assert "|  |" not in text
    assert "judge_check" not in report.data and "style" not in report.data
    assert "cost_quality" not in report.data
    assert not (tmp_path / "out" / "figures").exists()
    for block in re.findall(r"(?:^\|.*\n)+", text, flags=re.MULTILINE):
        assert len(block.splitlines()) >= 3, block
    assert [r["metric"] for r in report.data["comparisons"] if r["scope"] == "overall"] == [
        "recall",
        "cost",
    ]


def test_without_a_hand_check_the_judge_line_says_it_was_not_done(tmp_path):
    run = build_simple_run(tmp_path, arms=("classic", "hybrid"), n_labels=0, n_explain=3)
    report = build_report(run, out_dir=tmp_path / "out", **FAST)
    assert report.data["judge_check"] == {"done": False, "labels_found": 0}
    assert "has not yet been checked against hand-scored answers" in report.markdown
    judge = next(i for i in report.data["limitations"] if i["id"] == "judge")
    assert "has not been checked" in judge["text"]
    assert "(exploratory)" not in report.markdown


def test_one_repository_without_eras_still_builds(tmp_path):
    run = build_simple_run(tmp_path, repos=("repo-py",), arms=("classic", "hybrid"), n_change=6)
    counts_path = run / "corpus_counts.json"
    counts = json.loads(counts_path.read_text(encoding="utf-8"))
    del counts["repo-py"]["era"]
    counts_path.write_text(json.dumps(counts), encoding="utf-8")
    report = build_report(run, out_dir=tmp_path / "out", **FAST)
    assert "not labelled" in report.markdown
    assert "observations" not in report.data
    repositories = next(i for i in report.data["limitations"] if i["id"] == "repositories")
    assert "one per era" not in repositories["text"]


def test_the_other_modes_still_build(tmp_path):
    run = build_simple_run(tmp_path, arms=PILOT_ARMS, n_change=8, n_explain=3)
    full = build_report(run, mode="full", out_dir=tmp_path / "full", n_perm=100, **FAST)
    assert full.data["mode"] == "full" and full.markdown.startswith("# Evaluation report")
    pilot = build_report(run, mode="pilot", out_dir=tmp_path / "pilot", n_perm=100, **FAST)
    assert pilot.data["mode"] == "pilot"
    with pytest.raises(ReportError, match="unknown mode"):
        build_report(run, mode="other", out_dir=tmp_path / "x")


# --- the codebase measurements ----------------------------------------------------------


def _function(source: str, docstring: str | None = None, **extra) -> SymbolRow:
    fields = {
        "kind": "function",
        "name": "work",
        "start_line": 1,
        "end_line": 5,
        "source": source,
        "docstring": docstring,
        "path": "pkg/mod.py",
        "language": "python",
    }
    return SymbolRow(**{**fields, **extra})


def test_comment_lines_are_counted_per_language():
    python = "def f():\n    # one\n    x = 1  # trailing\n    #!not a comment shebang\n    # two\n"
    assert comment_lines(python, "a.py", "python") == ["# one", "# two"]
    slash = "function f() {\n  // one\n  /* two\n     three */\n  return 1; // trailing\n}\n"
    assert comment_lines(slash, "a.ts", "typescript") == ["// one", "/* two", "three */"]
    assert comment_lines("x = 1\n// y\n", "a.unknown", None) == ["// y"]
    assert comment_lines("# y\n", "script.sh", None) == ["# y"]


def test_documentation_lines_add_the_docstring_unless_it_is_already_in_the_source():
    plain = _function("def work():\n    # note\n    return 1\n", "Does a thing.\n\nSecond line.")
    assert documentation_lines(plain) == 1 + 2
    inside = _function(
        "/** Does a thing. */\nfunction work() {}\n",
        "Does a thing.",
        path="a.ts",
        language="typescript",
    )
    assert documentation_lines(inside) == 1
    assert documentation_lines(_function("def work():\n    return 1\n")) == 0


def test_code_style_on_a_tiny_repository():
    symbols = [
        _function("def a():\n    # c\n    return 1\n", "Doc.", name="alpha", end_line=4),
        _function("def b():\n    return 2\n", None, name="be", start_line=10, end_line=19),
        SymbolRow("class", "Klass", 1, 30, "class Klass: ...", None, "pkg/mod.py", "python"),
        SymbolRow("import", "os", 1, 1, "import os", None, "pkg/mod.py", "python"),
        SymbolRow("variable", "x", 1, 1, "x = 1", None, "pkg/mod.py", "python"),
    ]
    style = code_style(symbols, [10, 30])
    assert style["functions"]["n"] == 2
    assert style["functions"]["doc_lines_per_function"] == pytest.approx((2 + 0) / 2)
    assert style["functions"]["mean_length_lines"] == pytest.approx((4 + 10) / 2)
    assert style["files"] == {"n": 2, "mean_length_lines": 20.0}
    # alpha (5), be (2), Klass (5) and x (1); the import's name is not an identifier.
    assert style["identifiers"]["n"] == 4
    assert style["identifiers"]["mean_length_chars"] == pytest.approx((5 + 2 + 5 + 1) / 4)
    empty = code_style([], [])
    assert empty["functions"]["doc_lines_per_function"] is None and empty["files"]["n"] == 0


@pytest.mark.parametrize(
    ("message", "tools"),
    [
        ("fix\n\nCo-Authored-By: Claude <noreply@anthropic.com>", ["claude"]),
        ("fix\n\nco-authored-by: Claude Opus 4.5 <noreply@anthropic.com>", ["claude"]),
        (
            "fix\n\nCo-authored-by: Copilot <175728472+Copilot@users.noreply.github.com>",
            ["copilot"],
        ),
        ("fix\n\nCo-Authored-By: Cursor Agent <cursoragent@cursor.com>", ["cursor"]),
        (
            "fix\n\nCo-authored-by: Devin AI <1+devin-ai[bot]@users.noreply.github.com>",
            ["devin"],
        ),
        ("fix\n\nCo-authored-by: aider (gpt-4o) <noreply@aider.chat>", ["aider"]),
        ("fix\n\nCo-authored-by: Gemini <gemini@google.com>", ["gemini"]),
        ("fix\n\nCo-Authored-By: ChatGPT <noreply@openai.com>", ["chatgpt"]),
        ("fix\n\nCo-authored-by: google-labs-jules[bot] <x@y.z>", ["jules"]),
        ("fix\n\nCo-authored-by: Jane Roe <jane@example.com>", []),
        ("fix\n\nCo-authored-by: Jules Verne <jules@example.com>", []),
        ("fix\n\nCo-authored-by: Devin Smith <devin@example.com>", []),
        ("Claude wrote this in the subject, no trailer", []),
        ("fix\n\nSigned-off-by: Claude <noreply@anthropic.com>", []),
    ],
)
def test_ai_trailers_are_detected_only_when_a_trailer_names_an_ai(message, tools):
    assert ai_in_trailers(message) == tools


@pytest.mark.parametrize(
    ("name", "email", "expected"),
    [
        ("claude[bot]", "209825114+claude[bot]@users.noreply.github.com", True),
        ("copilot-swe-agent[bot]", "198982749+Copilot@users.noreply.github.com", True),
        (
            "devin-ai-integration[bot]",
            "158243242+devin-ai-integration[bot]@users.noreply.github.com",
            True,
        ),
        ("Claude", "noreply@anthropic.com", True),
        ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com", False),
        ("github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com", False),
        ("Claude Monet", "claude@example.com", False),
        ("Devin Smith", "devin@example.com", False),
    ],
)
def test_ai_bot_authors_are_detected_and_other_bots_are_not(name, email, expected):
    assert is_ai_author(name, email) is expected


def _commit(days_before: int, message: str, name="Dev", email="dev@example.com") -> CommitRow:
    base = datetime(2026, 6, 1, tzinfo=UTC)
    return CommitRow(name, email, base - timedelta(days=days_before), message)


def test_history_style_counts_ai_involvement_as_a_lower_bound_over_two_windows():
    commits = [
        _commit(0, "latest\n\nCo-Authored-By: Claude <noreply@anthropic.com>"),
        _commit(10, "bot work", "copilot-swe-agent[bot]", "1+Copilot@users.noreply.github.com"),
        _commit(
            20,
            "both\n\nCo-authored-by: Copilot <x@users.noreply.github.com>",
            "claude[bot]",
            "c@users.noreply.github.com",
        ),
        _commit(100, "plain"),
        _commit(400, "old plain, long enough message " * 3),
        _commit(500, "old\n\nCo-Authored-By: Claude <noreply@anthropic.com>"),
    ]
    style = history_style(commits, [("a" * 10, 3), (None, 1), ("b" * 30, 5)])
    ai = style["ai_involvement"]
    assert ai["lower_bound"] is True
    assert (ai["all"]["k"], ai["all"]["n"]) == (4, 6)
    assert (ai["last_12_months"]["k"], ai["last_12_months"]["n"]) == (3, 4)
    assert ai["last_12_months"]["since"] == "2025-06-01"
    assert ai["by_signal"] == {"trailer": 3, "bot_author": 2}
    assert ai["tools"] == ["claude", "copilot"]
    assert 0 < ai["all"]["lo"] < ai["all"]["share"] < ai["all"]["hi"] < 1
    assert style["commits"]["n"] == 6
    assert style["pull_requests"] == {
        "n": 3,
        "median_description_chars": 10,
        "median_files_changed": 3,
    }
    assert commit_ai_signals(commits[2]) == ["trailer", "bot_author"]


def _git(root: Path, *args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env=env,
    ).stdout


def test_commits_are_read_from_a_clone_with_their_trailers_and_merges_left_out(tmp_path):
    repo = tmp_path / "tiny"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Dev")
    _git(repo, "config", "user.email", "dev@example.com")
    messages = [
        "first commit",
        "second commit\n\nbody line\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
    ]
    for n, message in enumerate(messages):
        (repo / f"f{n}.txt").write_text(str(n), encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", message)
    _git(repo, "checkout", "-q", "-b", "side")
    (repo / "side.txt").write_text("s", encoding="utf-8")
    _git(repo, "add", ".")
    _git(
        repo,
        "commit",
        "-q",
        "-m",
        "side work",
        "--author=copilot-swe-agent[bot] <1+Copilot@users.noreply.github.com>",
    )
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "side", "-m", "Merge branch side")
    base = _git(repo, "rev-parse", "HEAD").strip()

    commits = read_commits(repo, base)
    assert sorted(c.message.splitlines()[0] for c in commits) == [
        "first commit",
        "second commit",
        "side work",
    ]
    by_subject = {c.message.splitlines()[0]: c for c in commits}
    assert "Co-Authored-By: Claude" in by_subject["second commit"].message
    assert by_subject["side work"].author_name == "copilot-swe-agent[bot]"
    style = history_style(commits, [])
    assert (style["ai_involvement"]["all"]["k"], style["ai_involvement"]["all"]["n"]) == (2, 3)
    assert read_commits(tmp_path / "missing", base) == []


def test_the_style_file_round_trips_and_is_empty_when_absent(tmp_path):
    assert read_style(tmp_path / "none.json") == {}
    write_style(tmp_path / "style.json", {"r": {"files": {"n": 1}}})
    assert read_style(tmp_path / "style.json") == {"r": {"files": {"n": 1}}}


@pytest.mark.integration
def test_repo_style_reads_the_database_and_the_clone(ingest, db, history):
    result = ingest()
    style = repo_style(db, result.repo_id, history.root, history.base)
    assert style["functions"]["n"] > 0
    assert style["files"]["n"] > 0 and style["files"]["mean_length_lines"] > 0
    assert style["identifiers"]["mean_length_chars"] > 0
    assert style["commits"]["n"] > 0 and style["commits"]["median_message_chars"] > 0
    assert style["pull_requests"]["n"] >= 0
    assert style["ai_involvement"]["all"]["n"] == style["commits"]["n"]
    assert style["base_commit"] == history.base
    without_clone = repo_style(db, result.repo_id, None, history.base)
    assert "ai_involvement" not in without_clone and "commits" not in without_clone


@pytest.mark.integration
def test_capture_writes_the_era_and_the_style_file(ingest, db, history, tmp_path):
    import shutil

    from sqlalchemy import select

    from app.models import Repository, User
    from evals.report.capture import capture_run_context
    from tests.evals.run_helpers import make_gold_item

    result = ingest()
    corpus = tmp_path / "corpus.yaml"
    corpus.write_text(
        "repos:\n  - name: sample\n    url: https://github.com/owner/sample\n"
        "    language: Python\n    licence: MIT\n    era: early AI\n"
        f'    base_commit: "{history.base}"\n',
        encoding="utf-8",
    )
    clones = tmp_path / "clones"
    shutil.copytree(history.root, clones / "owner__sample")
    email = db.execute(
        select(User.email)
        .join(Repository, Repository.user_id == User.id)
        .where(Repository.id == result.repo_id)
    ).scalar_one()
    run_dir = tmp_path / "out" / "runs" / "r1"

    missing = capture_run_context(
        db,
        run_dir=run_dir,
        items=[make_gold_item(repo="sample", gold_files=("src/app.py",))],
        out_dir=tmp_path / "out",
        user_email=email,
        corpus_path=corpus,
        clones_dir=clones,
    )

    assert missing == []
    counts = json.loads((run_dir / "corpus_counts.json").read_text(encoding="utf-8"))
    assert counts["sample"]["era"] == "early AI"
    style = read_style(run_dir / "style.json")["sample"]
    assert style["functions"]["n"] > 0 and style["commits"]["n"] > 0
    assert style["base_commit"] == history.base


@pytest.mark.parametrize(
    ("family", "template", "tags", "kind"),
    [
        ("hand", "hand.explain", (), "explain"),
        ("hand", "hand.architecture", (), "explain"),
        ("hand", "hand.flow", (), "explain"),
        ("hand", "hand.unanswerable", ("unanswerable",), None),
    ],
)
def test_answerable_hand_questions_count_as_explain(family, template, tags, kind):
    from evals.gold.schema import GoldItem
    from evals.report.simple import item_kind

    item = GoldItem(
        id="x",
        repo="r",
        base_commit="b" * 40,
        family=family,
        template=template,
        question_seed="q",
        tags=list(tags),
    )
    assert item_kind(item) == kind


def test_every_answer_is_kept_per_question_and_matches_the_tables(simple):
    import csv

    from evals.report.simple import QUESTION_COLUMNS

    jsonl = simple.out_dir / "questions.jsonl"
    table = simple.out_dir / "questions.csv"
    assert simple.paths["questions.jsonl"] == jsonl
    assert simple.paths["questions.csv"] == table
    rows = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines()]
    with table.open(encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert len(csv_rows) == len(rows) > 0
    assert all(list(r) == list(QUESTION_COLUMNS) for r in rows)
    assert {r["repo"] for r in rows} == set(SIMPLE_REPOS)
    assert {r["kind"] for r in rows} == {"change", "explain"}

    overall = simple.data["tables"]["overall"]["arms"]
    for arm, entry in overall.items():
        mine = [r for r in rows if r["arm"] == arm]
        errors = [r for r in mine if r["status"] == "error"]
        assert len(errors) == entry["n_errors"], arm
        assert all(r["file_recall"] is None and r["error"] for r in errors), arm
        recalls = [r["file_recall"] for r in mine if r["file_recall"] is not None]
        if entry["recall"] is not None:
            assert entry["recall"]["n"] == len(recalls), arm
            mean = sum(recalls) / len(recalls)
            assert abs(entry["recall"]["mean"] - mean) < 1e-9, arm
        correct = [r["correctness"] for r in mine if r["correctness"] is not None]
        if entry["correctness"] is not None:
            assert abs(entry["correctness"]["mean"] - sum(correct) / len(correct)) < 1e-9, arm
