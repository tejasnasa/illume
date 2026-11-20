"""Answer, citation, cost and routing metrics beyond the self-test."""

from datetime import UTC, datetime

import pytest

from evals.arms import AUTO
from evals.gold.schema import make_item
from evals.metrics.answer import answer_file_scores
from evals.metrics.citations import citation_scores
from evals.metrics.cost import generation_cost, percentile
from evals.metrics.routing import ROUTABLE_ARMS
from evals.run.adapters import AUTO_ARM_BY_PRESET
from evals.run.pricing import PriceTable
from evals.run.records import Usage
from tests.evals.metric_helpers import make_candidate, make_generation, make_step

pytestmark = pytest.mark.unit

BASE = "a" * 40


def _item(**over):
    fields = dict(
        repo="r",
        base_commit=BASE,
        family="hand",
        template="hand.flow",
        question="q",
        question_seed="q",
        gold_files=("a.py", "b.py"),
    )
    fields.update(over)
    return make_item(**fields)


def test_an_error_generation_is_refused_by_every_scorer():
    broken = make_generation(status="error", error="boom")
    with pytest.raises(ValueError):
        answer_file_scores(_item(), broken, {"a.py"})
    with pytest.raises(ValueError):
        citation_scores(broken, {"a.py"})


def test_a_classic_answer_that_cites_nothing_has_no_citation_rate():
    generation = make_generation("Files: a.py", candidates=[make_candidate("F:a.py", 1)])
    scores = citation_scores(generation, {"a.py"})
    assert scores.cited == 0 and scores.unresolved_rate is None


def test_agent_evidence_resolves_a_citation():
    generation = make_generation(
        "Look at [F:a.py:5-9].", steps=[make_step(0, evidence_keys=["F:a.py:1-20"])]
    )
    assert citation_scores(generation, {"a.py"}).unresolved == 0


def test_routable_arms_match_the_arms_the_adapter_composes():
    assert set(ROUTABLE_ARMS) == set(AUTO_ARM_BY_PRESET.values())
    assert AUTO == "auto"


def test_cost_prefers_the_recorded_figure_and_otherwise_prices_usages():
    usage = Usage(provider="p", model="m", kind="generate", reported_cost_usd=0.25)
    assert generation_cost(make_generation(cost_usd=1.5, usages=[usage])) == 1.5
    assert generation_cost(make_generation(usages=[usage])) == 0.25
    table = PriceTable(version="t")
    with pytest.raises(ValueError):
        generation_cost(make_generation(usages=[usage]), table)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert generation_cost(make_generation(usages=[usage]), table, now) == 0.25


def test_percentile_is_monotone_in_q():
    values = [3.0, 1.0, 9.0, 4.0, 7.0]
    results = [percentile(values, q) for q in (0, 25, 50, 75, 95, 100)]
    assert results == sorted(results) and results[0] == 1.0 and results[-1] == 9.0
