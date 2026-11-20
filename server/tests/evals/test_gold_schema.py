"""The gold item schema, ids and the canonical JSONL form."""

import json

import pytest
from pydantic import ValidationError

from evals.gold.schema import GoldItem, compute_id, make_item, read_jsonl, write_jsonl

pytestmark = pytest.mark.unit

BASE = "a" * 40


def _changeset(**over):
    fields = dict(
        repo="r",
        base_commit=BASE,
        family="changeset",
        template="changeset.blind",
        question_seed="Add retries",
        gold_files=("b.py", "a.py"),
        gold_prs=(7,),
        gold_commits=("c" * 40,),
        merges_since_base=0,
        cluster="r#7",
    )
    fields.update(over)
    return make_item(**fields)


def test_the_id_is_a_content_hash_of_the_defining_fields():
    item = _changeset()
    assert item.id == compute_id(item.model_dump())
    assert len(item.id) == 16
    assert item.gold_files == ("a.py", "b.py")
    assert _changeset(gold_files=("a.py", "b.py")).id == item.id


def test_the_question_and_verdict_do_not_change_the_id():
    base = _changeset()
    assert _changeset(question="Phrased differently?").id == base.id
    assert _changeset(verified="correct").id == base.id
    assert _changeset(question_seed="Something else").id != base.id
    assert _changeset(gold_prs=(8,)).id != base.id


def test_a_changeset_item_needs_a_cluster_and_no_circularity():
    with pytest.raises(ValueError, match="cluster"):
        _changeset(cluster=None)
    with pytest.raises(ValueError, match="merges_since_base"):
        _changeset(merges_since_base=None)
    with pytest.raises(ValueError, match="not circular"):
        _changeset(circular_with=("graph",))


def test_circularity_is_fixed_by_family():
    common = dict(repo="r", base_commit=BASE, question_seed="q", gold_files=("a.py",))
    with pytest.raises(ValueError, match="circular_with"):
        make_item(family="structural", template="structural.importers", **common)
    with pytest.raises(ValueError, match="circular_with"):
        make_item(family="rationale", template="rationale.blame", **common)
    make_item(family="structural", template="structural.path", circular_with=("graph",), **common)
    make_item(family="rationale", template="rationale.blame", circular_with=("history",), **common)


def test_the_anchor_is_only_for_anchor_items_and_never_in_the_gold():
    with pytest.raises(ValueError, match="anchor"):
        _changeset(anchor_file="a.py")
    with pytest.raises(ValueError, match="must not be in gold_files"):
        _changeset(template="changeset.anchor", anchor_file="a.py")
    with pytest.raises(ValueError, match="needs an anchor_file"):
        _changeset(template="changeset.anchor")
    _changeset(template="changeset.anchor", anchor_file="z.py")


def test_test_files_must_be_a_subset_of_the_gold():
    with pytest.raises(ValueError, match="subset"):
        _changeset(gold_test_files=("t.py",))


def test_unknown_fields_are_rejected_and_items_are_frozen():
    with pytest.raises(ValidationError):
        GoldItem(
            id="x",
            repo="r",
            base_commit=BASE,
            family="hand",
            template="hand.flow",
            question_seed="q",
            surprise=1,
        )
    with pytest.raises(ValidationError):
        _changeset().id = "other"


def test_jsonl_is_sorted_canonical_and_round_trips(tmp_path):
    items = [_changeset(question_seed=f"seed {n}", question="Né?") for n in range(5)]
    path = write_jsonl(tmp_path / "out" / "items.jsonl", reversed(items))
    raw = path.read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n")
    lines = raw.decode("utf-8").split("\n")[:-1]
    assert [json.loads(line)["id"] for line in lines] == sorted(item.id for item in items)
    assert "Né?" in raw.decode("utf-8")
    assert read_jsonl(path) == sorted(items, key=lambda item: item.id)
    assert write_jsonl(tmp_path / "again.jsonl", items).read_bytes() == raw
