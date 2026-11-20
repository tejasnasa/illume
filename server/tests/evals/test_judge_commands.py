"""``run judge``, ``judge-label`` and ``judge-agreement`` against a recorded run, key-free."""

import json
from datetime import UTC, datetime

import pytest

from evals.cli.judge_commands import (
    DEFAULT_SAMPLE_SIZE,
    cmd_judge_agreement,
    cmd_judge_label,
    cmd_run_judge,
    judge_manifest_name,
)
from evals.cli.run_commands import run_dir_for
from evals.gold.schema import write_jsonl
from evals.run.deepeval_env import deepeval_version
from evals.run.judge import judgments_path, read_judgments
from evals.run.judge_validation import SHEET_NAME, read_sheet
from tests.evals.judge_helpers import FakeJudge, endpoint, generation, item
from tests.evals.run_helpers import complete_table

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
PAIRS = 8  # four hand items by two arms
CALLS = PAIRS * 6  # six model calls to grade one answer on all three metrics


@pytest.fixture
def recorded(tmp_path):
    out = tmp_path / "out"
    items = [item("hand", n) for n in range(4)] + [item("hand", 9, tags=("unanswerable",))]
    write_jsonl(out / "gold" / "tuning.jsonl", items)
    run_dir = run_dir_for(out, "r1")
    run_dir.mkdir(parents=True)
    records = [generation(i, arm) for i in items for arm in ("classic", "hybrid")]
    generations = run_dir / "generations.jsonl"
    generations.write_text("".join(r.model_dump_json() + "\n" for r in records), encoding="utf-8")
    manifest = {"run": {"slice": "tuning"}, "arms": {"classic": "h"}, "models": {"generator": "g"}}
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return out, run_dir, items


def judge(out, model, **kw):
    fields = {
        "out_dir": out,
        "run_name": "r1",
        "endpoint": endpoint(),
        "budget_usd": 10.0,
        "stop_usd": 9.5,
        "table": complete_table(),
        "client_factory": model.factory,
        "evidence_for": lambda gold: {}.get,
        "concurrency": 1,
        "clock": lambda: NOW,
    }
    fields.update(kw)
    return cmd_run_judge(**fields)


def test_judging_grades_every_answer_but_the_unanswerable_and_leaves_the_run_files_alone(recorded):
    out, run_dir, _ = recorded
    before = {
        name: (run_dir / name).read_bytes() for name in ("generations.jsonl", "manifest.json")
    }
    model = FakeJudge()

    status = judge(out, model)

    stored = read_judgments(judgments_path(run_dir, endpoint()))
    assert status == 0 and len(stored) == PAIRS * 3 and model.calls == CALLS
    assert {j.family for j in stored} == {"hand"}
    assert {j.metric for j in stored} == {"correctness", "faithfulness", "answer_relevancy"}
    assert before == {name: (run_dir / name).read_bytes() for name in before}
    manifest = json.loads((run_dir / judge_manifest_name(endpoint())).read_text(encoding="utf-8"))
    recorded_judge = manifest["run"]["judge"]
    assert recorded_judge["model"] == "gpt-6-luna" and recorded_judge["host"] == "openai"
    assert recorded_judge["judged_on"] == "2026-11-19"
    assert recorded_judge["deepeval_version"] == deepeval_version()
    metrics = recorded_judge["metrics"]
    assert set(metrics) == {"correctness", "faithfulness", "answer_relevancy"}
    assert metrics["faithfulness"]["settings"]["penalize_ambiguous_claims"] is True
    assert metrics["faithfulness"]["settings"]["include_reason"] is False
    assert metrics["correctness"]["settings_hash"] and len(
        metrics["correctness"]["settings"]["evaluation_steps"]
    )
    assert manifest["models"]["judge"] == "gpt-6-luna" and "k-test" not in json.dumps(manifest)
    sheet = read_sheet(run_dir / SHEET_NAME)
    assert DEFAULT_SAMPLE_SIZE == 30 and len(sheet) == PAIRS


def test_unanswerable_items_are_judged_only_when_asked(recorded):
    out, run_dir, _ = recorded

    judge(out, FakeJudge(), include_unanswerable=True)

    stored = read_judgments(judgments_path(run_dir, endpoint()))
    assert len(stored) == (PAIRS + 2) * 3


def test_running_again_judges_nothing_and_a_second_judge_adds_its_own_file(recorded):
    out, run_dir, _ = recorded
    judge(out, FakeJudge())
    free = "qwen/qwen4-max:free"
    table = complete_table(
        models={
            "gpt-6-luna": {"rates": {"input_cache_miss": 1, "input_cache_hit": 0, "output": 1}},
            free: {"rates": {"input_cache_miss": 0, "input_cache_hit": 0, "output": 0}},
        }
    )
    again = FakeJudge()

    assert judge(out, again) == 0 and again.requests == []
    other = endpoint(free, "https://api.example.org/v1")
    assert judge(out, FakeJudge(), endpoint=other, table=table) == 0

    files = sorted(p.name for p in run_dir.glob("judgments.*.jsonl"))
    assert len(files) == 2


def test_a_failed_metric_makes_the_command_report_failure_and_the_next_run_retries_it(
    recorded, capsys
):
    out, run_dir, _ = recorded

    status = judge(out, FakeJudge({"ReasonScore": "no score"}))

    assert status == 1 and "retries them" in capsys.readouterr().out
    retry = FakeJudge()
    assert judge(out, retry) == 0
    assert set(retry.names()) == {"ReasonScore"} and retry.calls == PAIRS


def test_a_judge_missing_its_key_or_a_price_refuses_before_any_call(recorded, capsys):
    out, _, _ = recorded
    model = FakeJudge()

    no_key = judge(out, model, endpoint=endpoint(api_key=""))
    no_price = judge(out, model, endpoint=endpoint("unlisted-model"))

    err = capsys.readouterr().err
    assert (no_key, no_price) == (1, 1) and model.requests == []
    assert "OPENAI_API_KEY" in err and "no entry" in err


def test_sample_only_draws_the_sheet_without_calling_a_judge(recorded):
    out, run_dir, _ = recorded
    judge(out, FakeJudge())
    (run_dir / SHEET_NAME).unlink()
    silent = FakeJudge()

    status = judge(out, silent, sample_only=True, sample_size=4)

    assert status == 0 and silent.requests == []
    assert len(read_sheet(run_dir / SHEET_NAME)) == 4


def test_label_then_agreement_per_judge_and_between_judges(recorded, capsys):
    out, run_dir, _ = recorded
    judge(out, FakeJudge())
    replies = iter(["c n"] * PAIRS)

    status = cmd_judge_label(
        out_dir=out, run_name="r1", input_fn=lambda prompt: next(replies), print_fn=lambda t: None
    )
    report = cmd_judge_agreement(
        out_dir=out, run_name="r1", endpoint=endpoint(), resamples=50, minimum=8
    )

    printed = capsys.readouterr().out
    assert status == 0 and report == 0
    assert "against hand labels" in printed and "hand" in printed and "made_up" in printed

    other = endpoint("m2", "https://api.example.org/v1")
    table = complete_table(
        models={
            "gpt-6-luna": {"rates": {"input_cache_miss": 1, "input_cache_hit": 0, "output": 1}},
            "m2": {"rates": {"input_cache_miss": 0, "input_cache_hit": 0, "output": 0}},
        }
    )
    judge(out, FakeJudge(), endpoint=other, table=table)
    assert (
        cmd_judge_agreement(
            out_dir=out, run_name="r1", endpoint=endpoint(), compare=other, resamples=50, minimum=8
        )
        == 0
    )
    assert "gpt-6-luna@openai against m2@api.example.org" in capsys.readouterr().out


def test_missing_run_and_empty_label_sheet_are_reported(tmp_path, capsys):
    assert judge(tmp_path, FakeJudge()) == 1
    assert cmd_judge_label(out_dir=tmp_path, run_name="nope") == 1
    assert "run judge" in capsys.readouterr().err
