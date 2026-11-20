"""Phrasing with a scripted model: leak re-check, retry, drop, cache and duplicates."""

import copy
import json
from types import SimpleNamespace

import pytest

from evals.gold.changeset import LeakContext
from evals.gold.phrase import (
    PROMPT_VERSION,
    dedupe_questions,
    named_files,
    normalise_question,
    phrase_items,
)
from evals.gold.schema import make_item
from tests.fixtures.agent_run import ScriptedModel, Turn, build_response, say

pytestmark = pytest.mark.unit

BASE = "a" * 40
GOLD = ("src/billing/invoice.py", "src/billing/tax.py")
ANCHOR = "src/api/routes.py"


class PlainModel(ScriptedModel):
    """A scripted model that answers a non-streaming call with a whole response."""

    async def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        reply = self._script.pop(0)
        if reply.error is not None:
            raise reply.error
        return build_response(reply)


def _factory(model: ScriptedModel):
    return lambda: SimpleNamespace(responses=model)


def _context(item) -> LeakContext:
    return LeakContext(
        gold_paths=item.gold_files, is_gold_unique=lambda token: token == "compute_vat_total"
    )


def _blind(seed="Add VAT handling to the checkout total.", cluster="demo#1", **extra):
    return make_item(
        repo="demo",
        base_commit=BASE,
        family="changeset",
        template="changeset.blind",
        question_seed=seed,
        gold_files=GOLD,
        gold_prs=(1,),
        cluster=cluster,
        merges_since_base=0,
        **extra,
    )


def _anchor(seed="Add VAT handling to the checkout total.", cluster="demo#1"):
    return make_item(
        repo="demo",
        base_commit=BASE,
        family="changeset",
        template="changeset.anchor",
        question_seed=f"{seed}\n\nStart from `{ANCHOR}`.",
        gold_files=GOLD,
        anchor_file=ANCHOR,
        gold_prs=(1,),
        cluster=cluster,
        merges_since_base=0,
    )


def _rationale():
    return make_item(
        repo="demo",
        base_commit=BASE,
        family="rationale",
        template="rationale.blame",
        question_seed="Why does `src/billing/tax.py` contain `rate = 0.2`? What was the intent?",
        gold_files=("src/billing/tax.py",),
        gold_prs=(9,),
        circular_with=("history",),
        cluster="demo#9",
    )


def _structural():
    return make_item(
        repo="demo",
        base_commit=BASE,
        family="structural",
        template="structural.path",
        question_seed="How does `src/a.py` reach `src/c.py` through imports?",
        gold_files=("src/a.py", "src/b.py", "src/c.py"),
        circular_with=("graph",),
    )


def _hand():
    return make_item(
        repo="demo",
        base_commit=BASE,
        family="hand",
        template="hand.flow",
        question="What happens when a user logs in?",
        question_seed="What happens when a user logs in?",
        gold_files=("src/auth.py",),
    )


async def _run(items, replies, tmp_path, **kwargs):
    model = PlainModel(replies)
    result = await phrase_items(
        items,
        client_factory=_factory(model),
        cache_path=tmp_path / "phrased.jsonl",
        leak_context=_context,
        **kwargs,
    )
    return model, result


async def test_a_clean_output_is_accepted(tmp_path):
    item = _blind()
    model, result = await _run([item], [say("Can you add VAT to the total at checkout?")], tmp_path)
    assert [i.question for i in result.items] == ["Can you add VAT to the total at checkout?"]
    assert result.items[0].id == item.id
    assert result.drops == []
    assert len(model.requests) == 1
    assert "Add VAT handling" in json.dumps(model.requests[0]["input"])


async def test_a_leaking_first_output_then_a_clean_retry_is_accepted(tmp_path):
    item = _blind()
    model, result = await _run(
        [item],
        [say("Change invoice.py to add VAT."), say("Add VAT to the checkout total.")],
        tmp_path,
    )
    assert [i.question for i in result.items] == ["Add VAT to the checkout total."]
    assert len(model.requests) == 2
    retry = json.dumps(model.requests[1]["input"])
    assert "revealed something" in retry
    assert "invoice.py" in retry


async def test_two_leaking_outputs_drop_the_item(tmp_path):
    _, result = await _run(
        [_blind()],
        [say("Edit src/billing/tax.py."), say("Call compute_vat_total in the cart.")],
        tmp_path,
    )
    assert result.items == []
    assert [(d.reason, d.item_id) for d in result.drops] == [("leak", _blind().id)]
    assert "compute_vat_total" in result.drops[0].detail


async def test_an_empty_output_then_a_leak_drops_the_item(tmp_path):
    _, result = await _run([_blind()], [say("   "), say("Touch tax.py please.")], tmp_path)
    assert result.items == []
    assert result.drops[0].reason == "leak"


async def test_two_empty_outputs_drop_the_item_as_empty(tmp_path):
    _, result = await _run([_blind()], [say(""), say("")], tmp_path)
    assert [d.reason for d in result.drops] == ["empty"]


async def test_a_failed_call_counts_as_an_empty_output(tmp_path):
    _, result = await _run(
        [_blind()],
        [Turn(error=RuntimeError("boom")), say("Add VAT at checkout.")],
        tmp_path,
    )
    assert [i.question for i in result.items] == ["Add VAT at checkout."]


async def test_a_cached_item_makes_no_call_on_rerun(tmp_path):
    item = _blind()
    model, first = await _run([item], [say("Add VAT to the checkout total.")], tmp_path)
    assert first.calls == 1
    again, second = await _run([item], [], tmp_path)
    assert again.requests == []
    assert second.calls == 0
    assert second.cached == 1
    assert [i.question for i in second.items] == [i.question for i in first.items]
    record = json.loads((tmp_path / "phrased.jsonl").read_text().splitlines()[0])
    assert record["prompt_version"] == PROMPT_VERSION


async def test_a_different_model_does_not_reuse_the_cache(tmp_path):
    item = _blind()
    await _run([item], [say("Add VAT to the checkout total.")], tmp_path)
    model, result = await _run([item], [say("Add VAT at checkout.")], tmp_path, model="other")
    assert len(model.requests) == 1
    assert result.items[0].question == "Add VAT at checkout."


async def test_hand_items_are_not_sent_to_the_model(tmp_path):
    model, result = await _run([_hand()], [], tmp_path)
    assert model.requests == []
    assert result.items[0].question == "What happens when a user logs in?"


async def test_anchor_and_blind_of_one_pull_request_are_both_kept(tmp_path):
    same = "Add VAT handling to the checkout total."
    anchor_text = f"{same} Start from {ANCHOR}."
    _, result = await _run([_blind(), _anchor()], [say(same), say(anchor_text)], tmp_path)
    assert len(result.items) == 2
    assert result.drops == []


async def test_an_anchor_item_must_keep_its_anchor_file(tmp_path):
    _, result = await _run(
        [_anchor()], [say("Add VAT to the total."), say("Add VAT to the cart total.")], tmp_path
    )
    assert result.items == []
    assert "<dropped src/api/routes.py>" in result.drops[0].detail


async def test_an_anchor_item_may_name_its_anchor(tmp_path):
    _, result = await _run(
        [_anchor()], [say(f"Add VAT to the total, starting from {ANCHOR}.")], tmp_path
    )
    assert len(result.items) == 1


async def test_rationale_may_name_its_subject_file_but_not_other_gold(tmp_path):
    item = _rationale()
    assert named_files(item) == ("src/billing/tax.py",)
    _, ok = await _run([item], [say("Why is src/billing/tax.py using rate = 0.2?")], tmp_path)
    assert len(ok.items) == 1


async def test_structural_keeps_both_ends_and_flags_the_chain_between(tmp_path):
    item = _structural()
    assert named_files(item) == ("src/a.py", "src/c.py")
    _, ok = await _run([item], [say("How does src/a.py end up importing src/c.py?")], tmp_path)
    assert len(ok.items) == 1
    _, bad = await _run(
        [item],
        [say("Is src/b.py between src/a.py and src/c.py?")] * 2,
        tmp_path / "second",
    )
    assert bad.items == []
    assert "src/b.py" in bad.drops[0].detail


async def test_exact_and_near_duplicates_are_removed_smaller_id_kept(tmp_path):
    first = _blind(seed="seed one", cluster="demo#1")
    second = _blind(seed="seed two", cluster="demo#2")
    third = _blind(seed="seed three", cluster="demo#3")
    ordered = sorted([first, second, third], key=lambda item: item.id)
    distinct = "please add support for value added charges at the checkout total today ok"
    replies = [
        say("Add VAT to the checkout total!"),
        say("add  vat to the CHECKOUT total"),
        say(distinct),
    ]
    _, result = await _run(ordered, replies, tmp_path)
    assert [item.id for item in result.items][0] == ordered[0].id
    assert len(result.items) == 2
    assert [d.reason for d in result.drops] == ["duplicate_exact"]
    assert result.drops[0].detail == ordered[0].id


def test_near_duplicates_use_token_set_overlap():
    base = " ".join(f"word{n}" for n in range(10))
    one = _blind(seed="s1", cluster="demo#1").model_copy(update={"question": base})
    two = _blind(seed="s2", cluster="demo#2").model_copy(update={"question": base + " extra"})
    far = _blind(seed="s3", cluster="demo#3").model_copy(update={"question": "other text here"})
    kept, drops = dedupe_questions([one, two, far])
    assert [d.reason for d in drops] == ["duplicate_near"]
    assert len(kept) == 2


def test_duplicates_are_only_compared_within_a_repository():
    one = _blind(seed="s1", cluster="demo#1").model_copy(update={"question": "same words"})
    other = make_item(
        repo="elsewhere",
        base_commit=BASE,
        family="structural",
        template="structural.path",
        question_seed="x `a.py` `b.py`",
        gold_files=("a.py",),
        circular_with=("graph",),
    ).model_copy(update={"question": "same words"})
    kept, drops = dedupe_questions([one, other])
    assert len(kept) == 2 and drops == []


def test_normalisation_lowercases_strips_punctuation_and_collapses_whitespace():
    assert normalise_question("  Hello,   WORLD!! ") == "hello world"
