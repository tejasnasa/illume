"""A recall check over a realistic fixture repository, fast enough for every push.

Thirty files, 14 questions with known answers, run through the real pipeline
against the test Postgres with a deterministic fake embedder and no API key. The
point is to catch a retrieval regression the moment it is introduced instead of
at the next hand-run evaluation: a channel that stops returning, a fusion change
that buries a result, a graph walk that stops crossing barrels.

**What this does not measure.** The dense channel embeds with a hash of the text,
so it is noise: a question never lands within the 0.7 distance cut of any chunk,
and dense returns nothing at all. The check therefore guards the lexical, symbol,
grep, graph and co-change channels and the fusion between them. It says nothing
about embedding quality, which only a run against the real model can.

**Presets without a model.** Query rewrites need a model, and the ``jev`` reranker
needs ``OPENROUTER_API_KEY``. Neither is available here, and both degrade as they
do in production when the key is missing: the question is searched as typed and
the fused order is kept. The settings are blanked in the fixture so a developer's
``.env`` cannot change the result.

**The floors only move up.** Each constant below is the recall@10 measured on this
fixture, rounded down to the nearest 0.05. Raising one is how an improvement is
locked in. Lowering one means retrieval got worse, or the fixture changed, and
either is a reviewed change with the reason written in the pull request.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.file_cochange import FileCochange
from app.services.retrieval.candidate import Candidate
from app.services.retrieval.citations import commit_key
from app.services.retrieval.config import CLASSIC, HYBRID, STRUCTURAL, PipelineConfig
from app.services.retrieval.keys import key_for
from app.services.retrieval.pipeline import RetrievalResult, retrieve
from app.services.retrieval.resolve import SourceReference
from tests.factories import make_user
from tests.fixtures.retrieval import (
    EXPECTED_COCHANGE_PAIRS,
    RETRIEVAL_FIXTURE,
    RETRIEVAL_QUESTIONS,
    RetrievalQuestion,
    SeededRepo,
    make_context,
    matches_gold,
    rolled_back_session,
    seed_repo,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

K = 10

# The floors. See the module docstring: they only move up, and moving one is a
# reviewed change.
#
# Classic is a single dense search, and dense is noise here (see the module
# docstring), so its measured recall is 0.00 and its floor is trivially met. It is
# kept so the check fails loudly if Classic ever starts returning something it
# should not, and so the three presets are reported side by side.
#
# Hybrid measured 9/14 = 0.643: the lexical and symbol channels answer the identifier,
# README, history and plain-English questions, and miss the graph, co-change and grep
# questions. Structural measured 13/14 = 0.929: the graph, co-change and grep channels
# add those three. The one it still misses is the plain-English question that needs
# a stemmer.
CLASSIC_FLOOR = 0.00
HYBRID_FLOOR = 0.60
STRUCTURAL_FLOOR = 0.90

FLOORS = {"classic": CLASSIC_FLOOR, "hybrid": HYBRID_FLOOR, "structural": STRUCTURAL_FLOOR}

# Arms that are not presets, to isolate one channel at a time. Each differs from
# STRUCTURAL by exactly the channel named, and runs only on the questions that
# bear on that channel, which keeps the check to a few seconds.


def _without(config: PipelineConfig, kind: str, name: str) -> PipelineConfig:
    channels = tuple(channel for channel in config.channels if channel.kind != kind)
    return config.model_copy(update={"name": name, "channels": channels})


GRAPH_QUESTIONS = ("graph-direct", "graph-through-barrel")
COCHANGE_QUESTIONS = ("cochange",)
GREP_QUESTIONS = ("grep-long-function",)

# Arm name -> (config, the question ids it runs on; None means all of them).
ARMS: dict[str, tuple[PipelineConfig, tuple[str, ...] | None]] = {
    "classic": (CLASSIC, None),
    "hybrid": (HYBRID, None),
    "structural": (STRUCTURAL, None),
    "structural_no_graph": (_without(STRUCTURAL, "graph", "structural_no_graph"), GRAPH_QUESTIONS),
    "structural_no_cochange": (
        _without(STRUCTURAL, "cochange", "structural_no_cochange"),
        COCHANGE_QUESTIONS,
    ),
    "structural_no_grep": (_without(STRUCTURAL, "grep", "structural_no_grep"), GREP_QUESTIONS),
}


def recall_at_k(
    question: RetrievalQuestion, candidates: tuple[Candidate, ...], k: int = K
) -> float:
    """The share of the question's gold items matched by the top ``k`` candidates."""
    top = candidates[:k]
    found = [item for item in question.gold if any(matches_gold(c, item) for c in top)]
    return len(found) / len(question.gold)


def mean_recall(arm: str, outcomes: dict[str, dict[str, RetrievalResult]]) -> float:
    """Recall@10 averaged over every question for one arm."""
    scores = [
        recall_at_k(question, outcomes[arm][question.id].candidates)
        for question in RETRIEVAL_QUESTIONS
        if question.id in outcomes[arm]
    ]
    return sum(scores) / len(scores)


def _question(question_id: str) -> RetrievalQuestion:
    return next(q for q in RETRIEVAL_QUESTIONS if q.id == question_id)


def _hit_channels(result: RetrievalResult, item: str, k: int = K) -> set[str]:
    """Every channel that found a top-``k`` candidate satisfying a gold item."""
    return {
        hit.channel
        for candidate in result.candidates[:k]
        if matches_gold(candidate, item)
        for hit in candidate.channel_hits
    }


@dataclass
class Measured:
    """The seeded repository and every arm's result for every question.

    ``db`` stays open for the module so a test can look at the seeded rows.
    """

    db: AsyncSession
    seeded: SeededRepo
    results: dict[str, dict[str, RetrievalResult]]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def measured(engine):
    """Seeds the fixture once and runs every arm over every question.

    Seeding is by far the slowest part, so it happens once per module on a session
    that is rolled back at the end. The ``jev`` reranker and the query rewrites are
    switched off at the settings level: with no key they degrade, which is what
    this check wants, and a key in a developer's environment must not change that.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings, "OPENROUTER_API_KEY", "")
        patch.setattr(settings, "COHERE_API_KEY", "")
        async with rolled_back_session(engine) as db:
            seeded = await seed_repo(db, await make_user(db), RETRIEVAL_FIXTURE)
            results: dict[str, dict[str, RetrievalResult]] = {}
            for name, (config, only) in ARMS.items():
                results[name] = {}
                for question in RETRIEVAL_QUESTIONS:
                    if only is not None and question.id not in only:
                        continue
                    ctx = make_context(db, seeded.repo)
                    results[name][question.id] = await retrieve(config, question.text, ctx=ctx)
            yield Measured(db=db, seeded=seeded, results=results)


def _breakdown(arm: str, results: dict[str, dict[str, RetrievalResult]]) -> str:
    rows = [
        f"  {recall_at_k(q, results[arm][q.id].candidates):.2f}  {q.id}"
        for q in RETRIEVAL_QUESTIONS
    ]
    return "\n".join(rows)


# --- the fixture is what the questions assume -----------------------------------


async def test_fixture_matches_its_description(measured):
    seeded = measured.seeded

    assert len(seeded.files) == 30

    # The barrel holds only re-exports, so it is never a graph node of its own.
    barrel = [s for (path, _), s in seeded.symbols.items() if path == "app/auth/__init__.py"]
    assert barrel
    assert {s.kind for s in barrel} == {"import"}

    # The long function is stored but has no embedding row, so only grep and
    # symbol-name search can reach its body.
    long_key = ("app/billing/statements.py", "rebuild_monthly_statements")
    assert long_key in seeded.symbols
    assert long_key not in seeded.symbol_embeddings
    assert "LEGACY_PRORATION_CUTOFF" in seeded.symbols[long_key].source_code
    assert not any("LEGACY_PRORATION_CUTOFF" in e.chunk_text for e in seeded.embeddings)

    # The bulk commit touches more than 30 paths and must not have produced pairs.
    bulk = max(seeded.commits.values(), key=lambda c: len(c.changed_files_list))
    assert len(bulk.changed_files_list) > 30


async def test_cochange_pairs_are_the_derived_ones(measured):
    """The pairs come from the real builder; the bulk commit contributes none."""
    seeded = measured.seeded
    path_of = {file.id: path for path, file in seeded.files.items()}

    rows = (
        await measured.db.execute(
            select(FileCochange).where(FileCochange.repository_id == seeded.repo.id)
        )
    ).scalars()
    pairs = {frozenset({path_of[r.file_a_id], path_of[r.file_b_id]}) for r in rows}

    assert pairs == EXPECTED_COCHANGE_PAIRS


async def test_every_gold_item_exists_in_the_fixture(measured):
    seeded = measured.seeded
    commit_keys = {commit_key(h) for h in seeded.commits}
    pr_keys = {f"PR:{number}" for number in seeded.pull_requests}
    document_keys = {
        key_for(SourceReference(source_type="document", chunk_text=e.chunk_text))
        for e in seeded.embeddings
        if e.source_type == "document"
    }
    for question in RETRIEVAL_QUESTIONS:
        for item in question.gold:
            if item.startswith("C:"):
                assert item in commit_keys, f"{question.id}: {item}"
            elif item.startswith("PR:"):
                assert item in pr_keys, f"{question.id}: {item}"
            elif item.startswith("D:"):
                assert item in document_keys, f"{question.id}: {item}"
            else:
                assert item in seeded.files, f"{question.id}: {item} is not a fixture file"


# --- recall ----------------------------------------------------------------------


@pytest.mark.parametrize("arm", sorted(FLOORS))
async def test_recall_at_ten_stays_above_its_floor(arm, measured):
    recall = mean_recall(arm, measured.results)

    assert recall >= FLOORS[arm], (
        f"{arm} recall@{K} fell to {recall:.3f}, below the recorded floor {FLOORS[arm]:.2f}\n"
        + _breakdown(arm, measured.results)
    )


async def test_no_channel_failed_and_only_the_reranker_degraded(measured):
    for arm, by_question in measured.results.items():
        for question_id, result in by_question.items():
            failed = [t for t in result.trace.channels if t.error]
            assert not failed, f"{arm}/{question_id}: {failed}"
            stages = {event["stage"] for event in result.trace.degraded}
            assert stages <= {"rerank"}, f"{arm}/{question_id}: {result.trace.degraded}"


# --- structural properties ---------------------------------------------------------


async def test_structural_is_never_worse_than_hybrid_on_any_question(measured):
    for question in RETRIEVAL_QUESTIONS:
        hybrid = recall_at_k(question, measured.results["hybrid"][question.id].candidates)
        structural = recall_at_k(question, measured.results["structural"][question.id].candidates)
        assert structural >= hybrid, f"{question.id}: structural {structural} < hybrid {hybrid}"


async def test_presets_rank_classic_below_hybrid_below_structural(measured):
    classic, hybrid, structural = (
        mean_recall(arm, measured.results) for arm in ("classic", "hybrid", "structural")
    )

    assert classic < hybrid < structural


@pytest.mark.parametrize("question_id", GRAPH_QUESTIONS)
async def test_graph_only_answers_appear_only_when_the_graph_channel_is_on(question_id, measured):
    question = _question(question_id)
    results = measured.results

    assert recall_at_k(question, results["hybrid"][question_id].candidates) == 0
    assert recall_at_k(question, results["structural_no_graph"][question_id].candidates) == 0
    assert recall_at_k(question, results["structural"][question_id].candidates) == 1
    for item in question.gold:
        assert _hit_channels(results["structural"][question_id], item) == {"graph"}


async def test_cochange_only_answer_appears_only_when_the_cochange_channel_is_on(measured):
    question = _question("cochange")
    results = measured.results

    assert recall_at_k(question, results["hybrid"]["cochange"].candidates) == 0
    assert recall_at_k(question, results["structural_no_cochange"]["cochange"].candidates) == 0
    assert recall_at_k(question, results["structural"]["cochange"].candidates) == 1
    assert _hit_channels(results["structural"]["cochange"], question.gold[0]) == {"cochange"}


async def test_the_long_function_is_found_by_grep_and_by_nothing_else(measured):
    question = _question("grep-long-function")
    results = measured.results

    for arm in ("classic", "hybrid", "structural_no_grep"):
        assert recall_at_k(question, results[arm][question.id].candidates) == 0
    with_grep = results["structural"][question.id]
    assert recall_at_k(question, with_grep.candidates) == 1
    assert _hit_channels(with_grep, question.gold[0]) == {"grep"}


@pytest.mark.parametrize("question_id", ["exact-snake", "exact-camel"])
async def test_an_exact_identifier_is_found_by_name_and_by_text(question_id, measured):
    question = _question(question_id)

    found_by = _hit_channels(measured.results["hybrid"][question_id], question.gold[0])

    assert {"symbol", "lexical"} <= found_by


async def test_plain_words_find_a_camel_case_name_only_through_the_split_index(measured):
    question = _question("camel-in-words")

    found_by = _hit_channels(measured.results["hybrid"][question.id], question.gold[0])

    assert found_by == {"lexical"}
