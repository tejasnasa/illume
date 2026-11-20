"""``run judge``, ``judge-label`` and ``judge-agreement`` against a recorded run, key-free."""

import json
from datetime import UTC, datetime

import pytest

from evals.cli.judge_commands import (
    cmd_judge_agreement,
    cmd_judge_label,
    cmd_run_judge,
    judge_manifest_name,
)
from evals.cli.run_commands import run_dir_for
from evals.gold.schema import write_jsonl
from evals.run.judge import judgments_path, read_judgments
from evals.run.judge_validation import SHEET_NAME, read_sheet
from tests.evals.judge_helpers import endpoint, generation, item, verdict
from tests.evals.run_helpers import PlainModel, complete_table

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


@pytest.fixture
def recorded(tmp_path):
    out = tmp_path / "out"
    items = [item("hand", n) for n in range(4)] + [item("structural", 0)]
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


def test_judging_grades_the_selected_pairs_and_leaves_the_run_files_alone(recorded):
    out, run_dir, _ = recorded
    before = {
        name: (run_dir / name).read_bytes() for name in ("generations.jsonl", "manifest.json")
    }
    model = PlainModel([verdict(3, 2) for _ in range(8)])

    status = judge(out, model)

    stored = read_judgments(judgments_path(run_dir, endpoint()))
    assert status == 0 and len(stored) == 8 and len(model.requests) == 8  # hand only, 2 arms
    assert {j.family for j in stored} == {"hand"}
    assert before == {name: (run_dir / name).read_bytes() for name in before}
    manifest = json.loads((run_dir / judge_manifest_name(endpoint())).read_text(encoding="utf-8"))
    assert manifest["run"]["judge"]["model"] == "gpt-6-luna"
    assert manifest["run"]["judge"]["host"] == "openai"
    assert manifest["run"]["judge"]["judged_on"] == "2026-11-19"
    assert manifest["models"]["judge"] == "gpt-6-luna" and "k-test" not in json.dumps(manifest)
    sheet = read_sheet(run_dir / SHEET_NAME)
    assert len(sheet) == 8 and not any("rationale" in e.model_dump() for e in sheet)


def test_running_again_grades_nothing_and_a_second_judge_adds_its_own_file(recorded):
    out, run_dir, _ = recorded
    judge(out, PlainModel([verdict() for _ in range(8)]))
    free = "qwen/qwen4-max:free"
    table = complete_table(
        models={
            "gpt-6-luna": {"rates": {"input_cache_miss": 1, "input_cache_hit": 0, "output": 1}},
            free: {"rates": {"input_cache_miss": 0, "input_cache_hit": 0, "output": 0}},
        }
    )
    again = PlainModel([])

    assert judge(out, again) == 0 and again.requests == []
    other = endpoint(free, "https://api.example.org/v1")
    assert (
        judge(out, PlainModel([verdict(1, 1) for _ in range(8)]), endpoint=other, table=table) == 0
    )

    files = sorted(p.name for p in run_dir.glob("judgments.*.jsonl"))
    assert len(files) == 2


def test_a_judge_missing_its_key_or_a_price_refuses_before_any_call(recorded, capsys):
    out, _, _ = recorded
    model = PlainModel([])

    no_key = judge(out, model, endpoint=endpoint(api_key=""))
    no_price = judge(out, model, endpoint=endpoint("unlisted-model"))

    err = capsys.readouterr().err
    assert (no_key, no_price) == (1, 1) and model.requests == []
    assert "OPENAI_API_KEY" in err and "no entry" in err


def test_sample_only_draws_the_sheet_without_calling_a_judge(recorded):
    out, run_dir, _ = recorded
    judge(out, PlainModel([verdict() for _ in range(8)]))
    (run_dir / SHEET_NAME).unlink()
    silent = PlainModel([])

    status = judge(out, silent, sample_only=True, sample_size=4, per_family_min=2)

    assert status == 0 and silent.requests == []
    assert len(read_sheet(run_dir / SHEET_NAME)) == 4


def test_label_then_agreement_per_judge_and_between_judges(recorded, capsys):
    out, run_dir, _ = recorded
    judge(out, PlainModel([verdict(3, 3) for _ in range(8)]))
    replies = iter(["3 3"] * 8)

    status = cmd_judge_label(
        out_dir=out, run_name="r1", input_fn=lambda prompt: next(replies), print_fn=lambda t: None
    )
    report = cmd_judge_agreement(
        out_dir=out, run_name="r1", endpoint=endpoint(), resamples=50, minimum=8
    )

    printed = capsys.readouterr().out
    assert status == 0 and report == 0
    assert "against hand labels" in printed and "hand" in printed

    other = endpoint("m2", "https://api.example.org/v1")
    table = complete_table(
        models={
            "gpt-6-luna": {"rates": {"input_cache_miss": 1, "input_cache_hit": 0, "output": 1}},
            "m2": {"rates": {"input_cache_miss": 0, "input_cache_hit": 0, "output": 0}},
        }
    )
    judge(out, PlainModel([verdict(3, 3) for _ in range(8)]), endpoint=other, table=table)
    assert (
        cmd_judge_agreement(
            out_dir=out, run_name="r1", endpoint=endpoint(), compare=other, resamples=50, minimum=8
        )
        == 0
    )
    assert "gpt-6-luna@openai against m2@api.example.org" in capsys.readouterr().out


def test_missing_run_and_empty_label_sheet_are_reported(tmp_path, capsys):
    assert judge(tmp_path, PlainModel([])) == 1
    assert cmd_judge_label(out_dir=tmp_path, run_name="nope") == 1
    assert "run judge" in capsys.readouterr().err
