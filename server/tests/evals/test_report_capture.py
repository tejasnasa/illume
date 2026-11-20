"""Capturing the report's context into a run directory, and loading it back."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.models import Repository, User
from evals.cli.run_commands import cmd_run_generate
from evals.gold.schema import write_jsonl
from evals.gold.verify import Label, append_label
from evals.report.capture import capture_run_context
from evals.report.load import load_run
from evals.run.generate import GENERATIONS
from tests.evals.run_helpers import flat_table, make_gold_item, make_items
from tests.evals.test_run_commands import RecordingRuntime

pytestmark = pytest.mark.integration


def test_capture_writes_the_context_files_and_the_loader_reads_them(ingest, db, history, tmp_path):
    result = ingest()
    corpus = tmp_path / "corpus.yaml"
    corpus.write_text(
        "repos:\n  - name: sample\n    url: x\n    language: Python\n    licence: MIT\n"
        f'    base_commit: "{history.base}"\n',
        encoding="utf-8",
    )
    email = db.execute(
        select(User.email)
        .join(Repository, Repository.user_id == User.id)
        .where(Repository.id == result.repo_id)
    ).scalar_one()
    item = make_gold_item(repo="sample", gold_files=("src/app.py",))
    out = tmp_path / "out"
    labels = out / "gold" / "sample" / "labels.jsonl"
    append_label(labels, Label(item_id=item.id, label="wrong"))
    run_dir = out / "runs" / "r1"

    missing = capture_run_context(
        db, run_dir=run_dir, items=[item], out_dir=out, user_email=email, corpus_path=corpus
    )

    assert missing == []
    counts = json.loads((run_dir / "corpus_counts.json").read_text(encoding="utf-8"))
    assert counts["sample"]["files"] > 0 and counts["sample"]["language"] == "Python"
    files = json.loads((run_dir / "files_at_base.json").read_text(encoding="utf-8"))
    assert files["sample"] and files["sample"] == sorted(files["sample"])
    graph = json.loads((run_dir / "graph.json").read_text(encoding="utf-8"))
    assert set(graph["sample"]) <= set(files["sample"])

    (run_dir / GENERATIONS).write_text(
        json.dumps(
            {
                "record_key": "k",
                "item_id": item.id,
                "arm": "classic",
                "config_hash": "h",
                "model": "m",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    data = load_run(run_dir)
    assert set(data.items) == {item.id}
    assert [label.label for label in data.gold_labels] == ["wrong"]
    assert data.files_at_base["sample"] == files["sample"]
    assert "no gold items found" not in data.notes


def test_an_unknown_repository_is_reported_not_raised(db, tmp_path):
    item = make_gold_item(repo="never-ingested")
    missing = capture_run_context(
        db,
        run_dir=tmp_path / "run",
        items=[item],
        out_dir=tmp_path,
        user_email="nobody@example.com",
    )
    assert missing == ["never-ingested"]
    assert (tmp_path / "run" / "gold.jsonl").is_file()


def test_generate_captures_the_context_after_the_pass(tmp_path):
    out = tmp_path / "out"
    items = make_items(2)
    write_jsonl(out / "gold" / "tuning.jsonl", items)
    seen = []

    code = cmd_run_generate(
        out_dir=out,
        slice_name="tuning",
        arms_spec="classic",
        run_name="r1",
        budget_usd=10.0,
        stop_usd=9.5,
        table=flat_table(),
        runtime=RecordingRuntime(),
        concurrency=1,
        min_intervals={},
        capture=lambda run_dir, captured: seen.append((run_dir, [i.id for i in captured])),
    )

    assert code == 0
    assert seen == [(out / "runs" / "r1", [i.id for i in items])]
