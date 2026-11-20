"""Judge validation: weighted kappa, the blind sample and sheet, labelling and agreement."""

import json
import random

import pytest

from evals.run.endpoint import JudgeConfigError, JudgeEndpoint, resolve_judge_endpoint
from evals.run.judge import JudgePair
from evals.run.judge_validation import (
    HumanLabel,
    build_sheet,
    format_agreement,
    judge_vs_human,
    judge_vs_judge,
    labels_path,
    parse_scores,
    read_labels,
    read_sheet,
    run_labelling,
    sample_for_labelling,
    write_sheet,
)
from evals.run.records import JudgeVersion, Judgment
from evals.stats import weighted_kappa, weighted_kappa_interval
from tests.evals.judge_helpers import generation, item

pytestmark = pytest.mark.unit

IDENTITY = JudgeVersion(prompt_version="1", model="m", host="openai", judged_on="2026-11-19")


def graded(gold, arm="classic", correct=3, faithful=2, **fields) -> Judgment:
    gen = generation(gold, arm)
    return Judgment(
        judgment_key=f"j-{gen.record_key}",
        generation_key=gen.record_key,
        item_id=gold.id,
        family=gold.family,
        arm=arm,
        judge=IDENTITY,
        correct=correct,
        faithful=faithful,
        abstained=False,
        rationale="SECRET-JUDGE-RATIONALE",
        **fields,
    )


class TestWeightedKappa:
    def test_a_hand_computed_case_with_quadratic_weights(self):
        # Observed weighted disagreement 1/36; expected 1/18; kappa = 1 - 0.5.
        a, b = [0, 0, 1, 1], [0, 1, 1, 1]

        assert weighted_kappa(a, b) == pytest.approx(0.5)

    def test_quadratic_punishes_a_far_miss_more_than_linear(self):
        a, b = [0, 1, 2, 3, 3, 0], [0, 1, 2, 3, 0, 0]

        assert weighted_kappa(a, b, weights="quadratic") < weighted_kappa(a, b, weights="linear")

    def test_perfect_agreement_is_one_and_so_is_a_single_shared_label(self):
        assert weighted_kappa([0, 1, 2, 3], [0, 1, 2, 3]) == 1.0
        assert weighted_kappa([2, 2], [2, 2]) == 1.0

    def test_total_disagreement_is_below_zero(self):
        assert weighted_kappa([0, 3, 0, 3], [3, 0, 3, 0]) < 0

    @pytest.mark.parametrize(
        "args", [([1], []), ([], []), ([5], [1]), ([1], [1], (1,)), ([1], [1], (0, 1), "cubic")]
    )
    def test_bad_input_is_an_error(self, args):
        with pytest.raises(ValueError):
            weighted_kappa(*args)

    def test_the_interval_contains_the_point_estimate_and_is_seeded(self):
        rng = random.Random(4)
        a = [rng.randrange(4) for _ in range(60)]
        b = [x if rng.random() < 0.7 else rng.randrange(4) for x in a]

        point = weighted_kappa(a, b)
        low, high = weighted_kappa_interval(a, b, resamples=500, seed=1)

        assert low <= point <= high and high - low > 0
        assert (low, high) == weighted_kappa_interval(a, b, resamples=500, seed=1)
        assert weighted_kappa_interval([0, 1, 2, 3], [0, 1, 2, 3], resamples=50) == (1.0, 1.0)


class TestSample:
    def make(self):
        items = [item("rationale", n) for n in range(30)] + [item("hand", n) for n in range(6)]
        return [graded(i, correct=n % 4) for n, i in enumerate(items)]

    def test_the_sample_is_stratified_and_the_minimum_per_family_holds(self):
        pool = self.make()

        sample = sample_for_labelling(pool, n=12, seed=1, per_family_min=5)

        families = [j.family for j in sample]
        assert len(sample) == 12
        assert families.count("hand") >= 5 and families.count("rationale") >= 5

    def test_it_ignores_the_judges_scores_and_the_input_order(self):
        pool = self.make()
        flipped = [j.model_copy(update={"correct": 3 - (j.correct or 0)}) for j in pool]

        one = sample_for_labelling(pool, n=10, seed=2, per_family_min=3)
        two = sample_for_labelling(list(reversed(flipped)), n=10, seed=2, per_family_min=3)

        assert [j.generation_key for j in one] == [j.generation_key for j in two]

    def test_a_smaller_family_is_taken_whole_and_errors_and_reuse_are_left_out(self):
        gold = item("hand", 0)
        ok = graded(gold)
        reused = graded(item("hand", 1), reused_from="elsewhere")
        failed = graded(item("hand", 2)).model_copy(
            update={
                "status": "error",
                "error": "bad",
                "correct": None,
                "faithful": None,
                "abstained": None,
            }
        )

        sample = sample_for_labelling([ok, reused, failed], n=10, seed=0, per_family_min=5)

        assert [j.generation_key for j in sample] == [ok.generation_key]

    def test_the_sheet_hides_the_judges_scores_and_the_arm(self, tmp_path):
        golds = [item("hand", n) for n in range(3)]
        pool = [graded(g, arm="structural_rerank", correct=1, faithful=1) for g in golds]
        pairs = [JudgePair(g, generation(g, "structural_rerank")) for g in golds]

        entries = build_sheet(
            pool, pairs, evidence_for=lambda p: {"F:app/auth/security.py:10-20": "code"}.get
        )
        path = write_sheet(tmp_path / "sheet.jsonl", entries)

        text = path.read_text(encoding="utf-8")
        records = [json.loads(line) for line in text.splitlines()]
        assert len(records) == 3 and read_sheet(path) == entries
        assert "SECRET-JUDGE-RATIONALE" not in text and "structural_rerank" not in text
        for record in records:
            assert not {"correct", "faithful", "abstained", "rationale", "arm"} & record.keys()
            assert record["question"] and record["answer"] and "code" in record["evidence"]


def scripted(lines):
    replies = iter(lines)
    return lambda prompt: next(replies)


class TestLabelling:
    def entries(self, tmp_path):
        golds = [item("hand", n) for n in range(3)]
        pool = [graded(g) for g in golds]
        pairs = [JudgePair(g, generation(g)) for g in golds]
        return build_sheet(pool, pairs)

    def test_labels_are_saved_as_given_and_a_session_resumes(self, tmp_path):
        entries = self.entries(tmp_path)
        path = labels_path(tmp_path)
        shown: list[str] = []
        first = run_labelling(
            entries,
            path=path,
            input_fn=scripted(["3 2 good", "bogus", "1 0", "q"]),
            print_fn=shown.append,
        )
        skipped = run_labelling(entries, path=path, input_fn=scripted(["s"]), print_fn=shown.append)
        second = run_labelling(
            entries, path=path, input_fn=scripted(["2 2"]), print_fn=shown.append
        )

        labels = read_labels(path)
        assert (first.labelled, first.remaining, first.quit) == (2, 1, True)
        assert [(lab.correct, lab.faithful) for lab in labels] == [(3, 2), (1, 0), (2, 2)]
        assert labels[0].note == "good" and skipped.labelled == 0 and second.labelled == 1
        screen = "\n".join(shown)
        assert "SECRET-JUDGE-RATIONALE" not in screen and "Cited evidence" in screen
        assert "Reference notes" in screen and "Gold files" in screen

    def test_end_of_input_ends_the_session_like_quit(self, tmp_path):
        def eof(prompt):
            raise EOFError

        outcome = run_labelling(
            self.entries(tmp_path),
            path=labels_path(tmp_path),
            input_fn=eof,
            print_fn=lambda t: None,
        )

        assert outcome.quit and outcome.labelled == 0

    @pytest.mark.parametrize(
        ("text", "expected"),
        [("3 2", (3, 2, "")), ("0 1 a note here", (0, 1, "a note here")), ("S", "s"), ("q", "q")],
    )
    def test_parsing(self, text, expected):
        assert parse_scores(text) == expected

    @pytest.mark.parametrize("text", ["", "4 1", "1", "a b", "3 x"])
    def test_bad_lines_are_refused(self, text):
        assert parse_scores(text) is None


def label(j: Judgment, correct: int, faithful: int) -> HumanLabel:
    return HumanLabel(
        generation_key=j.generation_key,
        item_id=j.item_id,
        family=j.family,
        correct=correct,
        faithful=faithful,
    )


class TestAgreement:
    def test_a_judge_that_matches_the_labels_has_kappa_one_and_is_not_exploratory(self):
        golds = [item("hand", n) for n in range(12)]
        pool = [graded(g, correct=n % 4, faithful=(n + 1) % 4) for n, g in enumerate(golds)]
        labels = [label(j, j.correct, j.faithful) for j in pool]

        report = judge_vs_human(pool, labels, resamples=100, minimum=10)

        assert report.n == 12 and report.meets_minimum and not report.exploratory_families
        assert all(e.kappa == 1.0 for e in report.entries)
        assert "hand" in format_agreement(report, title="t")

    def test_a_family_with_low_kappa_is_flagged_exploratory(self):
        hands = [item("hand", n) for n in range(12)]
        rationales = [item("rationale", n) for n in range(12)]
        pool = [graded(g, correct=n % 4) for n, g in enumerate(hands + rationales)]
        labels = [
            label(j, j.correct if j.family == "hand" else 3 - (j.correct or 0), 2) for j in pool
        ]

        report = judge_vs_human(pool, labels, resamples=100, minimum=40)

        assert report.exploratory_families == {"rationale"}
        assert not report.meets_minimum
        assert "only 24 compared" in format_agreement(report, title="t")

    def test_two_judges_agree_per_family_on_the_generations_both_graded(self):
        golds = [item("hand", n) for n in range(10)]
        first = [graded(g, correct=n % 4) for n, g in enumerate(golds)]
        second = [j.model_copy(update={"judgment_key": "x" + j.judgment_key}) for j in first]
        extra = graded(item("hand", 99))

        report = judge_vs_judge(first + [extra], second, resamples=100, minimum=5)

        assert report.n == 10
        assert {e.family for e in report.entries} == {"hand", "all"}
        assert all(e.kappa == 1.0 for e in report.entries if e.dimension == "correct")

    def test_nothing_in_common_gives_an_empty_report(self):
        report = judge_vs_human([graded(item("hand", 0))], [], resamples=10)

        assert report.n == 0


class TestEndpointResolution:
    def test_defaults_are_the_pinned_judge_on_openai_with_the_openai_key(self):
        chosen = resolve_judge_endpoint({"OPENAI_API_KEY": "sk-openai"})

        assert (chosen.model, chosen.base_url, chosen.api_style) == (
            "gpt-6-luna",
            None,
            "responses",
        )
        assert chosen.host == "openai" and chosen.api_key == "sk-openai"
        assert chosen.client_kwargs() == {"api_key": "sk-openai"}

    def test_the_env_file_overrides_the_defaults(self):
        keys = {
            "OPENAI_API_KEY": "sk-openai",
            "JUDGE_MODEL": "qwen/qwen4-max:free",
            "JUDGE_BASE_URL": "https://openrouter.ai/api/v1",
            "JUDGE_API_KEY": "sk-judge",
            "JUDGE_API_STYLE": "chat",
        }

        chosen = resolve_judge_endpoint(keys)

        assert chosen.model == "qwen/qwen4-max:free" and chosen.host == "openrouter.ai"
        assert chosen.api_style == "chat" and chosen.api_key == "sk-judge"
        assert chosen.client_kwargs() == {
            "api_key": "sk-judge",
            "base_url": "https://openrouter.ai/api/v1",
        }

    def test_command_line_flags_override_the_env_file(self):
        keys = {"JUDGE_MODEL": "from-env", "JUDGE_API_STYLE": "chat", "OPENAI_API_KEY": "k"}

        chosen = resolve_judge_endpoint(
            keys, model="from-flag", base_url="https://x.example.com/v1", api_style="responses"
        )

        assert (chosen.model, chosen.host, chosen.api_style) == (
            "from-flag",
            "x.example.com",
            "responses",
        )

    def test_the_openai_key_is_never_sent_to_another_host(self):
        chosen = resolve_judge_endpoint(
            {"OPENAI_API_KEY": "sk-openai", "JUDGE_BASE_URL": "https://other.example.com/v1"}
        )

        assert chosen.api_key == ""
        with pytest.raises(JudgeConfigError, match="JUDGE_API_KEY"):
            chosen.require_key()

    def test_bad_values_are_refused(self):
        with pytest.raises(JudgeConfigError):
            resolve_judge_endpoint({}, api_style="soap")
        with pytest.raises(JudgeConfigError):
            resolve_judge_endpoint({}, base_url="not a url")
        with pytest.raises(JudgeConfigError):
            JudgeEndpoint(" ")

    def test_the_key_stays_out_of_repr_equality_and_the_slug(self):
        a = JudgeEndpoint("m/x:free", "https://h.example.com/v1", "secret-1")
        b = JudgeEndpoint("m/x:free", "https://h.example.com/v1", "secret-2")

        assert a == b and "secret" not in repr(a) and "secret" not in a.slug
        assert "/" not in a.slug and ":" not in a.slug
        assert a.slug != JudgeEndpoint("m/x:free").slug

    def test_the_judge_keys_are_recognised_but_never_exported_to_the_app(self):
        from evals.envcheck import ENV_EVAL_KEYS, eval_environment

        env = eval_environment({"JUDGE_API_KEY": "secret", "JUDGE_MODEL": "m"})

        assert {"JUDGE_MODEL", "JUDGE_BASE_URL", "JUDGE_API_KEY", "JUDGE_API_STYLE"} <= set(
            ENV_EVAL_KEYS
        )
        assert not [name for name in env if name.startswith("JUDGE_")]
        assert "secret" not in env.values()


class TestFreeJudgePricing:
    def table(self, **model):
        from tests.evals.run_helpers import complete_table

        return complete_table(models={"gpt-6-luna": complete_table().models["gpt-6-luna"], **model})

    def test_a_listed_free_model_with_zero_rates_is_accepted(self):
        zero = {"rates": {"input_cache_miss": 0, "input_cache_hit": 0, "output": 0}}

        self.table(**{"qwen/qwen4-max:free": zero}).require_complete(["qwen/qwen4-max:free"])

    def test_an_unlisted_model_still_refuses_to_run(self):
        from evals.run.pricing import PricesIncomplete

        with pytest.raises(PricesIncomplete, match="no entry"):
            self.table().require_complete(["qwen/qwen4-max:free"])

    def test_a_listed_model_with_missing_rates_still_refuses(self):
        from evals.run.pricing import PricesIncomplete

        with pytest.raises(PricesIncomplete):
            self.table(**{"m": {"rates": {"input_cache_miss": 0}}}).require_complete(["m"])
