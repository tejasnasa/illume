"""The phrase, verify and split commands, without a model or a database."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from evals.cli.gold_commands import cmd_gold_phrase, cmd_gold_split, cmd_gold_verify
from evals.gold.schema import make_item, read_jsonl, write_jsonl
from evals.gold.split import read_lock

pytestmark = pytest.mark.unit

BASE = "f" * 40


def _items(n):
    return [
        make_item(
            repo="demo",
            base_commit=BASE,
            family="structural",
            template="structural.importers",
            question_seed=f"What breaks if `src/f{k}.py` changes?",
            gold_files=(f"src/g{k}.py",),
            circular_with=("graph",),
        )
        for k in range(n)
    ]


def test_phrase_fails_clearly_without_a_key(tmp_path, capsys):
    write_jsonl(tmp_path / "gold" / "demo" / "items.jsonl", _items(2))
    status = cmd_gold_phrase(
        out_dir=tmp_path, clones_dir=tmp_path / "clones", api_key="", repo_name="demo"
    )
    assert status == 1
    assert "OPENAI_API_KEY" in capsys.readouterr().err
    assert not (tmp_path / "gold" / "demo" / "items.phrased.jsonl").exists()


def test_split_writes_the_lock_and_slices_for_every_repository(tmp_path):
    write_jsonl(tmp_path / "gold" / "demo" / "items.jsonl", _items(20))
    assert cmd_gold_split(out_dir=tmp_path, repo_name=None, all_repos=True, pilot=False) == 0
    lock = read_lock(tmp_path / "gold" / "split.lock.json")
    assert lock["counts"] == {"test": 16, "tuning": 4}
    assert len(read_jsonl(tmp_path / "gold" / "test.jsonl")) == 16


def test_pilot_split_has_one_slice(tmp_path):
    write_jsonl(tmp_path / "gold" / "demo" / "items.jsonl", _items(5))
    assert cmd_gold_split(out_dir=tmp_path, repo_name="demo", all_repos=False, pilot=True) == 0
    lock = read_lock(tmp_path / "gold" / "split.lock.json")
    assert lock["frozen_slice"] == "pilot" and lock["counts"] == {"pilot": 5}


def _corpus(tmp_path):
    path = tmp_path / "corpus.yaml"
    lines = [
        "repos:",
        "  - name: demo",
        "    url: https://github.com/octo/demo",
        "    language: Python",
        "    licence: MIT",
        f'    base_commit: "{BASE}"',
    ]
    path.write_text(os.linesep.join(lines) + os.linesep)
    return path


def test_verify_labels_then_reports_and_writes_the_verified_items(tmp_path, capsys):
    items = _items(3)
    write_jsonl(tmp_path / "gold" / "demo" / "items.jsonl", items)
    answers = iter(["c", "w bad", "a"])
    status = cmd_gold_verify(
        out_dir=tmp_path,
        repo_name="demo",
        annotator=None,
        report=False,
        corpus_path=_corpus(tmp_path),
        input_fn=lambda _: next(answers),
        print_fn=lambda text: None,
    )
    assert status == 0
    assert cmd_gold_verify(out_dir=tmp_path, repo_name="demo", annotator=None, report=True) == 0
    assert "structural" in capsys.readouterr().out
    verified = read_jsonl(tmp_path / "gold" / "demo" / "items.verified.jsonl")
    assert len(verified) == 1 and verified[0].verified == "correct"


def test_split_defaults_to_the_single_pilot_slice(tmp_path):
    write_jsonl(tmp_path / "gold" / "demo" / "items.jsonl", _items(5))
    assert cmd_gold_split(out_dir=tmp_path, repo_name="demo", all_repos=False) == 0
    lock = read_lock(tmp_path / "gold" / "split.lock.json")
    assert lock["frozen_slice"] == "pilot" and lock["counts"] == {"pilot": 5}


PARSE = """
import json, sys
from evals.__main__ import build_parser
args = build_parser().parse_args(sys.argv[1:])
print(json.dumps(vars(args), default=str))
"""


def _parse(*argv):
    """Parse command-line arguments in a fresh process, where the eval settings load first."""
    result = subprocess.run(
        [sys.executable, "-c", PARSE, *argv],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return json.loads(result.stdout.splitlines()[-1])


def test_the_command_line_defaults_to_the_lean_design():
    build = _parse("gold", "build", "--repo", "demo")
    for flag in (
        "include_anchor",
        "include_rationale",
        "include_structural",
        "include_unanswerable",
        "tuning_test_split",
    ):
        assert build[flag] is False
    assert _parse("run", "generate")["slice"] == "pilot"
    opted = _parse(
        "gold", "build", "--include-anchor", "--include-rationale", "--include-structural"
    )
    assert opted["include_anchor"] and opted["include_rationale"] and opted["include_structural"]
    assert _parse("gold", "split", "--tuning-test-split")["tuning_test_split"] is True


def test_check_takes_its_own_model_override_and_defaults_to_the_judge_model():
    default = _parse("gold", "check", "--repo", "demo")
    chosen = _parse("gold", "check", "--repo", "demo", "--checker-model", "m2")
    assert default["checker_model"] is None and chosen["checker_model"] == "m2"
