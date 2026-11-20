"""The budget: charging, the stop rule, rebuilding spend, and projecting a larger run."""

from datetime import UTC, datetime

import pytest

from evals.run.budget import (
    Budget,
    BudgetStop,
    ProjectionPlan,
    UnpricedSpend,
    project,
    spent_in,
)
from evals.run.records import Generation, RouteRecord, Usage
from tests.evals.run_helpers import GENERATOR, complete_table, usage_call

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


def generation(arm="classic", cost=0.1, *, key=None, **fields):
    return Generation(
        record_key=key or f"{arm}-{cost}-{fields.get('repeat', 0)}-{len(fields)}-{id(fields)}",
        item_id="item",
        arm=arm,
        config_hash="h",
        model=GENERATOR,
        cost_usd=cost,
        **fields,
    )


class TestBudget:
    def test_charging_adds_the_priced_cost_and_returns_it(self):
        tracker = Budget(cap_usd=10, stop_usd=9.5)

        added = tracker.charge([usage_call(), usage_call(tokens=200_000)], complete_table(), NOW)

        assert added == pytest.approx(0.30) and tracker.spent_usd == pytest.approx(0.30)
        assert tracker.remaining_usd == pytest.approx(9.70)

    def test_a_reported_cost_is_charged_as_reported(self):
        cohere = Usage(provider="cohere", model="rerank", kind="rerank", reported_cost_usd=3e-6)

        tracker = Budget(cap_usd=1, stop_usd=1)
        tracker.charge([cohere], complete_table(), NOW)

        assert tracker.spent_usd == 3e-6

    def test_the_stop_threshold_ends_the_run_and_below_it_does_not(self):
        tracker = Budget(cap_usd=10, stop_usd=9.5, spent_usd=9.49)
        tracker.check_before_next()

        tracker.charge([usage_call(tokens=100_000)], complete_table(), NOW)  # now $9.59

        with pytest.raises(BudgetStop) as stop:
            tracker.check_before_next()
        assert stop.value.spent_usd == pytest.approx(9.59) and "9.50" in stop.value.reason

    def test_spend_exactly_at_the_stop_stops(self):
        with pytest.raises(BudgetStop):
            Budget(cap_usd=10, stop_usd=9.5, spent_usd=9.5).check_before_next()

    def test_would_exceed_looks_at_the_cap_not_the_stop(self):
        tracker = Budget(cap_usd=10, stop_usd=9.5, spent_usd=9.0)

        assert tracker.would_exceed(1.01) and not tracker.would_exceed(1.0)
        assert not tracker.would_exceed(None)  # no measurement, no prediction

    def test_usage_with_no_price_is_charged_where_it_can_be_and_then_reported(self):
        tracker = Budget(cap_usd=10, stop_usd=9.5)

        with pytest.raises(UnpricedSpend) as failure:
            tracker.charge([usage_call(), usage_call(model="mystery")], complete_table(), NOW)

        assert failure.value.models == ["mystery"]
        assert tracker.spent_usd == pytest.approx(0.10)  # the priced part is not lost

    def test_the_stop_must_not_pass_the_cap(self):
        with pytest.raises(ValueError, match="stop"):
            Budget(cap_usd=1, stop_usd=2)
        with pytest.raises(ValueError, match="stop"):
            Budget(cap_usd=1, stop_usd=0)


class TestRestore:
    def test_spend_is_rebuilt_from_generations_and_routes_without_counting_composed_twice(self):
        route = RouteRecord(
            item_id="item",
            resolved_preset="structural",
            target_arm="structural_rerank",
            cost_usd=0.00004,
        )
        records = [
            generation("classic", 0.10, key="a"),
            generation("hybrid", 0.25, key="b"),
            generation("hybrid", None, key="c"),  # written before it was priced
            generation("auto", 0.25004, key="d", composed_from="structural_rerank"),
        ]

        tracker = Budget(cap_usd=10, stop_usd=9.5, spent_usd=99)
        restored = tracker.restore(records, [route])

        assert restored == tracker.spent_usd == pytest.approx(0.35004)
        assert spent_in(records, [route]) == pytest.approx(0.35004)


class TestProjection:
    def test_mean_and_p95_per_arm_scale_to_the_planned_items(self):
        records = [
            generation("classic", cost, key=f"c{n}") for n, cost in enumerate([0.1, 0.2, 0.3, 0.4])
        ]

        projection = project(records, ProjectionPlan(arms=("classic",), items=100))

        (arm,) = projection.arms
        assert (arm.measured, arm.runs) == (4, 100)
        assert arm.mean_usd == pytest.approx(0.25) and arm.p95_usd == 0.4
        assert arm.expected_usd == pytest.approx(25.0) and arm.high_usd == pytest.approx(40.0)
        assert projection.expected_usd == pytest.approx(25.0)

    def test_agent_arms_repeat_on_the_subset_only(self):
        records = [generation("agent", 1.0, key="a1"), generation("classic", 0.1, key="c1")]

        projection = project(
            records,
            ProjectionPlan(arms=("classic", "agent"), items=50, repeats=3, repeats_subset=10),
        )

        runs = {arm.arm: arm.runs for arm in projection.arms}
        assert runs == {"classic": 50, "agent": 50 + 2 * 10}
        assert projection.expected_usd == pytest.approx(50 * 0.1 + 70 * 1.0)

    def test_auto_projects_only_its_decision_because_its_target_is_in_the_plan(self):
        route = RouteRecord(
            item_id="item", resolved_preset="x", target_arm="classic", cost_usd=0.00004
        )
        records = [generation("auto", 0.10004, key="a", composed_from="classic", route=route)]

        projection = project(records, ProjectionPlan(arms=("auto",), items=100))

        assert projection.expected_usd == pytest.approx(100 * 0.00004)

    def test_arms_with_no_measurement_are_listed_not_guessed(self):
        projection = project(
            [generation("classic", 0.1, key="a")],
            ProjectionPlan(arms=("classic", "hybrid"), items=10),
        )

        assert projection.unmeasured == ["hybrid"]
        assert projection.expected_usd == pytest.approx(1.0)

    def test_a_superseded_error_does_not_count_twice_and_unpriced_records_are_skipped(self):
        records = [
            generation("classic", 0.5, key="same", status="error", error="boom"),
            generation("classic", 0.1, key="same"),
            generation("classic", None, key="unpriced"),
        ]

        projection = project(records, ProjectionPlan(arms=("classic",), items=10))

        assert projection.arms[0].measured == 1
        assert projection.expected_usd == pytest.approx(1.0)
