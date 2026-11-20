"""Verification: sampling, the labelling loop, the error report and agreement."""

from typing import Any

import pytest

from evals.gold.schema import make_item
from evals.gold.verify import (
    Label,
    agreement_report,
    apply_labels,
    gold_error_report,
    labels_path,
    read_labels,
    run_verification,
    sample_for_verification,
)
from evals.stats import cohen_kappa, wilson_interval

pytestmark = pytest.mark.unit

BASE = "e" * 40


def _family(family: str, n: int, template: str | None = None):
    items = []
    for number in range(n):
        fields: dict[str, Any] = {
            "repo": "demo",
            "base_commit": BASE,
            "family": family,
            "template": template or f"{family}.t",
            "question_seed": f"{family} {template} {number}",
            "gold_files": (f"src/{family}{number}.py", f"src/{family}{number}_b.py"),
        }
        if family == "structural":
            fields["circular_with"] = ("graph",)
        elif family == "rationale":
            fields["circular_with"] = ("history",)
        elif family == "changeset":
            fields.update(
                cluster=f"demo#{number}",
                merges_since_base=number,
                template=template or "changeset.blind",
            )
        items.append(make_item(**fields))
    return items


def _labels(items, wrong=0, ambiguous=0):
    out = []
    for position, item in enumerate(items):
        if position < wrong:
            verdict = "wrong"
        elif position < wrong + ambiguous:
            verdict = "ambiguous"
        else:
            verdict = "correct"
        out.append(Label(item.id, verdict))
    return out


@pytest.mark.parametrize(("size", "expected"), [(30, 30), (50, 50), (200, 50), (1000, 150)])
def test_sample_sizes(size, expected):
    sample = sample_for_verification(_family("structural", size), seed=1)
    assert len(sample) == expected


def test_sampling_is_stratified_and_deterministic():
    items = _family("structural", 200) + _family("rationale", 30) + _family("changeset", 1000)
    one = sample_for_verification(items, seed=2)
    two = sample_for_verification(list(reversed(items)), seed=2)
    assert [i.id for i in one] == [i.id for i in two]
    sizes = {f: sum(i.family == f for i in one) for f in ("structural", "rationale", "changeset")}
    assert sizes == {"structural": 50, "rationale": 30, "changeset": 150}
    assert [i.id for i in sample_for_verification(items, seed=3)] != [i.id for i in one]


def test_a_session_labels_and_resumes_after_quit(tmp_path):
    items = _family("rationale", 3)
    path = labels_path(tmp_path, "ada")
    assert path.name == "labels.ada.jsonl"
    shown: list[str] = []
    answers = iter(["c", "w the last file is unrelated", "q"])
    outcome = run_verification(
        items,
        slug="o/r",
        path=path,
        annotator="ada",
        input_fn=lambda _: next(answers),
        print_fn=shown.append,
    )
    assert (outcome.labelled, outcome.remaining, outcome.quit) == (2, 1, True)
    saved = read_labels(path)
    assert [(x.item_id, x.label, x.note, x.annotator) for x in saved] == [
        (items[0].id, "correct", "", "ada"),
        (items[1].id, "wrong", "the last file is unrelated", "ada"),
    ]

    shown.clear()
    answers = iter(["x", "a"])
    again = run_verification(
        items,
        slug="o/r",
        path=path,
        annotator="ada",
        input_fn=lambda _: next(answers),
        print_fn=shown.append,
    )
    text = "\n".join(shown)
    assert (again.labelled, again.remaining, again.quit) == (1, 0, False)
    assert items[0].question_seed not in text
    assert items[2].question_seed in text
    assert f"https://github.com/o/r/blob/{BASE}/src/rationale2.py" in text
    assert [x.label for x in read_labels(path)] == ["correct", "wrong", "ambiguous"]


def test_skip_records_nothing_and_links_mark_tests_and_prs(tmp_path):
    item = make_item(
        repo="demo",
        base_commit=BASE,
        family="changeset",
        template="changeset.blind",
        question_seed="seed text",
        gold_files=("src/a.py", "tests/test_a.py"),
        gold_test_files=("tests/test_a.py",),
        gold_prs=(42,),
        cluster="demo#42",
        merges_since_base=0,
    ).model_copy(update={"question": "phrased text"})
    shown: list[str] = []
    answers = iter(["s"])
    outcome = run_verification(
        [item],
        slug="o/r",
        path=tmp_path / "labels.jsonl",
        input_fn=lambda _: next(answers),
        print_fn=shown.append,
    )
    assert (outcome.labelled, outcome.remaining) == (0, 1)
    assert not (tmp_path / "labels.jsonl").exists()
    text = "\n".join(shown)
    assert "phrased text" in text and "seed text" in text
    assert f"/blob/{BASE}/tests/test_a.py  [test]" in text
    assert "https://github.com/o/r/pull/42" in text
    assert "Labelling rule" in text


def test_wilson_interval_matches_a_hand_computed_case():
    lower, upper = wilson_interval(5, 50)
    assert lower == pytest.approx(0.0435, abs=5e-4)
    assert upper == pytest.approx(0.2136, abs=5e-4)
    assert wilson_interval(0, 0) == (0.0, 1.0)
    zero_lower, zero_upper = wilson_interval(0, 50)
    assert zero_lower == 0.0
    assert zero_upper == pytest.approx(0.0713, abs=5e-4)
    with pytest.raises(ValueError):
        wilson_interval(3, 2)


def test_cohen_kappa_matches_a_hand_computed_case():
    a = ["correct"] * 20 + ["wrong"] * 5 + ["correct"] * 5 + ["wrong"] * 20
    b = ["correct"] * 20 + ["correct"] * 5 + ["wrong"] * 5 + ["wrong"] * 20
    # observed 40/50 = 0.8; each rater says correct for 25 of 50, so chance is 0.5
    assert cohen_kappa(a, b) == pytest.approx(0.6)
    assert cohen_kappa(["a", "b"], ["a", "b"]) == 1.0
    assert cohen_kappa(["a", "a"], ["a", "a"]) == 1.0
    with pytest.raises(ValueError):
        cohen_kappa(["a"], [])


def test_the_error_report_counts_ambiguous_separately():
    items = _family("rationale", 50)
    report = gold_error_report(items, _labels(items, wrong=5, ambiguous=5))
    stats = report.families["rationale"]
    assert (stats.n_labelled, stats.n_ambiguous, stats.n_wrong, stats.n_scored) == (50, 5, 5, 45)
    assert stats.rate == pytest.approx(5 / 45)
    assert (stats.lower, stats.upper) == pytest.approx(wilson_interval(5, 45))


def test_the_drop_rule_fires_only_at_fifty_labelled():
    forty_nine = _family("rationale", 49)
    fifty = _family("rationale", 50)
    assert not gold_error_report(forty_nine, _labels(forty_nine, wrong=49)).dropped_families
    assert gold_error_report(fifty, _labels(fifty, wrong=50)).dropped_families == {"rationale"}


def test_the_drop_rule_uses_the_upper_bound():
    items = _family("rationale", 50)
    # 5 of 50 wrong: upper bound 21.4%, above the 20% line.
    assert gold_error_report(items, _labels(items, wrong=5)).dropped_families == {"rationale"}
    # 4 of 50 wrong: upper bound about 18.8%.
    assert not gold_error_report(items, _labels(items, wrong=4)).dropped_families


def test_a_small_template_is_pooled_with_its_family_not_dropped_alone():
    good = _family("structural", 100, "structural.importers")
    bad = _family("structural", 10, "structural.path")
    labels = _labels(good) + _labels(bad, wrong=4)
    report = gold_error_report(good + bad, labels)
    assert not report.templates["structural.path"].judged
    assert not report.dropped_templates
    assert not report.dropped_families
    assert report.templates["structural.importers"].judged


def test_a_large_bad_template_is_dropped_but_its_family_survives():
    good = _family("structural", 400, "structural.importers")
    bad = _family("structural", 50, "structural.path")
    labels = _labels(good) + _labels(bad, wrong=50)
    report = gold_error_report(good + bad, labels)
    assert report.dropped_templates == {"structural.path"}
    assert not report.dropped_families
    kept = apply_labels(good + bad, labels)
    assert {i.template for i in kept} == {"structural.importers"}


def test_agreement_uses_only_the_overlap():
    items = _family("rationale", 6)
    first = [Label(i.id, "correct") for i in items[:4]] + [Label(items[4].id, "wrong")]
    second = [
        Label(items[0].id, "correct"),
        Label(items[1].id, "wrong"),
        Label(items[4].id, "wrong"),
        Label(items[5].id, "correct"),
    ]
    report = agreement_report(first, second)
    assert report.n == 3
    assert report.agreement == pytest.approx(2 / 3)
    # a: c,c,w and b: c,w,w -> observed 2/3, expected (2*1 + 1*2)/9 = 4/9
    assert report.kappa == pytest.approx((2 / 3 - 4 / 9) / (1 - 4 / 9))
    assert agreement_report([], first).kappa is None


def test_apply_labels_marks_verified_and_drops_wrong_and_ambiguous():
    items = _family("rationale", 5)
    labels = [
        Label(items[0].id, "correct"),
        Label(items[1].id, "wrong"),
        Label(items[2].id, "ambiguous"),
    ]
    kept = apply_labels(items, labels)
    assert [i.id for i in kept] == [items[0].id, items[3].id, items[4].id]
    assert [i.verified for i in kept] == ["correct", None, None]
