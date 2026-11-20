"""Loading hand-written questions."""

import pytest

from evals.gold.hand import HAND_DIR, HandError, hand_path, load_hand_items

pytestmark = pytest.mark.unit

BASE = "c" * 40


def test_the_example_file_parses():
    items = load_hand_items(HAND_DIR / "example.yaml", repo_name="demo", base_commit=BASE)
    assert [item.template for item in items] == [
        "hand.architecture",
        "hand.flow",
        "hand.unanswerable",
    ]
    architecture, flow, _ = items
    assert architecture.gold_files == ("app/middleware/auth.py",)
    assert architecture.acceptable_files == ("app/api/deps.py",)
    assert architecture.gold_answer_notes
    assert architecture.question == architecture.question_seed
    assert flow.tags == ("multi-file",)
    assert all(item.family == "hand" and item.circular_with == () for item in items)


def test_unanswerable_items_have_empty_gold_and_a_tag():
    *_, unanswerable = load_hand_items(
        HAND_DIR / "example.yaml", repo_name="demo", base_commit=BASE
    )
    assert unanswerable.gold_files == ()
    assert unanswerable.acceptable_files == ()
    assert "unanswerable" in unanswerable.tags


def test_the_guide_states_the_labelling_rule():
    text = (HAND_DIR / "GUIDE.md").read_text(encoding="utf-8")
    for phrase in (
        "*correct*",
        "*ambiguous*",
        "*wrong*",
        "Ambiguous items are dropped, not scored",
    ):
        assert phrase in text


def test_a_missing_file_gives_no_items_and_the_path_is_per_repo():
    assert load_hand_items(hand_path("no-such-repo"), repo_name="x", base_commit=BASE) == []
    assert hand_path("shop").name == "shop.yaml"


@pytest.mark.parametrize(
    "text",
    [
        "items: nope",
        "items:\n  - kind: guess\n    question: q",
        "items:\n  - kind: flow\n    question: q",
        "items:\n  - kind: unanswerable\n    question: q\n    required_files: [a.py]",
        "items:\n  - kind: flow\n    required_files: [a.py]",
    ],
)
def test_malformed_entries_are_rejected(tmp_path, text):
    path = tmp_path / "bad.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(HandError):
        load_hand_items(path, repo_name="x", base_commit=BASE)
