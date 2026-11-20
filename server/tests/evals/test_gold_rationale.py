"""Rationale items on the sample repository with hand-made pull request mappings."""

from datetime import UTC, date, datetime

import pytest

from app.services.stack_detector import is_scannable
from evals.gold.rationale import answer_notes, build_rationale_items, is_candidate_line
from evals.mining.clones import default_tip, ensure_clone, files_at
from evals.mining.github_cache import CachedPR

pytestmark = pytest.mark.integration

LONG_BODY = (
    "## Why\n\n"
    "Rewrite the scanner so that it reports every file it skips during a run. "
    "This keeps the onboarding output honest when parsing fails halfway through.\n\n"
    "- Reviewers asked for it after the last incident in production last month.\n"
    "Short one. Nothing else matters here, only the **intent** of the change `matters`."
)
SHORT_BODY = "Tiny tweak, nothing to explain."


def _pr(number, sha, body):
    return CachedPR(
        number=number,
        title=f"Pull request {number}",
        body=body,
        author="ada",
        merged_at=datetime(2026, 2, 15, tzinfo=UTC),
        merge_commit_sha=sha,
        files=None,
        labels=(),
        user_type="User",
    )


@pytest.fixture
def clone(tmp_path, history):
    return ensure_clone(str(history.root), tmp_path / "clones", slug="fixture/sample")


def _build(clone, history, mapping, **kw):
    return build_rationale_items(
        repo_name="sample",
        clone=clone,
        base_commit=history.base,
        prs_by_merge_sha=mapping,
        tip=default_tip(clone),
        files=files_at(clone, history.base),
        seed=0,
        per_repo_target=50,
        generator_cutoff=date(2026, 1, 1),
        **kw,
    )


def test_an_item_links_the_line_to_its_pull_request_commit_and_file(clone, history):
    items = _build(clone, history, {history.first: _pr(101, history.first, LONG_BODY)})
    assert len(items) == 2
    at_base = files_at(clone, history.base)
    for item in items:
        assert item.family == "rationale" and item.template == "rationale.blame"
        assert item.gold_prs == (101,)
        assert item.gold_commits == (history.first,)
        assert len(item.gold_files) == 1 and item.gold_files[0] in at_base
        assert is_scannable(item.gold_files[0])
        assert item.question_seed.startswith(f"Why does `{item.gold_files[0]}` contain `")
        assert item.question_seed.endswith("`? What was the intent?")
        assert item.circular_with == ("history",)
        assert item.cluster == "sample#101"
        assert item.post_cutoff is True
        assert item.merges_since_base is None


def test_notes_are_sentences_quoted_from_the_body(clone, history):
    items = _build(clone, history, {history.first: _pr(101, history.first, LONG_BODY)})
    notes = items[0].gold_answer_notes
    assert 1 <= len(notes) <= 3
    for note in notes:
        assert note in LONG_BODY
        assert len(note.split()) >= 8
    assert notes[0].startswith("Rewrite the scanner")


def test_at_most_max_per_pr_items_come_from_one_pull_request(clone, history):
    mapping = {history.first: _pr(101, history.first, LONG_BODY)}
    assert len(_build(clone, history, mapping, max_per_pr=1)) == 1
    assert len(_build(clone, history, mapping, max_per_pr=2)) == 2


def test_a_pull_request_with_a_short_body_gives_no_items(clone, history):
    mapping = {
        history.first: _pr(101, history.first, SHORT_BODY),
        history.second: _pr(102, history.second, SHORT_BODY),
    }
    assert _build(clone, history, mapping) == []


def test_building_twice_gives_the_same_items(clone, history):
    mapping = {history.first: _pr(101, history.first, LONG_BODY)}
    assert _build(clone, history, mapping) == _build(clone, history, mapping)


@pytest.mark.unit
def test_candidate_lines():
    assert is_candidate_line("    total = compute_total(items, discount)")
    for line in (
        "    pass",
        "    return",
        "x = 1",
        "# a long comment that goes on and on and on",
        "import os, sys, collections, itertools",
        "from a.b import something_long_enough",
        '    """A docstring line that is long enough."""',
        "    })",
        "const fs = require('fs-extra-library')",
        "    " + "y = 1 + " * 30 + "1",
    ):
        assert not is_candidate_line(line), line


@pytest.mark.unit
def test_answer_notes_strip_markdown_and_skip_short_sentences():
    assert answer_notes(
        "Nothing else matters here, only the **intent** of the change `matters`. Short one."
    ) == ("Nothing else matters here, only the intent of the change matters.",)
    assert answer_notes("Too short. Also short.") == ()
