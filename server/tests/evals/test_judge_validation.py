"""Judge validation: kappa, the blind 30-answer sample and sheet, labelling and agreement."""

import json
import random

import pytest

from evals.run.endpoint import JudgeConfigError, JudgeEndpoint, resolve_judge_endpoint
from evals.run.judge import Grade, JudgePair
from evals.run.judge_validation import (
    CORRECTNESS_LEVELS,
    LABEL_SAMPLE_SIZE,
    RUBRIC_TO_LEVEL,
    UNFAITHFUL_BELOW,
    Correctness,
    HumanLabel,
    build_sheet,
    format_agreement,
    judge_levels,
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
from evals.run.records import JudgeVersion, Judgment, Metric
from evals.stats import weighted_kappa, weighted_kappa_interval
from tests.evals.judge_helpers import generation, item

pytestmark = pytest.mark.unit

ARMS = ("classic", "hybrid", "structural", "agent", "hybrid_rerank")


def grade(gold, arm="classic", correct=3, faithful=1.0, **fields) -> Grade:
    gen = generation(gold, arm)
    return Grade(
        generation_key=gen.record_key,
        item_id=gold.id,
        family=gold.family,
        arm=arm,
        correct=correct,
        correct_score=correct / 3,
        faithful_score=faithful,
        relevancy_score=0.9,
        **fields,
    )


def judgments_for(gold, arm="classic", correct=3, faithful=1.0, tag="") -> list[Judgment]:
    """The three per-metric records of one generation, as the judge writes them."""
    gen = generation(gold, arm)
    version = JudgeVersion(
        deepeval_version="4.3.2", settings_hash="h", model="m", host="openai", judged_on="d"
    )
    scores: dict[Metric, float] = {
        "correctness": correct / 3,
        "faithfulness": faithful,
        "answer_relevancy": 0.9,
    }
    return [
        Judgment(
            judgment_key=f"{tag}{metric}-{gen.record_key}",
            generation_key=gen.record_key,
            item_id=gold.id,
            family=gold.family,
            arm=arm,
            metric=metric,
            judge=version,
            score=score,
            rubric=correct if metric == "correctness" else None,
        )
        for metric, score in scores.items()
    ]


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
    def make(self, per_stratum=3):
        grades = []
        n = 0
        for family in ("changeset", "hand"):
            for arm in ARMS:
                for _ in range(per_stratum):
                    grades.append(grade(item(family, n), arm, correct=n % 4))
                    n += 1
        return grades

    def test_the_sample_is_30_by_default_and_spread_across_arms_and_question_kinds(self):
        pool = self.make()

        sample = sample_for_labelling(pool, n=LABEL_SAMPLE_SIZE, seed=1)

        assert LABEL_SAMPLE_SIZE == 30 and len(sample) == 30
        assert {g.arm for g in sample} == set(ARMS)
        assert {g.family for g in sample} == {"changeset", "hand"}
        counts: dict[tuple[str, str], int] = {}
        for g in sample:
            counts[(g.family, g.arm)] = counts.get((g.family, g.arm), 0) + 1
        assert len(counts) == 10 and set(counts.values()) == {3}

    def test_a_smaller_sample_takes_one_from_each_stratum_before_a_second_from_any(self):
        sample = sample_for_labelling(self.make(), n=10, seed=3)

        assert len({(g.family, g.arm) for g in sample}) == 10

    def test_it_ignores_the_judges_scores_and_the_input_order(self):
        pool = self.make()
        flipped = [
            Grade(**{**g.__dict__, "correct": 3 - (g.correct or 0), "faithful_score": 0.1})
            for g in pool
        ]

        one = sample_for_labelling(pool, n=12, seed=2)
        two = sample_for_labelling(list(reversed(flipped)), n=12, seed=2)

        assert [g.generation_key for g in one] == [g.generation_key for g in two]

    def test_a_smaller_sample_is_contained_in_a_larger_one(self):
        pool = self.make()

        small = {g.generation_key for g in sample_for_labelling(pool, n=10, seed=5)}
        large = {g.generation_key for g in sample_for_labelling(pool, n=20, seed=5)}

        assert small <= large

    def test_a_small_pool_is_taken_whole_and_errors_and_reuse_are_left_out(self):
        ok = grade(item("hand", 0))
        reused = grade(item("hand", 1), reused=True)
        failed = Grade(
            generation_key="x", item_id="i", family="hand", arm="classic", errors=("correctness",)
        )

        sample = sample_for_labelling([ok, reused, failed], n=10, seed=0)

        assert [g.generation_key for g in sample] == [ok.generation_key]

    def test_the_sheet_hides_the_judges_scores_and_the_arm(self, tmp_path):
        golds = [item("hand", n) for n in range(3)]
        pool = [grade(g, arm="structural_rerank", correct=1, faithful=0.123) for g in golds]
        pairs = [JudgePair(g, generation(g, "structural_rerank")) for g in golds]

        entries = build_sheet(
            pool, pairs, evidence_for=lambda p: {"F:app/auth/security.py:10-20": "code"}.get
        )
        path = write_sheet(tmp_path / "sheet.jsonl", entries)

        text = path.read_text(encoding="utf-8")
        records = [json.loads(line) for line in text.splitlines()]
        assert len(records) == 3 and read_sheet(path) == entries
        assert "structural_rerank" not in text and "0.123" not in text
        for record in records:
            assert not {"correct", "faithful", "score", "arm"} & record.keys()
            assert record["question"] and record["answer"] and "code" in record["evidence"]
            assert any("Feature" in note for note in record["notes"])


def scripted(lines):
    replies = iter(lines)
    return lambda prompt: next(replies)


class TestLabelling:
    def entries(self):
        golds = [item("hand", n) for n in range(3)]
        pool = [grade(g) for g in golds]
        pairs = [JudgePair(g, generation(g)) for g in golds]
        return build_sheet(pool, pairs)

    def test_labels_are_saved_as_given_and_a_session_resumes(self, tmp_path):
        entries = self.entries()
        path = labels_path(tmp_path)
        shown: list[str] = []
        first = run_labelling(
            entries,
            path=path,
            input_fn=scripted(["c n good", "bogus", "w y", "q"]),
            print_fn=shown.append,
        )
        skipped = run_labelling(entries, path=path, input_fn=scripted(["s"]), print_fn=shown.append)
        second = run_labelling(
            entries, path=path, input_fn=scripted(["p n"]), print_fn=shown.append
        )

        labels = read_labels(path)
        assert (first.labelled, first.remaining, first.quit) == (2, 1, True)
        assert [(lab.correct, lab.made_something_up) for lab in labels] == [
            ("correct", False),
            ("wrong", True),
            ("partly", False),
        ]
        assert labels[0].note == "good" and skipped.labelled == 0 and second.labelled == 1
        screen = "\n".join(shown)
        assert "Cited evidence" in screen and "Reference notes" in screen
        assert "Gold files" in screen and "made anything up" in screen

    def test_end_of_input_ends_the_session_like_quit(self, tmp_path):
        def eof(prompt):
            raise EOFError

        outcome = run_labelling(
            self.entries(), path=labels_path(tmp_path), input_fn=eof, print_fn=lambda t: None
        )

        assert outcome.quit and outcome.labelled == 0

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("c n", ("correct", False, "")),
            ("P y a note here", ("partly", True, "a note here")),
            ("w N", ("wrong", False, "")),
            ("S", "s"),
            ("q", "q"),
        ],
    )
    def test_parsing(self, text, expected):
        assert parse_scores(text) == expected

    @pytest.mark.parametrize("text", ["", "3 2", "c", "c maybe", "x y", "cc n"])
    def test_bad_lines_are_refused(self, text):
        assert parse_scores(text) is None


def label(g: Grade, correct: Correctness, made_up: bool) -> HumanLabel:
    return HumanLabel(
        generation_key=g.generation_key,
        item_id=g.item_id,
        family=g.family,
        correct=correct,
        made_something_up=made_up,
    )


class TestBinning:
    def test_the_rubric_is_binned_to_wrong_partly_and_correct(self):
        assert [RUBRIC_TO_LEVEL[n] for n in range(4)] == [0, 1, 2, 2]
        assert CORRECTNESS_LEVELS == {"wrong": 0, "partly": 1, "correct": 2}

    def test_faithfulness_below_the_cutoff_is_made_something_up(self):
        gold = item("hand", 0)

        assert judge_levels(grade(gold, correct=3, faithful=UNFAITHFUL_BELOW)) == (2, 0)
        assert judge_levels(grade(gold, correct=1, faithful=UNFAITHFUL_BELOW - 0.01)) == (1, 1)

    def test_a_row_missing_a_metric_cannot_be_binned(self):
        bare = Grade(generation_key="g", item_id="i", family="hand", arm="a", correct=2)

        with pytest.raises(ValueError, match="no correctness and faithfulness"):
            judge_levels(bare)


class TestAgreement:
    def test_the_thirty_label_check_hand_computed(self):
        # 30 answers, 15 hand and 15 changeset. DeepEval's bins are 10 wrong, 10 partly and 10
        # correct; the person agrees on 24 and is one level off on the other 6.
        golds = [item("hand", n) for n in range(15)] + [item("changeset", n) for n in range(15)]
        rubric = [0] * 10 + [1] * 10 + [3] * 10
        grades = [grade(g, correct=r, faithful=1.0) for g, r in zip(golds, rubric, strict=True)]
        levels = [0] * 10 + [1] * 10 + [2] * 10
        human = list(levels)
        for index in (0, 1, 10, 11, 20, 21):
            human[index] = levels[index] + 1 if levels[index] < 2 else 1
        names = ["wrong", "partly", "correct"]
        labels = [label(g, names[h], False) for g, h in zip(grades, human, strict=True)]

        report = judge_vs_human(grades, labels, resamples=200, seed=1)

        pooled = {e.dimension: e for e in report.entries if e.family == "all"}
        assert report.n == 30 and report.meets_minimum
        assert pooled["correct"].n == 30 and pooled["correct"].agreement == pytest.approx(24 / 30)
        assert pooled["correct"].kappa == pytest.approx(weighted_kappa(levels, human, (0, 1, 2)))
        assert pooled["correct"].lower <= pooled["correct"].kappa <= pooled["correct"].upper
        # DeepEval says nothing was made up and neither does the person: agreement is total.
        assert pooled["made_up"].agreement == 1.0 and pooled["made_up"].kappa == 1.0
        assert {e.family for e in report.entries} == {"hand", "changeset", "all"}

    def test_made_something_up_is_compared_on_the_two_bins(self):
        golds = [item("hand", n) for n in range(10)]
        grades = [grade(g, faithful=0.5 if n < 5 else 1.0) for n, g in enumerate(golds)]
        labels = [label(g, "correct", n < 4 or n == 9) for n, g in enumerate(grades)]

        report = judge_vs_human(grades, labels, resamples=50, minimum=10)

        made_up = next(e for e in report.entries if e.family == "all" and e.dimension == "made_up")
        assert made_up.n == 10 and made_up.agreement == pytest.approx(0.8)

    def test_a_judge_that_matches_the_labels_has_kappa_one_and_is_not_exploratory(self):
        golds = [item("hand", n) for n in range(12)]
        grades = [
            grade(g, correct=n % 4, faithful=1.0 if n % 2 else 0.2) for n, g in enumerate(golds)
        ]
        labels = [
            label(g, ["wrong", "partly", "correct", "correct"][g.correct], g.faithful_score < 0.8)
            for g in grades
        ]

        report = judge_vs_human(grades, labels, resamples=100, minimum=10)

        assert report.n == 12 and report.meets_minimum and not report.exploratory_families
        assert all(e.kappa == 1.0 for e in report.entries)
        assert "hand" in format_agreement(report, title="t")

    def test_a_family_with_low_kappa_is_flagged_exploratory(self):
        hands = [item("hand", n) for n in range(12)]
        rationales = [item("rationale", n) for n in range(12)]
        grades = [grade(g, correct=(0, 1, 3)[n % 3]) for n, g in enumerate(hands + rationales)]
        flip = {"wrong": "correct", "partly": "partly", "correct": "wrong"}
        names = {0: "wrong", 1: "partly", 3: "correct"}
        labels = [
            label(g, names[g.correct] if g.family == "hand" else flip[names[g.correct]], False)
            for g in grades
        ]

        report = judge_vs_human(grades, labels, resamples=100, minimum=40)

        assert report.exploratory_families == {"rationale"}
        assert not report.meets_minimum
        assert "only 24 compared" in format_agreement(report, title="t")

    def test_two_judges_agree_per_family_on_the_generations_both_graded(self):
        golds = [item("hand", n) for n in range(10)]
        first = [j for n, g in enumerate(golds) for j in judgments_for(g, correct=n % 4)]
        second = [j for n, g in enumerate(golds) for j in judgments_for(g, correct=n % 4, tag="b-")]
        extra = judgments_for(item("hand", 99))

        report = judge_vs_judge(first + extra, second, resamples=100, minimum=5)

        assert report.n == 10
        assert {e.family for e in report.entries} == {"hand", "all"}
        assert all(e.kappa == 1.0 for e in report.entries)

    def test_nothing_in_common_gives_an_empty_report(self):
        report = judge_vs_human([grade(item("hand", 0))], [], resamples=10)

        assert report.n == 0


class TestEndpointResolution:
    def test_defaults_are_the_pinned_judge_on_openrouter_with_the_openrouter_key(self):
        chosen = resolve_judge_endpoint(
            {"OPENAI_API_KEY": "sk-openai", "OPENROUTER_API_KEY": "sk-or"}
        )

        assert (chosen.model, chosen.base_url, chosen.api_style) == (
            "anthropic/claude-haiku-5.5",
            "https://openrouter.ai/api/v1",
            "chat",
        )
        assert chosen.host == "openrouter.ai" and chosen.api_key == "sk-or"
        assert chosen.client_kwargs() == {
            "api_key": "sk-or",
            "base_url": "https://openrouter.ai/api/v1",
        }

    def test_the_openai_key_is_used_only_on_openais_endpoint(self):
        chosen = resolve_judge_endpoint(
            {
                "OPENAI_API_KEY": "sk-openai",
                "OPENROUTER_API_KEY": "sk-or",
                "JUDGE_BASE_URL": "https://api.openai.com/v1",
            }
        )

        assert chosen.api_key == "sk-openai"

    def test_a_missing_openrouter_key_is_named(self):
        chosen = resolve_judge_endpoint({"OPENAI_API_KEY": "sk-openai"})

        assert chosen.api_key == ""
        with pytest.raises(JudgeConfigError, match="OPENROUTER_API_KEY"):
            chosen.require_key()

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

    def test_no_provider_key_is_sent_to_another_host(self):
        chosen = resolve_judge_endpoint(
            {
                "OPENAI_API_KEY": "sk-openai",
                "OPENROUTER_API_KEY": "sk-or",
                "JUDGE_BASE_URL": "https://other.example.com/v1",
            }
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
