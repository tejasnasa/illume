"""The judge pass: selection, the prompt, grading, errors, re-judging and the two transports."""

import asyncio
import json
from datetime import UTC, datetime

import pytest

from evals.arms import ARMS
from evals.run import judge as judge_module
from evals.run.budget import Budget
from evals.run.endpoint import JudgeEndpoint
from evals.run.judge import (
    JudgePair,
    judge_all,
    judge_prompt,
    judgments_path,
    parse_verdict,
    read_judgments,
    select_for_judging,
)
from evals.run.records import CandidateRecord, Judgment
from tests.evals.judge_helpers import (
    CITED,
    ChatReply,
    endpoint,
    generation,
    item,
    verdict,
    verdict_json,
)
from tests.evals.run_helpers import PlainModel, complete_table
from tests.fixtures.agent_run import Turn, say

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
FREE = "qwen/qwen4-max:free"


def free_table():
    return complete_table(
        models={
            "gpt-6-luna": {"rates": {"input_cache_miss": 1, "input_cache_hit": 0, "output": 1}},
            FREE: {"rates": {"input_cache_miss": 0, "input_cache_hit": 0, "output": 0}},
        }
    )


def run_with(pairs, chosen, factory, tmp_path, *, clock=lambda: NOW, **kw):
    path = judgments_path(tmp_path, chosen)
    result = asyncio.run(
        judge_all(
            pairs,
            endpoint=chosen,
            out_path=path,
            budget=kw.pop("budget", Budget(cap_usd=10, stop_usd=9.5)),
            table=kw.pop("table", complete_table()),
            client_factory=factory,
            clock=clock,
            **kw,
        )
    )
    return result, path


def run(pairs, model, tmp_path, *, judge=None, **kw):
    return run_with(pairs, judge or endpoint(), model.factory, tmp_path, **kw)


def pair(family="hand", n=0, arm="classic", **kw):
    gold = item(family, n)
    return JudgePair(gold, generation(gold, arm, **kw))


def leaves(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from leaves(child)
    elif isinstance(value, list):
        for child in value:
            yield from leaves(child)
    else:
        yield value


class TestSelection:
    def make(self):
        items = [item("rationale", n) for n in range(3)]
        items += [item("hand", n) for n in range(2)]
        items += [item("structural", n) for n in range(3)]
        items += [item("changeset", n) for n in range(20)]
        return items, [generation(i) for i in items]

    def test_every_rationale_and_hand_item_and_a_cluster_sample_of_changesets(self):
        items, gens = self.make()

        chosen = select_for_judging(items, gens, seed=1)

        families = [p.item.family for p in chosen]
        assert families.count("rationale") == 3 and families.count("hand") == 2
        assert "structural" not in families
        changesets = [p.item for p in chosen if p.item.family == "changeset"]
        clusters = {i.cluster for i in changesets}
        assert len(clusters) == 2  # 10 clusters, 20%
        members = [i for i in items if i.family == "changeset" and i.cluster in clusters]
        assert len(changesets) == len(members) == 4  # both variants of each pull request

    def test_selection_is_deterministic_and_independent_of_order(self):
        items, gens = self.make()

        first = select_for_judging(items, gens, seed=7)
        second = select_for_judging(list(reversed(items)), list(reversed(gens)), seed=7)

        assert [p.generation.record_key for p in first] == [p.generation.record_key for p in second]

    def test_adding_an_arm_does_not_change_which_questions_are_chosen(self):
        items, gens = self.make()
        more = gens + [generation(i, "hybrid") for i in items]

        before = {p.item.id for p in select_for_judging(items, gens, seed=3)}
        after = {p.item.id for p in select_for_judging(items, more, seed=3)}

        assert before == after

    def test_error_generations_and_superseded_records_are_skipped(self):
        gold = item("hand", 0)
        failed = generation(gold, "classic", status="error")
        old = generation(gold, "hybrid", key="k", status="error")
        new = generation(gold, "hybrid", key="k")

        chosen = select_for_judging([gold], [failed, old, new], seed=0)

        assert [p.generation.arm for p in chosen] == ["hybrid"]


class TestPrompt:
    def test_it_carries_the_task_and_never_the_arm(self):
        gold = item("hand", 0, acceptable_files=("app/other.py",), question="How is input checked?")
        for arm in ARMS.values():
            prompt = judge_prompt(
                gold, generation(gold, arm), evidence_text={CITED: "def check(): ..."}.get
            )
            text = prompt.text.lower()
            assert "how is input checked?" in text and "feature 0 validates input" in text
            assert "app/hand0.py" in text and "app/other.py" in text
            assert "def check(): ..." in prompt.user
            assert arm.name.lower() not in text, arm.name
            assert arm.config_hash() not in text and arm.model.lower() not in text
            if arm.config is not None:
                dumped = arm.config.model_dump(mode="json")
                strings = {v for v in leaves(dumped) if isinstance(v, str) and len(v) > 3}
                assert not {s for s in strings if s.lower() in text}, arm.name

    def test_an_unanswerable_item_says_declining_is_correct(self):
        gold = item("hand", 1, gold_files=(), tags=("unanswerable",))

        prompt = judge_prompt(gold, generation(gold))

        assert "declining to answer is the correct response" in prompt.user
        assert "abstaining is the correct answer" in prompt.system

    def test_evidence_is_truncated_to_a_fixed_budget_and_unknown_keys_are_marked(self):
        gold = item("hand", 2)
        keys = [f"F:app/f{n}.py:1-9" for n in range(4)]
        gen = generation(
            gold,
            answer=" ".join(f"[{k}]" for k in [*keys, "F:app/never.py:1-2"]),
            candidates=[
                CandidateRecord(key=k, rank=i, source_type="symbol") for i, k in enumerate(keys)
            ],
        )
        big = "x" * 50_000

        prompt = judge_prompt(gold, gen, evidence_text=lambda key: big if "f0" in key else None)

        assert len(prompt.user) < judge_module.EVIDENCE_CHAR_BUDGET + 3000
        assert "(truncated)" in prompt.user
        assert judge_module.UNAVAILABLE in prompt.user
        assert judge_module.UNMATCHED in prompt.user

    def test_an_answer_that_cites_nothing_says_so(self):
        gold = item("hand", 3)

        prompt = judge_prompt(gold, generation(gold, answer="No citations.", cited_keys=[]))

        assert judge_module.NO_EVIDENCE in prompt.user


class TestParsing:
    def test_valid_fenced_and_wrapped_outputs_are_accepted(self):
        plain = parse_verdict(verdict_json(3, 1, True))
        fenced = parse_verdict("```json\n" + verdict_json(2, 2) + "\n```")
        wrapped = parse_verdict("Here you go: " + verdict_json(1, 0) + " done")

        assert (plain.correct, plain.faithful, plain.abstained) == (3, 1, True)
        assert (fenced.correct, wrapped.correct) == (2, 1)

    @pytest.mark.parametrize(
        "text",
        [
            "not json at all",
            verdict_json(7, 1),
            verdict_json(-1, 1),
            json.dumps({"correct": 1, "faithful": 1, "rationale": "x"}),
            json.dumps({"correct": "2", "faithful": 1, "abstained": False, "rationale": "x"}),
            json.dumps({"correct": 1.5, "faithful": 1, "abstained": False, "rationale": "x"}),
            json.dumps({"correct": 1, "faithful": 1, "abstained": "no", "rationale": "x"}),
            "[1, 2]",
            "",
        ],
    )
    def test_unusable_output_is_rejected(self, text):
        with pytest.raises(judge_module.JudgeOutputError):
            parse_verdict(text)


class TestGrading:
    def test_a_valid_judgment_is_stored_with_cost_and_identity(self, tmp_path):
        model = PlainModel([verdict(3, 2)])
        p = pair()

        result, path = run([p], model, tmp_path)

        [stored] = read_judgments(path)
        assert (result.ok, result.errors) == (1, 0)
        assert stored.status == "ok" and (stored.correct, stored.faithful) == (3, 2)
        assert stored.generation_key == p.generation.record_key and stored.arm == "classic"
        assert stored.judge.model == "gpt-6-luna" and stored.judge.host == "openai"
        assert stored.judge.prompt_version == judge_module.JUDGE_VERSION
        assert stored.judge.judged_on == "2026-11-19"
        assert stored.usages[0].kind == "judge" and stored.cost_usd and stored.cost_usd > 0
        assert result.spent_usd == pytest.approx(stored.cost_usd)

    def test_the_request_is_structured_and_carries_no_arm(self, tmp_path):
        model = PlainModel([verdict()])

        run([pair(arm="structural_rerank")], model, tmp_path)

        [request] = model.requests
        schema = request["text"]["format"]
        assert schema["type"] == "json_schema" and schema["strict"] is True
        assert request["model"] == "gpt-6-luna"
        assert "structural_rerank" not in json.dumps(request["input"])

    @pytest.mark.parametrize(
        "reply",
        ["this is not json", verdict_json(7, 1), json.dumps({"correct": 1, "faithful": 1})],
    )
    def test_malformed_output_is_a_judge_error_retried_next_run(self, tmp_path, reply):
        p = pair()
        model = PlainModel([say(reply), verdict(2, 2)])

        first, path = run([p], model, tmp_path)
        [bad] = read_judgments(path)
        second, _ = run([p], model, tmp_path)

        assert (first.ok, first.errors) == (0, 1)
        assert bad.status == "error" and bad.raw == reply and bad.correct is None
        assert "unusable" in (bad.error or "")
        assert (second.ok, second.skipped) == (1, 0)
        latest = {j.judgment_key: j for j in read_judgments(path)}
        assert [j.status for j in latest.values()] == ["ok"]

    def test_a_finished_pair_is_not_graded_again_even_on_another_day(self, tmp_path):
        p = pair()
        model = PlainModel([verdict()])
        run([p], model, tmp_path, clock=lambda: NOW)

        again, _ = run([p], model, tmp_path, clock=lambda: LATER)

        assert (again.skipped, again.ok) == (1, 0) and len(model.requests) == 1

    def test_bumping_the_judge_version_grades_again_and_leaves_generations_alone(
        self, tmp_path, monkeypatch
    ):
        p = pair()
        generations = tmp_path / "generations.jsonl"
        generations.write_bytes(p.generation.model_dump_json().encode() + b"\n")
        before = generations.read_bytes()
        model = PlainModel([verdict(), verdict(1, 1)])
        run([p], model, tmp_path)

        monkeypatch.setattr(judge_module, "JUDGE_VERSION", "2")
        result, path = run([p], model, tmp_path)

        stored = read_judgments(path)
        assert result.ok == 1 and len(stored) == 2
        assert {j.judge.prompt_version for j in stored} == {"1", "2"}
        assert len({j.judgment_key for j in stored}) == 2
        assert generations.read_bytes() == before

    def test_a_provider_failure_is_an_error_record_not_a_crash(self, tmp_path):
        model = PlainModel([Turn(error=RuntimeError("provider down"))])

        result, path = run([pair()], model, tmp_path)

        [stored] = read_judgments(path)
        assert result.errors == 1 and "provider down" in (stored.error or "")

    def test_the_run_stops_cleanly_at_the_stop_threshold(self, tmp_path):
        pairs = [pair(n=n) for n in range(3)]
        model = PlainModel([verdict() for _ in range(3)])
        budget = Budget(cap_usd=1.0, stop_usd=0.0001)
        table = complete_table(
            models={
                "gpt-6-luna": {
                    "rates": {"input_cache_miss": 1000.0, "input_cache_hit": 0, "output": 1000.0}
                }
            }
        )

        result, path = run(pairs, model, tmp_path, budget=budget, table=table)

        assert result.ok == 1 and result.stopped and "stop" in result.stopped
        assert len(read_judgments(path)) == 1

    def test_an_unpriced_judge_model_stops_the_run(self, tmp_path):
        model = PlainModel([verdict(), verdict()])

        result, _ = run([pair(n=0), pair(n=1)], model, tmp_path, judge=endpoint("no-price-model"))

        assert result.stopped and "no price" in result.stopped and result.ok == 1


class TestComposedRecords:
    def test_an_identical_composed_answer_reuses_its_targets_grade(self, tmp_path):
        gold = item("hand", 0)
        target = generation(gold, "structural", key="t")
        auto = generation(gold, "auto", key="a").model_copy(update={"composed_from": "structural"})
        model = PlainModel([verdict(2, 3)])

        result, path = run([JudgePair(gold, target), JudgePair(gold, auto)], model, tmp_path)

        by_arm = {j.arm: j for j in read_judgments(path)}
        assert (result.ok, result.reused) == (1, 1) and len(model.requests) == 1
        assert by_arm["auto"].reused_from == by_arm["structural"].judgment_key
        assert by_arm["auto"].generation_key == "a" and by_arm["auto"].cost_usd == 0
        assert (by_arm["auto"].correct, by_arm["auto"].faithful) == (2, 3)

    def test_a_composed_answer_that_differs_is_graded_itself(self, tmp_path):
        gold = item("hand", 0)
        target = generation(gold, "structural", key="t")
        auto = generation(gold, "auto", key="a", answer="different").model_copy(
            update={"composed_from": "structural"}
        )
        model = PlainModel([verdict(), verdict()])

        result, _ = run([JudgePair(gold, target), JudgePair(gold, auto)], model, tmp_path)

        assert (result.ok, result.reused) == (2, 0)


class TestTransports:
    def test_chat_completions_ask_for_json_and_parse_it(self, tmp_path):
        chat = ChatReply([verdict_json(3, 3)])
        chosen = endpoint(FREE, "https://openrouter.ai/api/v1", api_style="chat")

        result, path = run_with([pair()], chosen, chat.factory, tmp_path, table=free_table())

        [stored] = read_judgments(path)
        [request] = chat.requests
        assert result.ok == 1 and (stored.correct, stored.faithful) == (3, 3)
        assert request["response_format"] == {"type": "json_object"}
        assert "JSON schema" in request["messages"][0]["content"]
        assert stored.judge.host == "openrouter.ai" and stored.judge.api_style == "chat"
        assert stored.cost_usd == 0 and stored.usages[0].input_tokens == 1000
        assert stored.reported_model == "reported-chat-model"
        assert chat.client_kwargs["base_url"] == "https://openrouter.ai/api/v1"

    def test_fenced_json_from_a_chat_model_is_accepted(self, tmp_path):
        chat = ChatReply(["```json\n" + verdict_json(2, 1) + "\n```"])

        result, path = run_with([pair()], endpoint(api_style="chat"), chat.factory, tmp_path)

        assert result.ok == 1 and read_judgments(path)[0].correct == 2

    def test_malformed_chat_output_is_a_judge_error(self, tmp_path):
        chat = ChatReply(["I think it is good."])

        result, path = run_with([pair()], endpoint(api_style="chat"), chat.factory, tmp_path)

        [stored] = read_judgments(path)
        assert result.errors == 1 and stored.status == "error"
        assert stored.raw == "I think it is good." and stored.correct is None

    def test_a_provider_that_rejects_json_mode_is_asked_again_without_it(self, tmp_path):
        chat = ChatReply([verdict_json()], reject_json_mode=True)

        result, _ = run_with([pair()], endpoint(api_style="chat"), chat.factory, tmp_path)

        assert result.ok == 1
        assert ["response_format" in r for r in chat.requests] == [True, False]


class TestTwoJudges:
    def test_each_judge_has_its_own_file_and_generations_stay_byte_identical(self, tmp_path):
        p = pair()
        generations = tmp_path / "generations.jsonl"
        generations.write_bytes(p.generation.model_dump_json().encode() + b"\n")
        before = generations.read_bytes()
        luna, other = endpoint(), endpoint(FREE, "https://api.example.org/v1")

        _, luna_path = run(
            [p], PlainModel([verdict(3, 3)]), tmp_path, judge=luna, table=free_table()
        )
        _, other_path = run(
            [p], PlainModel([verdict(1, 1)]), tmp_path, judge=other, table=free_table()
        )

        assert luna_path != other_path and luna_path.exists() and other_path.exists()
        [a], [b] = read_judgments(luna_path), read_judgments(other_path)
        assert a.judgment_key != b.judgment_key and a.generation_key == b.generation_key
        assert (a.correct, b.correct) == (3, 1)
        assert generations.read_bytes() == before
        assert sorted(f.name for f in tmp_path.glob("judgments.*.jsonl")) == sorted(
            [luna_path.name, other_path.name]
        )

    def test_the_stored_identity_names_model_and_host_but_never_the_key(self, tmp_path):
        chosen = JudgeEndpoint(FREE, "https://user:pw@api.example.org:8443/v1/x", "sk-secret-value")

        _, path = run([pair()], PlainModel([verdict()]), tmp_path, judge=chosen, table=free_table())

        text = path.read_text(encoding="utf-8")
        [stored] = read_judgments(path)
        assert stored.judge.model == FREE and stored.judge.host == "api.example.org"
        for secret in ("sk-secret-value", "user:pw", "/v1/x", "8443"):
            assert secret not in text and secret not in path.name
        assert "sk-secret-value" not in repr(chosen)


class TestRecord:
    def test_an_error_record_cannot_carry_scores(self):
        scored = Judgment(
            judgment_key="k",
            generation_key="g",
            item_id="i",
            family="hand",
            arm="a",
            judge={
                "prompt_version": "1",
                "model": "m",
                "host": "openai",
                "judged_on": "2026-11-19",
            },
            correct=1,
            faithful=1,
            abstained=False,
        )

        with pytest.raises(ValueError):
            Judgment.model_validate({**scored.model_dump(), "status": "error", "error": "bad"})
