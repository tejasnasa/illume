"""``eval-ci``: the real adapters, two arms by three items, through the runner, key-free.

This is the harness's smoke test. It runs the product's retrieval and answering against the
seeded retrieval fixture with a scripted model and the fake embedder, drives them through
:func:`evals.run.generate.generate`, and checks the records that come out. Later stages (judge,
report) extend it. Find it by name: ``pytest tests/evals/test_eval_ci_end_to_end.py``.
"""

import dataclasses
import json
import time
from contextlib import asynccontextmanager

import pytest
import respx

from app.services.retrieval.citations import code_key
from evals.arms import get_arm, question_with_instruction
from evals.gold.schema import write_jsonl
from evals.report import build_report
from evals.run.adapters import run_single_shot
from evals.run.budget import Budget
from evals.run.endpoint import JudgeEndpoint
from evals.run.generate import GENERATIONS, STOPPED, SUMMARY, generate, read_generations
from evals.run.judge import (
    grades_by_generation,
    judge_all,
    judgments_path,
    read_judgments,
    select_for_judging,
)
from evals.run.metering import Meter
from tests.evals.judge_helpers import FakeJudge
from tests.evals.run_helpers import PlainModel, complete_table, make_gold_item
from tests.factories import make_user
from tests.fixtures.agent_run import say
from tests.fixtures.retrieval import (
    DEFAULT_SPEC,
    hash_vector,
    make_context,
    make_llm,
    render_symbol_chunk,
    seed_repo,
)

pytestmark = pytest.mark.integration

SECURITY = "app/auth/security.py"
VERIFY_SPEC = DEFAULT_SPEC.files[0].symbols[0]
VERIFY_KEY = code_key(SECURITY, VERIFY_SPEC.start_line, VERIFY_SPEC.end_line)
VERIFY_VECTOR = hash_vector(render_symbol_chunk(SECURITY, VERIFY_SPEC))
ANSWER = f"verify_password compares with bcrypt [{VERIFY_KEY}].\n\nFiles:\n- {SECURITY}"
QUESTIONS = [
    "how does verify_password check bcrypt checkpw",
    "where does verify_password call bcrypt checkpw",
    "which function compares a password with bcrypt",
]
ARMS = ["classic", "structural"]


@pytest.fixture
async def seeded(db_session):
    return await seed_repo(db_session, await make_user(db_session), DEFAULT_SPEC)


async def test_two_arms_by_three_items_produce_six_ok_records(db_session, seeded, tmp_path):
    items = [
        make_gold_item(question, question_seed=question, gold_files=(SECURITY,))
        for question in QUESTIONS
    ]
    mapping = {question_with_instruction(q): VERIFY_VECTOR for q in QUESTIONS}
    model = PlainModel([say(ANSWER) for _ in range(6)], cached_tokens=20)
    meter = Meter()

    @asynccontextmanager
    async def open_context():
        yield make_context(db_session, seeded.repo, mapping)

    async def executor(item, arm, repeat):
        return await run_single_shot(
            item,
            arm,
            ctx_factory=open_context,
            llm=dataclasses.replace(make_llm(), model=arm.model),
            meter=meter,
            client_factory=model.factory,
            repeat=repeat,
        )

    started = time.perf_counter()
    with respx.mock(assert_all_mocked=True, assert_all_called=False):  # no network at all
        result = await generate(
            items=items,
            arm_names=ARMS,
            run_dir=tmp_path / "run",
            executor=executor,
            budget=Budget(cap_usd=10.0, stop_usd=9.5),
            table=complete_table(),
            slice_name="tuning",
        )
    assert time.perf_counter() - started < 120

    records = read_generations(tmp_path / "run" / GENERATIONS)
    assert (result.ok, result.errors, result.stopped) == (6, 0, None)
    assert len(records) == 6 and all(r.status == "ok" for r in records)
    assert {(r.item_id, r.arm) for r in records} == {(i.id, a) for i in items for a in ARMS}
    assert len({r.record_key for r in records}) == 6
    for record in records:
        assert record.answer == ANSWER
        assert record.candidates and record.candidates[0].key == VERIFY_KEY
        assert record.usages and all(u.cached_input_tokens == 20 for u in record.usages)
        assert record.cost_usd is not None and record.cost_usd > 0
    structural = [r for r in records if r.arm == "structural"]
    assert structural and {e["channel"] for e in structural[0].channel_trace} >= {"dense", "graph"}
    assert len(model.requests) == 6

    run_dir = tmp_path / "run"
    summary = json.loads((run_dir / SUMMARY).read_text(encoding="utf-8"))
    assert summary["ok"] == 6 and set(summary["per_arm"]) == set(ARMS)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["arms"] == {a: get_arm(a).config_hash() for a in ARMS}
    assert not (run_dir / STOPPED).exists()


async def test_judging_the_generated_records_with_a_scripted_judge(db_session, seeded, tmp_path):
    items = [
        make_gold_item(question, question_seed=question, gold_files=(SECURITY,))
        for question in QUESTIONS
    ]
    mapping = {question_with_instruction(q): VERIFY_VECTOR for q in QUESTIONS}
    model = PlainModel([say(ANSWER) for _ in range(6)])

    @asynccontextmanager
    async def open_context():
        yield make_context(db_session, seeded.repo, mapping)

    async def executor(item, arm, repeat):
        return await run_single_shot(
            item,
            arm,
            ctx_factory=open_context,
            llm=dataclasses.replace(make_llm(), model=arm.model),
            meter=Meter(),
            client_factory=model.factory,
            repeat=repeat,
        )

    run_dir = tmp_path / "run"
    await generate(
        items=items,
        arm_names=ARMS,
        run_dir=run_dir,
        executor=executor,
        budget=Budget(cap_usd=10.0, stop_usd=9.5),
        table=complete_table(),
        slice_name="tuning",
    )
    generations = run_dir / GENERATIONS
    before = generations.read_bytes()
    pairs = select_for_judging(items, read_generations(generations), seed=0)
    judge_model = FakeJudge()
    judge = JudgeEndpoint("gpt-6-luna", api_key="test-key")

    with respx.mock(assert_all_mocked=True, assert_all_called=False):  # no network at all
        result = await judge_all(
            pairs,
            endpoint=judge,
            out_path=judgments_path(run_dir, judge),
            budget=Budget(cap_usd=10.0, stop_usd=9.5),
            table=complete_table(),
            client_factory=judge_model.factory,
            evidence_for=lambda gold: {VERIFY_KEY: "def verify_password(): ..."}.get,
        )

    stored = read_judgments(judgments_path(run_dir, judge))
    assert len(pairs) == 6 and (result.ok, result.errors) == (18, 0)  # three metrics each
    assert {j.generation_key for j in stored} == {p.generation.record_key for p in pairs}
    assert all(j.status == "ok" for j in stored)
    assert {g.correct for g in grades_by_generation(stored)} == {3}
    assert any("def verify_password" in text for text in judge_model.texts())
    assert generations.read_bytes() == before

    write_jsonl(run_dir / "gold.jsonl", items)
    started = time.perf_counter()
    report = build_report(
        run_dir,
        mode="pilot",
        out_dir=tmp_path / "report",
        n_boot=200,
        n_perm=200,
        n_boot_mean=100,
    )
    assert time.perf_counter() - started < 120
    assert (tmp_path / "report" / "report.md").read_text(encoding="utf-8").startswith("# Pilot")
    written = json.loads((tmp_path / "report" / "report.json").read_text(encoding="utf-8"))
    assert written["mode"] == "pilot" and written["scope"]["arms"] == ARMS
    assert {"judge_results", "limitations"} <= set(report.data["sections"])
    assert generations.read_bytes() == before
