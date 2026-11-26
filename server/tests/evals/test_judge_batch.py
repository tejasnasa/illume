"""Judging through the batch API in rounds, against a scripted batch service, key-free."""

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

from evals.cli.judge_commands import WAITING, cmd_run_judge
from evals.cli.run_commands import run_dir_for
from evals.gold.schema import write_jsonl
from evals.run.judge import judgments_path, read_judgments
from evals.run.judge_batch import (
    MAX_ATTEMPTS,
    BatchApi,
    BatchApiError,
    InFlight,
    Reply,
    ReplyStore,
    batch_dir,
    is_batch_model,
    plain_slug,
    request_key,
    stored_spend,
)
from tests.evals.judge_helpers import CITED, FakeJudge, _schema_name, endpoint, generation, item
from tests.evals.run_helpers import complete_table

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
OPENROUTER = "https://openrouter.ai/api/v1"
ITEMS = 4


def batch_endpoint(model: str = "gpt-6-luna:batch"):
    return endpoint(model, base_url=OPENROUTER, api_style="chat")


class FakeBatches:
    """A batch service that answers every request from a scripted judge once it is finished.

    Args:
        judge: Answers each request body.
        finish: Whether a submitted batch is finished the first time it is asked about.
        fail: Custom ids to answer with an error, every time.
        refuse: Raise from ``submit`` with this status code.
    """

    def __init__(
        self,
        judge: FakeJudge,
        *,
        finish: bool = True,
        fail: set[str] | None = None,
        refuse: int | None = None,
    ) -> None:
        self.judge = judge
        self.finish = finish
        self.fail = fail or set()
        self.refuse = refuse
        self.batches: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        self.finished: set[str] = set()
        self.models: list[str] = []

    @property
    def requests(self) -> int:
        return sum(len(r) for r in self.batches.values())

    def submit(self, model, requests):
        if self.refuse is not None:
            raise BatchApiError("too many batches", self.refuse)
        batch_id = f"b{len(self.batches)}"
        self.batches[batch_id] = [(key, dict(body)) for key, body in requests]
        self.models.append(model)
        if self.finish:
            self.finished.add(batch_id)
        return {"id": batch_id, "status": "validating"}

    def status(self, batch_id):
        return {
            "id": batch_id,
            "status": "completed" if batch_id in self.finished else "in_progress",
        }

    def results(self, batch_id):
        for key, body in self.batches[batch_id]:
            if key in self.fail:
                yield {"custom_id": key, "response": None, "error": {"message": "overloaded"}}
                continue
            self.judge.requests.append(body)
            yield {
                "custom_id": key,
                "response": {
                    "status_code": 200,
                    "body": {
                        "model": "reported-batch-model",
                        "choices": [{"message": {"content": self.judge._reply(body)}}],
                        "usage": {"prompt_tokens": 1000, "completion_tokens": 50},
                    },
                },
                "error": None,
            }


@pytest.fixture
def recorded(tmp_path):
    out = tmp_path / "out"
    items = [item("hand", n) for n in range(ITEMS)]
    write_jsonl(out / "gold" / "tuning.jsonl", items)
    run_dir = run_dir_for(out, "r1")
    run_dir.mkdir(parents=True)
    records = [
        generation(i, arm, answer=f"Item {n} validates input [{CITED}].\n\nFiles:\n- x.py")
        for n, i in enumerate(items)
        for arm in ("classic", "hybrid")
    ]
    (run_dir / "generations.jsonl").write_text(
        "".join(r.model_dump_json() + "\n" for r in records), encoding="utf-8"
    )
    manifest = {"run": {"slice": "tuning"}, "arms": {"classic": "h"}, "models": {"generator": "g"}}
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return out, run_dir


def judge(out, **kw):
    fields: dict[str, Any] = {
        "out_dir": out,
        "run_name": "r1",
        "endpoint": batch_endpoint(),
        "budget_usd": 10.0,
        "stop_usd": 9.5,
        "table": complete_table(),
        "evidence_for": lambda gold: {}.get,
        "concurrency": 2,
        "clock": lambda: NOW,
        "sleep": lambda seconds: None,
    }
    fields.update(kw)
    return cmd_run_judge(**fields)


def scores(run_dir, chosen):
    return {
        (j.generation_key, j.metric): j.score
        for j in read_judgments(judgments_path(run_dir, chosen))
        if j.status == "ok"
    }


# --- whole runs ------------------------------------------------------------------------


def test_waiting_runs_rounds_until_every_metric_is_graded_with_the_live_judges_scores(recorded):
    out, run_dir = recorded
    batches = FakeBatches(FakeJudge())

    status = judge(out, batch_api=batches, wait=True)

    assert status == 0
    batch_scores = scores(run_dir, batch_endpoint())
    assert len(batch_scores) == ITEMS * 2 * 3
    live = FakeJudge()
    assert judge(out, endpoint=endpoint(api_style="chat"), client_factory=live.factory) == 0
    assert scores(run_dir, endpoint(api_style="chat")) == batch_scores
    # Each metric's chain needs more than one round, and the batch model is called by its plain id.
    assert len(batches.batches) > 1 and set(batches.models) == {"gpt-6-luna"}


def test_a_request_is_sent_once_however_many_answers_ask_it(recorded):
    out, run_dir = recorded
    batches = FakeBatches(FakeJudge())
    live = FakeJudge()

    judge(out, batch_api=batches, wait=True)
    judge(out, endpoint=endpoint(api_style="chat"), client_factory=live.factory)

    # Both arms gave the same answer to each question, so their requests are the same ones.
    distinct = {request_key(request) for request in live.requests}
    assert batches.requests == len(distinct) < live.calls
    graded = read_judgments(judgments_path(run_dir, batch_endpoint()))
    assert {j.arm for j in graded} == {"classic", "hybrid"}


def test_without_wait_each_call_takes_one_step_and_reports_that_work_is_out(recorded):
    out, run_dir = recorded
    batches = FakeBatches(FakeJudge(), finish=False)

    assert judge(out, batch_api=batches) == WAITING
    assert len(batches.batches) == 1 and not read_judgments(
        judgments_path(run_dir, batch_endpoint())
    )

    assert judge(out, batch_api=batches) == WAITING
    assert len(batches.batches) == 1  # nothing is sent twice while it is still running

    batches.finish = True
    batches.finished |= set(batches.batches)
    statuses = [judge(out, batch_api=batches) for _ in range(6)]
    assert statuses[-1] == 0 and WAITING in statuses
    assert len(scores(run_dir, batch_endpoint())) == ITEMS * 2 * 3


def test_the_spend_counts_each_paid_reply_once_and_a_judgment_carries_its_own_calls(recorded):
    out, run_dir = recorded
    judge(out, batch_api=FakeBatches(FakeJudge()), wait=True)
    graded = read_judgments(judgments_path(run_dir, batch_endpoint()))
    store = ReplyStore.open(batch_dir(run_dir, batch_endpoint()))

    # $1 in and $2 out per 1M tokens: 1000 in and 50 out cost $0.0011 a reply.
    spend = stored_spend(store, batch_endpoint(), complete_table())
    assert spend == pytest.approx(0.0011 * len(store.replies))
    # A judgment is priced as the calls it made, shared or not: five per answer here.
    assert sum(j.cost_usd or 0 for j in graded) == pytest.approx(0.0011 * ITEMS * 2 * 5)


def test_a_batch_that_would_pass_the_stop_is_not_sent(recorded):
    out, run_dir = recorded
    batches = FakeBatches(FakeJudge())

    status = judge(out, batch_api=batches, budget_usd=0.01, stop_usd=0.001, wait=True)

    assert status == 1 and not batches.batches
    assert not read_judgments(judgments_path(run_dir, batch_endpoint()))


def test_a_refused_submit_keeps_the_requests_for_the_next_step(recorded):
    out, _ = recorded
    batches = FakeBatches(FakeJudge(), refuse=429)

    assert judge(out, batch_api=batches) == 1
    batches.refuse = None
    assert judge(out, batch_api=batches, wait=True) == 0


def test_a_request_that_keeps_failing_is_sent_again_then_recorded_as_an_error(recorded):
    out, run_dir = recorded
    probe = FakeBatches(FakeJudge())
    judge(out, batch_api=probe, wait=True)
    first_claims = next(key for key, body in probe.batches["b0"] if _schema_name(body) == "Claims")
    for path in run_dir.glob("judgments.*"):
        path.unlink()
    for path in batch_dir(run_dir, batch_endpoint()).iterdir():
        path.unlink()
    batches = FakeBatches(FakeJudge(), fail={first_claims})

    status = judge(out, batch_api=batches, wait=True)

    sent = [key for requests in batches.batches.values() for key, _ in requests]
    assert sent.count(first_claims) == MAX_ATTEMPTS
    graded = read_judgments(judgments_path(run_dir, batch_endpoint()))
    errors = [j for j in graded if j.status == "error"]
    assert status == 1 and errors and all(j.metric == "faithfulness" for j in errors)
    assert "overloaded" in errors[0].error


def test_a_batch_judge_needs_chat_completions(recorded):
    out, _ = recorded
    chosen = endpoint("gpt-6-luna:batch", base_url=OPENROUTER, api_style="responses")

    assert judge(out, endpoint=chosen, batch_api=FakeBatches(FakeJudge())) == 2


# --- the pieces --------------------------------------------------------------------------


def test_the_batch_suffix_selects_the_path_and_is_dropped_for_the_api():
    assert is_batch_model("anthropic/claude-haiku-5.5:batch")
    assert not is_batch_model("anthropic/claude-haiku-5.5")
    assert plain_slug("anthropic/claude-haiku-5.5:batch") == "anthropic/claude-haiku-5.5"


def test_a_request_key_ignores_key_order():
    one = {"model": "m", "messages": [{"role": "user", "content": "x"}]}
    two = {"messages": [{"content": "x", "role": "user"}], "model": "m"}
    assert request_key(one) == request_key(two)
    assert request_key(one) != request_key({**one, "model": "n"})


def test_the_store_reads_back_its_replies_and_batches_with_the_last_reply_winning(tmp_path):
    store = ReplyStore.open(tmp_path / "b")
    store.add(Reply(key="a", error="busy"))
    store.add(Reply(key="a", body={"choices": []}, attempts=2))
    store.in_flight.append(InFlight(id="x", keys=["c"], submitted_at="t", estimate_usd=0.5))
    store.save_in_flight()

    again = ReplyStore.open(tmp_path / "b")

    assert again.replies["a"].ok and again.replies["a"].attempts == 2
    assert again.in_flight_keys() == {"c"}
    again.queue("c", {})
    assert not again.queued  # already in flight


def test_a_failed_reply_is_retried_until_the_last_attempt(tmp_path):
    store = ReplyStore.open(tmp_path / "b")
    store.add(Reply(key="a", error="busy", attempts=1))
    assert store.lookup("a") is None
    store.add(Reply(key="a", error="busy", attempts=MAX_ATTEMPTS))
    assert store.lookup("a") is not None


@respx.mock
def test_the_api_puts_the_batch_fields_before_the_requests_and_pages_through_results():
    submit = respx.post(f"{OPENROUTER}/batches").mock(
        return_value=httpx.Response(202, json={"id": "b1", "status": "validating"})
    )
    respx.get(f"{OPENROUTER}/batches/b1/results").mock(
        side_effect=[
            httpx.Response(
                200, json={"data": [{"custom_id": "a"}], "has_more": True, "next_cursor": "c2"}
            ),
            httpx.Response(
                200, json={"data": [{"custom_id": "b"}], "has_more": False, "next_cursor": None}
            ),
        ]
    )
    api = BatchApi(batch_endpoint())

    created = api.submit("gpt-6-luna", [("a", {"messages": []})])
    entries = list(api.results("b1"))

    sent = submit.calls[0].request
    assert created["id"] == "b1" and [e["custom_id"] for e in entries] == ["a", "b"]
    assert list(json.loads(sent.content)) == ["endpoint", "model", "completion_window", "requests"]
    assert sent.headers["authorization"] == "Bearer k-test"


@respx.mock
def test_an_api_error_carries_the_status_and_message_but_not_the_key():
    respx.post(f"{OPENROUTER}/batches").mock(
        return_value=httpx.Response(429, json={"error": {"message": "slow down"}})
    )

    with pytest.raises(BatchApiError) as raised:
        BatchApi(batch_endpoint()).submit("m", [("a", {})])

    assert raised.value.status_code == 429 and "slow down" in str(raised.value)
    assert "k-test" not in str(raised.value)


def test_a_composed_answer_waits_for_its_target_and_takes_a_copy_of_its_grade(recorded):
    out, run_dir = recorded
    gold = [item("hand", n) for n in range(ITEMS)]
    target = generation(gold[0], "classic", answer="Item 0 answer.\n\nFiles:\n- x.py")
    composed = generation(
        gold[0], "auto", composed_from="classic", answer="Item 0 answer.\n\nFiles:\n- x.py"
    )
    (run_dir / "generations.jsonl").write_text(
        target.model_dump_json() + "\n" + composed.model_dump_json() + "\n", encoding="utf-8"
    )
    batches = FakeBatches(FakeJudge())

    assert judge(out, batch_api=batches, wait=True) == 0

    graded = read_judgments(judgments_path(run_dir, batch_endpoint()))
    copies = [j for j in graded if j.arm == "auto"]
    assert len(copies) == 3 and all(j.reused_from and j.cost_usd == 0 for j in copies)
    assert batches.requests == 5
