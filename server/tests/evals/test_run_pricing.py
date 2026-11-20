"""The price table: refused while empty, and the cost of a call worked out by hand."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from evals.run.pricing import PRICES_PATH, PricesIncomplete, PriceTable, UnpricedUsage
from evals.run.records import Usage
from tests.evals.run_helpers import EMBEDDING, GENERATOR, complete_table

pytestmark = pytest.mark.unit

PEAK = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
OFF_PEAK = datetime(2026, 11, 19, 20, 0, tzinfo=UTC)


class TestShippedTable:
    def test_it_is_filled_dated_and_verified_for_every_model_the_harness_calls(self):
        from evals.models import GENERATOR_MODEL, JUDGE_MODEL, PHRASER_MODEL

        table = PriceTable.load(PRICES_PATH)

        assert table.verified and table.as_of is not None
        table.require_complete([GENERATOR_MODEL, JUDGE_MODEL, PHRASER_MODEL, EMBEDDING])

    def test_the_generator_is_priced_by_deepseeks_weekday_peak_hours(self):
        from evals.models import GENERATOR_MODEL

        table = PriceTable.load(PRICES_PATH)
        thursday_peak = datetime(2026, 11, 19, 2, 30, tzinfo=UTC)
        thursday_gap = datetime(2026, 11, 19, 5, 0, tzinfo=UTC)
        saturday = datetime(2026, 11, 21, 2, 30, tzinfo=UTC)
        call = Usage(
            provider="deepseek",
            model=GENERATOR_MODEL,
            kind="generate",
            input_tokens=1_000_000,
            output_tokens=0,
        )

        assert not table.is_off_peak(thursday_peak)
        assert table.is_off_peak(thursday_gap) and table.is_off_peak(saturday)
        assert table.cost(call, thursday_peak) == pytest.approx(2 * table.cost(call, saturday))

    def test_it_pins_every_model_the_harness_calls(self):
        from evals.models import GENERATOR_MODEL, JUDGE_MODEL

        table = PriceTable.load(PRICES_PATH)

        assert {GENERATOR_MODEL, JUDGE_MODEL} <= set(table.models)
        assert "text-embedding-3-small" in table.embeddings


class TestPeakHours:
    @staticmethod
    def table() -> PriceTable:
        return complete_table(
            off_peak={"start_utc": None, "end_utc": None},
            peak_hours={
                "days": [1, 2, 3, 4, 5],
                "windows_utc": [["01:00", "04:00"], ["06:00", "10:00"]],
            },
        )

    @pytest.mark.parametrize(
        ("moment", "off_peak"),
        [
            (datetime(2026, 11, 19, 0, 59, tzinfo=UTC), True),
            (datetime(2026, 11, 19, 1, 0, tzinfo=UTC), False),
            (datetime(2026, 11, 19, 3, 59, tzinfo=UTC), False),
            (datetime(2026, 11, 19, 4, 0, tzinfo=UTC), True),
            (datetime(2026, 11, 19, 9, 0, tzinfo=UTC), False),
            (datetime(2026, 11, 19, 10, 0, tzinfo=UTC), True),
            (datetime(2026, 11, 22, 7, 0, tzinfo=UTC), True),
        ],
    )
    def test_membership_on_weekdays_and_weekends(self, moment, off_peak):
        assert self.table().is_off_peak(moment) is off_peak

    def test_the_window_satisfies_a_timed_model(self):
        self.table().require_complete([GENERATOR, EMBEDDING])

    def test_seconds_until_off_peak_is_the_end_of_the_current_window(self):
        table = self.table()

        assert table.seconds_until_off_peak(datetime(2026, 11, 19, 7, 30, tzinfo=UTC)) == 2.5 * 3600
        assert table.seconds_until_off_peak(datetime(2026, 11, 19, 5, 0, tzinfo=UTC)) == 0

    def test_bad_windows_are_rejected(self):
        with pytest.raises(ValueError):
            complete_table(peak_hours={"windows_utc": [["04:00", "01:00"]]})
        with pytest.raises(ValueError):
            complete_table(peak_hours={"days": [0], "windows_utc": [["01:00", "02:00"]]})
        with pytest.raises(ValueError):
            complete_table(peak_hours={"windows_utc": []})


class TestRequireComplete:
    def test_a_filled_table_passes(self):
        complete_table().require_complete([GENERATOR, EMBEDDING, "gpt-6-luna"])

    def test_a_model_with_no_entry_is_refused(self):
        with pytest.raises(PricesIncomplete, match="mystery-model"):
            complete_table().require_complete(["mystery-model"])

    def test_an_unverified_or_undated_table_is_refused(self):
        with pytest.raises(PricesIncomplete, match="verified"):
            complete_table(verified=False).require_complete([GENERATOR])
        with pytest.raises(PricesIncomplete, match="as_of"):
            complete_table(as_of=None).require_complete([GENERATOR])

    def test_a_peak_priced_model_needs_the_off_peak_window(self):
        table = complete_table(off_peak={"start_utc": None, "end_utc": None})

        with pytest.raises(PricesIncomplete, match="off_peak.start_utc"):
            table.require_complete([GENERATOR])
        table.require_complete(["gpt-6-luna"])  # a flat-rate model does not need it

    def test_one_missing_rate_is_named(self):
        models = {
            "gpt-6-luna": {"rates": {"input_cache_miss": 1.0, "input_cache_hit": None, "output": 2}}
        }

        with pytest.raises(PricesIncomplete) as refusal:
            complete_table(models=models).require_complete(["gpt-6-luna"])

        assert refusal.value.missing == ["gpt-6-luna.rates.input_cache_hit"]

    def test_a_model_may_not_mix_flat_and_timed_rates(self):
        rates = {"input_cache_miss": 1.0, "input_cache_hit": 0.1, "output": 2.0}

        with pytest.raises(ValueError, match="not both"):
            complete_table(models={"m": {"rates": rates, "peak": rates, "off_peak": rates}})


class TestCost:
    # 1M input of which 400k are cache hits, and 200k output.
    CALL = Usage(
        provider="deepseek",
        model=GENERATOR,
        kind="generate",
        input_tokens=1_000_000,
        cached_input_tokens=400_000,
        output_tokens=200_000,
    )

    def test_peak_cost_splits_cached_from_uncached_input(self):
        # 600k * $1.00 + 400k * $0.10 + 200k * $2.00, per 1M.
        assert complete_table().cost(self.CALL, PEAK) == pytest.approx(0.6 + 0.04 + 0.4)

    def test_off_peak_cost_uses_the_off_peak_rates(self):
        # 600k * $0.50 + 400k * $0.05 + 200k * $1.00, per 1M.
        assert complete_table().cost(self.CALL, OFF_PEAK) == pytest.approx(0.3 + 0.02 + 0.2)

    def test_a_flat_rate_model_ignores_the_time_of_day(self):
        call = self.CALL.model_copy(update={"model": "gpt-6-luna"})
        table = complete_table()

        assert table.cost(call, PEAK) == table.cost(call, OFF_PEAK) == pytest.approx(1.04)

    def test_a_reported_cost_wins_over_the_table(self):
        call = self.CALL.model_copy(update={"reported_cost_usd": 0.0003})

        assert complete_table().cost(call, PEAK) == 0.0003

    def test_a_reported_cost_needs_no_price_for_its_model(self):
        call = Usage(provider="cohere", model="rerank-v4", kind="rerank", reported_cost_usd=3e-6)

        assert complete_table().cost(call, PEAK) == 3e-6

    def test_an_embedding_is_priced_by_its_input_tokens(self):
        call = Usage(provider="openai", model=EMBEDDING, kind="embed", input_tokens=500_000)

        assert complete_table().cost(call, PEAK) == pytest.approx(0.01)

    def test_a_dated_snapshot_is_priced_as_its_base_model(self):
        call = self.CALL.model_copy(update={"model": f"{GENERATOR}-20261101"})

        assert complete_table().cost(call, PEAK) == pytest.approx(1.04)

    def test_tokens_of_an_unknown_model_are_refused_but_an_empty_call_is_free(self):
        unknown = self.CALL.model_copy(update={"model": "mystery"})

        with pytest.raises(UnpricedUsage, match="mystery"):
            complete_table().cost(unknown, PEAK)
        assert complete_table().cost(Usage(provider="x", model="mystery", kind="other"), PEAK) == 0

    def test_a_rate_left_unset_cannot_price_a_call(self):
        unset = {"input_cache_miss": None, "input_cache_hit": 0.1, "output": 2.0}
        table = complete_table(models={GENERATOR: {"peak": unset, "off_peak": unset}})
        with pytest.raises(PricesIncomplete):
            table.cost(self.CALL, OFF_PEAK.replace(hour=1))


class TestOffPeakWindow:
    """The window of the tests, 16:30 to 00:30, wraps past midnight."""

    @pytest.mark.parametrize(
        ("hour", "minute", "expected"),
        [(12, 0, False), (16, 29, False), (16, 30, True), (23, 59, True), (0, 29, True)]
        + [(0, 30, False), (3, 0, False)],
    )
    def test_membership_at_the_edges(self, hour, minute, expected):
        moment = datetime(2026, 11, 19, hour, minute, tzinfo=UTC)

        assert complete_table().is_off_peak(moment) is expected

    def test_a_window_inside_one_day(self):
        table = complete_table(off_peak={"start_utc": "02:00", "end_utc": "06:00"})

        assert table.is_off_peak(datetime(2026, 11, 19, 3, tzinfo=UTC))
        assert not table.is_off_peak(datetime(2026, 11, 19, 6, tzinfo=UTC))

    def test_other_time_zones_are_converted_and_naive_times_are_utc(self):
        table = complete_table()
        plus_two = timezone(timedelta(hours=2))

        assert table.is_off_peak(datetime(2026, 11, 19, 19, 0, tzinfo=plus_two))  # 17:00 UTC
        assert not table.is_off_peak(datetime(2026, 11, 19, 12, 0, tzinfo=plus_two))  # 10:00 UTC
        assert table.is_off_peak(datetime(2026, 11, 19, 20, 0))  # naive 20:00 is UTC

    def test_seconds_until_it_opens(self):
        table = complete_table()

        assert table.seconds_until_off_peak(PEAK) == 4.5 * 3600
        assert table.seconds_until_off_peak(OFF_PEAK) == 0
        # 00:45 is past the close; the next opening is 16:30 the same day.
        assert table.seconds_until_off_peak(datetime(2026, 11, 19, 0, 45, tzinfo=UTC)) == (
            15 * 3600 + 45 * 60
        )

    def test_an_unset_window_is_an_error_not_a_guess(self):
        table = complete_table(off_peak={"start_utc": None, "end_utc": None})
        with pytest.raises(PricesIncomplete, match="off_peak"):
            table.is_off_peak(PEAK)

    def test_an_empty_window_is_rejected(self):
        with pytest.raises(ValueError, match="same time"):
            complete_table(off_peak={"start_utc": "01:00", "end_utc": "01:00"})
