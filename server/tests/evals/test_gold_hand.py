"""Loading hand-written questions."""

import pytest

from evals.gold.hand import HAND_DIR, HandError, hand_path, load_hand_items

pytestmark = pytest.mark.unit

BASE = "c" * 40


def test_the_example_file_parses():
    items = load_hand_items(HAND_DIR / "example.yaml", repo_name="demo", base_commit=BASE)
    assert [item.template for item in items] == [
        "hand.explain",
        "hand.architecture",
        "hand.flow",
        "hand.unanswerable",
    ]
    _, architecture, flow, _ = items
    assert architecture.gold_files == ("app/middleware/auth.py",)
    assert architecture.acceptable_files == ("app/api/deps.py",)
    assert architecture.gold_answer_notes
    assert architecture.question == architecture.question_seed
    assert flow.tags == ("multi-file",)
    assert all(item.family == "hand" and item.circular_with == () for item in items)


def test_an_explain_item_carries_its_reference_answer_and_files():
    explain, *_ = load_hand_items(HAND_DIR / "example.yaml", repo_name="demo", base_commit=BASE)
    assert explain.template == "hand.explain"
    assert explain.reference_answer.startswith("The login route checks")
    assert "\n" not in explain.reference_answer
    assert explain.gold_files == ("app/api/auth.py", "app/middleware/auth.py")
    assert explain.acceptable_files == ("app/core/security.py",)


def test_the_older_kinds_load_without_a_reference_answer():
    _, architecture, flow, _ = load_hand_items(
        HAND_DIR / "example.yaml", repo_name="demo", base_commit=BASE
    )
    assert architecture.reference_answer == "" and flow.reference_answer == ""


def test_the_reference_answer_does_not_change_an_items_id(tmp_path):
    base = (
        "items:\n  - kind: flow\n    question: How is a session kept?\n    required_files: [a.py]\n"
    )
    ids = []
    for position, extra in enumerate(
        ("", "    reference_answer: Through a cookie.\n", "    reference_answer: A token.\n")
    ):
        path = tmp_path / f"{position}.yaml"
        path.write_text(base + extra, encoding="utf-8")
        (item,) = load_hand_items(path, repo_name="x", base_commit=BASE)
        ids.append(item.id)
    assert len(set(ids)) == 1


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
        "items:\n  - kind: explain\n    question: q\n    required_files: [a.py]",
        "items:\n  - kind: explain\n    question: q\n    required_files: [a.py]\n"
        "    reference_answer: [not, text]",
    ],
)
def test_malformed_entries_are_rejected(tmp_path, text):
    path = tmp_path / "bad.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(HandError):
        load_hand_items(path, repo_name="x", base_commit=BASE)
