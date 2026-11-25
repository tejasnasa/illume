"""The judge pass: selection, DeepEval metrics, per-metric caching, errors, metering and budget."""

import asyncio
import os
from datetime import UTC, datetime

import pytest
import respx

from evals.run import judge as judge_module
from evals.run.budget import Budget
from evals.run.deepeval_env import deepeval_version
from evals.run.judge import (
    JudgePair,
    grades_by_generation,
    judge_all,
    judgments_path,
    read_judgments,
    select_for_judging,
)
from evals.run.judge_metrics import (
    NO_EVIDENCE,
    default_metrics,
    evidence_pieces,
    reference_answer,
    settings_hash,
)
from evals.run.metering import Meter
from evals.run.records import CandidateRecord, Judgment
from tests.evals.judge_helpers import (
    CITED,
    FakeJudge,
    endpoint,
    evidence,
    generation,
    item,
    verdicts,
)
from tests.evals.run_helpers import complete_table

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
CODE = "def check(value): ..."


@pytest.fixture(autouse=True)
def no_network():
    """Any outbound HTTP request from a judge test is an error."""
    with respx.mock(assert_all_mocked=True, assert_all_called=False):
        yield


def run(pairs, model, tmp_path, *, judge=None, clock=lambda: NOW, **kw):
    chosen = judge or endpoint()
    path = judgments_path(tmp_path, chosen)
    kw.setdefault("evidence_for", evidence(CODE))
    result = asyncio.run(
        judge_all(
            pairs,
            endpoint=chosen,
            out_path=path,
            budget=kw.pop("budget", Budget(cap_usd=10, stop_usd=9.5)),
            table=kw.pop("table", complete_table()),
            client_factory=model.factory,
            clock=clock,
            **kw,
        )
    )
    return result, path


def pair(family="hand", n=0, arm="classic", **kw):
    gold = item(family, n)
    return JudgePair(gold, generation(gold, arm, **kw))


def by_metric(path):
    return {j.metric: j for j in read_judgments(path)}


class TestSelection:
    def make(self):
        items = [item("rationale", n) for n in range(3)]
        items += [item("hand", n) for n in range(2)]
        items += [item("hand", 9, tags=("unanswerable",))]
        items += [item("structural", n) for n in range(3)]
        items += [item("changeset", n) for n in range(20)]
        return items, [generation(i) for i in items]

    def test_every_item_is_judged_by_default_except_unanswerable_ones(self):
        items, gens = self.make()

        chosen = select_for_judging(items, gens, seed=1)

        assert len(chosen) == len(items) - 1
        assert not any("unanswerable" in p.item.tags for p in chosen)
        families = [p.item.family for p in chosen]
        assert families.count("changeset") == 20 and families.count("structural") == 3

    def test_unanswerable_items_can_be_asked_for(self):
        items, gens = self.make()

        chosen = select_for_judging(items, gens, seed=1, include_unanswerable=True)

        assert len(chosen) == len(items)

    def test_a_cluster_sample_is_still_available_and_keeps_both_variants_together(self):
        items, gens = self.make()

        chosen = select_for_judging(items, gens, seed=1, changeset_fraction=0.2)

        changesets = [p.item for p in chosen if p.item.family == "changeset"]
        clusters = {i.cluster for i in changesets}
        assert len(clusters) == 2  # 10 clusters, 20%
        members = [i for i in items if i.family == "changeset" and i.cluster in clusters]
        assert len(changesets) == len(members) == 4

    def test_selection_is_deterministic_and_independent_of_order(self):
        items, gens = self.make()

        first = select_for_judging(items, gens, seed=7, changeset_fraction=0.5)
        second = select_for_judging(
            list(reversed(items)), list(reversed(gens)), seed=7, changeset_fraction=0.5
        )

        assert [p.generation.record_key for p in first] == [p.generation.record_key for p in second]

    def test_error_generations_and_superseded_records_are_skipped(self):
        gold = item("hand", 0)
        failed = generation(gold, "classic", status="error")
        old = generation(gold, "hybrid", key="k", status="error")
        new = generation(gold, "hybrid", key="k")

        chosen = select_for_judging([gold], [failed, old, new], seed=0)

        assert [p.generation.arm for p in chosen] == ["hybrid"]


class TestWhatTheMetricsAreShown:
    def test_a_change_item_is_judged_against_the_pull_request_and_its_files(self):
        gold = item("changeset", 3)

        text = reference_answer(gold)

        assert "Add input validation 3" in text and "rejects empty input" in text
        assert "app/changeset3.py" in text

    def test_an_anchor_variant_does_not_leak_the_anchor_sentence(self):
        gold = item(
            "changeset",
            2,
            template="changeset.anchor",
            anchor_file="app/anchor.py",
            question_seed="Title\n\nBody\n\nStart from `app/anchor.py`.",
        )

        text = reference_answer(gold)

        assert "Start from" not in text and "app/anchor.py" not in text

    def test_a_hand_item_uses_its_reference_answer_when_it_has_one_and_its_notes_otherwise(self):
        gold = item("hand", 0)
        carrying = item(
            "hand",
            1,
            reference_answer="It hashes with bcrypt.",
            gold_answer_notes=("note",),
            gold_files=("app/a.py",),
        )

        assert "Feature 0 validates input." in reference_answer(gold)
        with_reference = reference_answer(carrying)
        assert "It hashes with bcrypt." in with_reference and "note" not in with_reference
        assert "app/a.py" in with_reference

    def test_the_evidence_is_labelled_with_its_path_and_line_range(self):
        gen = generation(item("hand", 0))

        pieces = evidence_pieces(gen, {CITED: CODE}.get)

        assert pieces == [f"[app/auth/security.py:10-20]\n{CODE}"]

    def test_evidence_without_text_is_not_offered_as_evidence(self):
        gen = generation(item("hand", 0))

        assert evidence_pieces(gen, {}.get) == []

    def test_a_short_piece_hands_its_unused_share_to_a_long_one(self):
        other = "F:app/auth/tokens.py:1-90"
        gen = generation(
            item("hand", 0),
            answer=f"It validates input [{CITED}] and signs tokens [{other}].",
            candidates=[
                CandidateRecord(key=CITED, rank=1, source_type="symbol"),
                CandidateRecord(key=other, rank=2, source_type="symbol"),
            ],
        )
        long_text = "x" * 900

        short_piece, long_piece = evidence_pieces(
            gen, {CITED: CODE, other: long_text}.get, budget=1000
        )

        assert short_piece.endswith(CODE)
        assert long_piece.endswith(long_text)

    def test_pieces_are_cut_only_when_the_whole_set_does_not_fit(self):
        gen = generation(item("hand", 0))

        (piece,) = evidence_pieces(gen, {CITED: "q" * 500}.get, budget=100)

        assert piece.endswith("(truncated)")
        assert piece.count("q") == 100

    def test_an_answer_citing_nothing_is_held_to_the_context_it_was_shown(self):
        gen = generation(item("hand", 0), answer="It validates input.", cited_keys=[])

        pieces = evidence_pieces(gen, {CITED: CODE}.get)

        assert pieces == [f"[app/auth/security.py:10-20]\n{CODE}"]

    def test_an_answer_citing_nothing_is_judged_against_a_note_saying_so(self, tmp_path):
        gold = item("hand", 0)
        bare = generation(gold, answer="It validates input.", cited_keys=[], candidates=[])
        model = FakeJudge()

        run([JudgePair(gold, bare)], model, tmp_path)

        assert any(NO_EVIDENCE in text for text in model.texts())


class TestGrading:
    def test_each_metric_stores_its_own_raw_score_and_the_correctness_rubric_value(self, tmp_path):
        model = FakeJudge(
            {
                "ReasonScore": {"reason": "r", "score": 2},
                "Verdicts": verdicts("yes", "no", "yes", "yes"),
            }
        )

        result, path = run([pair()], model, tmp_path)

        stored = by_metric(path)
        assert (result.ok, result.errors, result.planned) == (3, 0, 3)
        assert set(stored) == {"correctness", "faithfulness", "answer_relevancy"}
        assert stored["correctness"].score == pytest.approx(2 / 3)
        assert stored["correctness"].rubric == 2
        assert stored["faithfulness"].score == pytest.approx(0.75)
        assert stored["faithfulness"].rubric is None
        assert stored["answer_relevancy"].score == pytest.approx(0.75)
        assert all(j.status == "ok" and j.usages and j.cost_usd for j in stored.values())

    def test_an_ambiguous_claim_counts_against_faithfulness(self, tmp_path):
        model = FakeJudge({"Verdicts": verdicts("yes", "borderline")})

        _, path = run([pair()], model, tmp_path)

        assert by_metric(path)["faithfulness"].score == pytest.approx(0.5)

    def test_the_calls_per_answer_match_the_metrics(self, tmp_path):
        model = FakeJudge()

        run([pair()], model, tmp_path)

        names = model.names()
        assert names.count("ReasonScore") == 1  # fixed steps: no step-generation call
        assert "Steps" not in names
        assert sorted(n for n in names if n in {"Truths", "Claims", "Statements"}) == [
            "Claims",
            "Statements",
        ]  # faithfulness reads the evidence itself: no truth-extraction call
        assert names.count("Verdicts") == 2
        assert len(names) == 5

    def test_faithfulness_verdicts_read_the_cited_evidence_verbatim(self, tmp_path):
        model = FakeJudge()

        run([pair()], model, tmp_path)

        verdict_prompts = [
            text
            for name, text in zip(model.names(), model.texts(), strict=True)
            if name == "Verdicts" and "Retrieval Contexts" in text
        ]
        assert len(verdict_prompts) == 1
        assert f"[app/auth/security.py:10-20]\n{CODE}" in verdict_prompts[0]

    def test_every_call_is_structured_and_shows_nothing_about_the_arm(self, tmp_path):
        pairs = [pair("hand", 0, "structural_rerank"), pair("changeset", 1, "hybrid")]
        model = FakeJudge()

        run(pairs, model, tmp_path)

        everything = "\n".join(model.texts())
        for arm in ("structural_rerank", "hybrid", "classic"):
            assert arm not in everything
        for p in pairs:
            assert p.generation.config_hash not in everything
            assert p.generation.model not in everything
            assert p.generation.record_key not in everything
        assert all("text" in request for request in model.requests)
        assert all(r["text"]["format"]["strict"] for r in model.requests)

    def test_the_prompts_carry_the_question_the_reference_the_answer_and_the_evidence(
        self, tmp_path
    ):
        gold = item("changeset", 3, question="How does input get checked?")
        model = FakeJudge()

        run([JudgePair(gold, generation(gold))], model, tmp_path)

        everything = "\n".join(model.texts())
        assert "How does input get checked?" in everything
        assert "Add input validation 3" in everything and "app/changeset3.py" in everything
        assert "It validates input" in everything
        assert "[app/auth/security.py:10-20]" in everything and CODE in everything

    def test_the_stored_identity_names_the_release_model_and_host_but_never_the_key(self, tmp_path):
        _, path = run([pair()], FakeJudge(), tmp_path)

        text = path.read_text(encoding="utf-8")
        record = by_metric(path)["correctness"]
        assert record.judge.deepeval_version == deepeval_version()
        assert record.judge.model == "gpt-6-luna" and record.judge.host == "openai"
        assert record.judge.settings_hash == next(
            m.settings_hash for m in default_metrics() if m.name == "correctness"
        )
        assert "k-test" not in text

    def test_grades_gather_the_metrics_of_a_generation(self, tmp_path):
        model = FakeJudge({"ReasonScore": {"reason": "r", "score": 1}})
        p = pair()
        run([p], model, tmp_path)

        (grade,) = grades_by_generation(read_judgments(judgments_path(tmp_path, endpoint())))

        assert grade.generation_key == p.generation.record_key
        assert (grade.correct, grade.faithful, grade.status) == (1, 3, "ok")
        assert grade.relevancy_score == 1.0 and grade.errors == ()

    def test_a_judge_that_reports_no_usage_is_noted_and_costs_nothing(self, tmp_path):
        meter = Meter()

        result, path = run([pair()], FakeJudge(report_usage=False), tmp_path, meter=meter)

        assert result.ok == 3 and all(j.cost_usd == 0 for j in read_judgments(path))
        assert meter.unmetered == ["response_without_usage:judge"]


class TestCaching:
    def test_a_finished_pair_is_not_judged_again_even_on_another_day(self, tmp_path):
        p = pair()
        run([p], FakeJudge(), tmp_path)
        again = FakeJudge()

        result, path = run([p], again, tmp_path, clock=lambda: LATER)

        assert again.calls == 0 and result.skipped == 3 and result.ok == 0
        assert len(read_judgments(path)) == 3

    def test_changing_one_metrics_settings_judges_only_that_metric(self, tmp_path):
        p = pair()
        run([p], FakeJudge(), tmp_path)
        changed = []
        for spec in default_metrics():
            if spec.name == "answer_relevancy":
                spec = type(spec)(
                    spec.name, {**spec.settings, "answer_char_budget": 100}, spec.build, spec.case
                )
            changed.append(spec)
        again = FakeJudge()

        result, path = run([p], again, tmp_path, metrics=changed)

        assert result.ok == 1 and result.skipped == 2
        assert sorted(set(again.names())) == ["Statements", "Verdicts"]
        records = read_judgments(path)
        assert [j.metric for j in records].count("answer_relevancy") == 2
        assert [j.metric for j in records].count("correctness") == 1

    def test_a_deepeval_release_change_judges_every_metric_again(self, tmp_path):
        p = pair()
        run([p], FakeJudge(), tmp_path)
        again = FakeJudge()

        result, path = run([p], again, tmp_path, deepeval_release="9.9.9")

        assert result.ok == 3 and result.skipped == 0
        releases = {j.judge.deepeval_version for j in read_judgments(path)}
        assert releases == {deepeval_version(), "9.9.9"}

    def test_a_new_judge_model_or_host_judges_again_into_its_own_file(self, tmp_path):
        p = pair()
        run([p], FakeJudge(), tmp_path)
        other = endpoint("m2", "https://api.example.org/v1")
        table = complete_table(
            models={
                "gpt-6-luna": {"rates": {"input_cache_miss": 1, "input_cache_hit": 0, "output": 1}},
                "m2": {"rates": {"input_cache_miss": 0, "input_cache_hit": 0, "output": 0}},
            }
        )

        result, path = run([p], FakeJudge(), tmp_path, judge=other, table=table)

        assert result.ok == 3
        assert path != judgments_path(tmp_path, endpoint())
        assert {j.judge.host for j in read_judgments(path)} == {"api.example.org"}

    def test_the_settings_hash_is_stable_and_depends_on_content(self):
        assert settings_hash({"a": 1, "b": [1, 2]}) == settings_hash({"b": [1, 2], "a": 1})
        assert settings_hash({"a": 1}) != settings_hash({"a": 2})

    def test_the_three_metrics_have_distinct_hashes(self):
        assert len({m.settings_hash for m in default_metrics()}) == 3

    def test_generations_are_never_written(self, tmp_path):
        generations = tmp_path / "generations.jsonl"
        generations.write_text("untouched\n", encoding="utf-8")

        run([pair()], FakeJudge(), tmp_path)

        assert generations.read_text(encoding="utf-8") == "untouched\n"


class TestErrors:
    def test_a_metric_with_unusable_output_is_an_error_record_and_the_others_still_score(
        self, tmp_path
    ):
        model = FakeJudge({"ReasonScore": "I give it a three"})

        result, path = run([pair()], model, tmp_path)

        stored = by_metric(path)
        assert (result.ok, result.errors) == (2, 1)
        bad = stored["correctness"]
        assert bad.status == "error" and bad.score is None and bad.rubric is None
        assert "unusable" in (bad.error or "")
        assert stored["faithfulness"].status == "ok"

    def test_an_error_is_retried_on_the_next_run_and_the_last_record_wins(self, tmp_path):
        p = pair()
        run([p], FakeJudge({"ReasonScore": {"reason": "r", "score": 99}}), tmp_path)

        fixed = FakeJudge()
        result, path = run([p], fixed, tmp_path)

        assert (result.ok, result.skipped) == (1, 2) and set(fixed.names()) == {"ReasonScore"}
        (grade,) = grades_by_generation(read_judgments(path))
        assert grade.correct == 3 and grade.errors == ()
        statuses = [j.status for j in read_judgments(path) if j.metric == "correctness"]
        assert statuses == ["error", "ok"]

    def test_a_score_outside_zero_to_one_is_an_error_not_a_score(self, tmp_path):
        _, path = run([pair()], FakeJudge({"ReasonScore": {"reason": "r", "score": 7}}), tmp_path)

        record = by_metric(path)["correctness"]
        assert record.status == "error" and record.score is None

    def test_a_provider_failure_is_an_error_record_not_a_crash(self, tmp_path):
        model = FakeJudge(error=RuntimeError("provider down"))

        result, path = run([pair()], model, tmp_path)

        assert (result.ok, result.errors) == (0, 3)
        assert all("provider down" in (j.error or "") for j in read_judgments(path))

    def test_a_metric_that_times_out_is_an_error_record(self, tmp_path):
        result, path = run([pair()], FakeJudge(delay=0.5), tmp_path, metric_timeout=0.05)

        assert result.errors == 3
        assert all("did not finish" in (j.error or "") for j in read_judgments(path))

    def test_an_error_record_cannot_carry_a_score(self):
        record = error_record()

        assert record.status == "error" and record.score is None
        with pytest.raises(ValueError, match="never scored"):
            Judgment.model_validate({**record.model_dump(), "score": 0.5})
        with pytest.raises(ValueError, match="needs `error`"):
            Judgment.model_validate({**record.model_dump(), "error": None})


def error_record() -> Judgment:
    from evals.run.records import JudgeVersion

    return Judgment(
        judgment_key="k",
        generation_key="g",
        item_id="i",
        family="hand",
        arm="classic",
        metric="correctness",
        judge=JudgeVersion(
            deepeval_version="4.3.2", settings_hash="h", model="m", host="openai", judged_on="d"
        ),
        status="error",
        error="boom",
    )


class TestMeteringAndBudget:
    def test_every_call_reaches_the_budget_the_meter_and_the_record(self, tmp_path):
        budget = Budget(cap_usd=10, stop_usd=9.5)
        meter = Meter()

        result, path = run([pair()], FakeJudge(), tmp_path, budget=budget, meter=meter)

        records = read_judgments(path)
        assert sum(len(j.usages) for j in records) == 5
        # 1000 input and 50 output tokens per call at the table rates.
        assert budget.spent_usd == pytest.approx(5 * 0.0011)
        assert result.spent_usd == pytest.approx(budget.spent_usd)
        assert sum(j.cost_usd or 0 for j in records) == pytest.approx(budget.spent_usd)
        assert all(u.kind == "judge" and u.model == "gpt-6-luna" for j in records for u in j.usages)
        assert len(meter.usages) == 5
        assert result.reported_models == {"reported-judge-model"}

    def test_the_run_stops_cleanly_at_the_stop_threshold(self, tmp_path):
        pairs = [pair("hand", n) for n in range(3)]
        budget = Budget(cap_usd=1.0, stop_usd=0.00001)

        result, path = run(pairs, FakeJudge(), tmp_path, budget=budget)

        assert result.stopped is not None and "stop" in result.stopped
        assert 0 < len(read_judgments(path)) < 9

    def test_spend_on_disk_counts_when_the_run_resumes(self, tmp_path):
        from evals.run.judge import all_judgments, final_judgments

        run([pair()], FakeJudge(), tmp_path)
        budget = Budget(cap_usd=10, stop_usd=9.5)

        spent = budget.restore([], judgments=final_judgments(all_judgments(tmp_path)))

        assert spent == pytest.approx(5 * 0.0011)

    def test_an_unpriced_judge_model_stops_the_run(self, tmp_path):
        result, _ = run([pair("hand", 0), pair("hand", 1)], FakeJudge(), tmp_path, table=_blank())

        assert result.stopped and "no price" in result.stopped

    def test_concurrent_gradings_all_complete(self, tmp_path):
        pairs = [pair("hand", n) for n in range(4)]

        result, path = run(pairs, FakeJudge(), tmp_path, concurrency=4)

        assert result.ok == 12 and len(read_judgments(path)) == 12


def _blank():
    return complete_table(
        models={"other": {"rates": {"input_cache_miss": 1, "input_cache_hit": 0, "output": 1}}}
    )


class TestTransports:
    def test_chat_completions_ask_for_json_and_parse_it(self, tmp_path):
        chat = endpoint("qwen/qwen4-max:free", "https://api.example.org/v1", api_style="chat")
        model = FakeJudge()
        table = complete_table(
            models={
                "qwen/qwen4-max:free": {
                    "rates": {"input_cache_miss": 0, "input_cache_hit": 0, "output": 0}
                }
            }
        )

        result, path = run([pair()], model, tmp_path, judge=chat, table=table)

        assert result.ok == 3 and model.client_kwargs["base_url"] == "https://api.example.org/v1"
        assert all(r["response_format"] == {"type": "json_object"} for r in model.requests)
        assert all("JSON schema" in r["messages"][0]["content"] for r in model.requests)
        assert {j.reported_model for j in read_judgments(path)} == {"reported-chat-model"}

    def test_a_provider_that_rejects_structured_output_is_asked_again_with_the_schema_in_text(
        self, tmp_path
    ):
        model = FakeJudge(reject_structured=True)

        result, _ = run([pair()], model, tmp_path)

        assert result.ok == 3
        retries = [r for r in model.requests if "text" not in r]
        assert len(retries) == 5 and all("JSON schema" in r["input"][0]["content"] for r in retries)

    def test_chat_json_mode_rejection_falls_back_to_a_plain_request(self, tmp_path):
        chat = endpoint("m", "https://api.example.org/v1", api_style="chat")
        table = complete_table(
            models={"m": {"rates": {"input_cache_miss": 0, "input_cache_hit": 0, "output": 0}}}
        )

        result, _ = run(
            [pair()], FakeJudge(reject_structured=True), tmp_path, judge=chat, table=table
        )

        assert result.ok == 3


class TestComposedRecords:
    def test_an_identical_composed_answer_reuses_its_targets_grades(self, tmp_path):
        gold = item("hand", 0)
        target = generation(gold, "classic")
        composed = generation(gold, "auto", composed_from="classic")
        model = FakeJudge()

        result, path = run([JudgePair(gold, target), JudgePair(gold, composed)], model, tmp_path)

        assert (result.ok, result.reused) == (3, 3) and model.calls == 5
        copies = [j for j in read_judgments(path) if j.arm == "auto"]
        assert len(copies) == 3 and all(j.reused_from and j.usages == [] for j in copies)
        assert all(j.cost_usd == 0 for j in copies)

    def test_a_composed_answer_that_differs_is_graded_itself(self, tmp_path):
        gold = item("hand", 0)
        target = generation(gold, "classic")
        composed = generation(gold, "auto", composed_from="classic", answer="Something else")

        result, _ = run([JudgePair(gold, target), JudgePair(gold, composed)], FakeJudge(), tmp_path)

        assert (result.ok, result.reused) == (6, 0)


class TestEnvironment:
    def test_telemetry_is_off_and_nothing_reads_dotenv_files(self):
        from deepeval.config.settings import get_settings

        assert os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] == "1"
        assert os.environ["DEEPEVAL_DISABLE_DOTENV"] == "1"
        assert get_settings().DEEPEVAL_TELEMETRY_OPT_OUT is True

    def test_the_installed_release_is_the_pinned_one(self):
        assert deepeval_version() == "4.3.2"

    def test_the_judge_module_does_not_use_the_deepeval_runner(self):
        source = open(judge_module.__file__, encoding="utf-8").read()

        assert "evaluate(" not in source and "assert_test" not in source
