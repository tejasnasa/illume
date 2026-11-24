"""The runner: resumable, keyed by content, budgeted, and never scoring an error as zero."""

import dataclasses
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.services.retrieval.config import DiversifyConfig
from evals.arms import ARMS, EVAL_AGENT_MAX_INPUT_TOKENS, EVAL_INSTRUCTION, get_arm
from evals.run.budget import Budget
from evals.run.generate import (
    GENERATIONS,
    MAX_ATTEMPTS,
    ROUTES,
    STOPPED,
    SUMMARY,
    RateLimiter,
    expected_key,
    final_records,
    generate,
    order_items,
    plan_pairs,
    read_generations,
    read_routes,
    subset_ids,
)
from evals.run.records import RouteRecord, RunTokens, Usage
from tests.evals.run_helpers import (
    GENERATOR,
    OFF_PEAK_CALL_COST,
    PEAK_CALL_COST,
    Crash,
    ScriptedExecutor,
    complete_table,
    make_items,
    usage_call,
)

pytestmark = pytest.mark.unit

NOON = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


def budget(cap: float = 100.0, stop: float | None = None) -> Budget:
    return Budget(cap_usd=cap, stop_usd=stop if stop is not None else cap)


async def run(tmp_path, items, arms, executor, **kwargs):
    kwargs.setdefault("budget", budget())
    kwargs.setdefault("table", complete_table())
    kwargs.setdefault("clock", lambda: NOON)
    kwargs.setdefault("retry_delay", 0.0)
    return await generate(
        items=items, arm_names=arms, run_dir=tmp_path / "run", executor=executor, **kwargs
    )


def records(tmp_path):
    return read_generations(tmp_path / "run" / GENERATIONS)


class TestResume:
    async def test_stopping_after_three_of_six_pairs_and_rerunning_gives_six_ok_records(
        self, tmp_path
    ):
        items = make_items(3)
        arms = ["classic", "hybrid"]

        with pytest.raises(Crash):
            await run(tmp_path, items, arms, ScriptedExecutor(crash_after=3))
        first = {r.record_key for r in records(tmp_path)}
        assert len(first) == 3

        second = ScriptedExecutor()
        result = await run(tmp_path, items, arms, second)

        final = final_records(records(tmp_path))
        assert len(final) == 6 and all(r.status == "ok" for r in final)
        assert len(second.calls) == 3  # the first three were not regenerated
        assert (result.ok, result.skipped, result.errors) == (3, 3, 0)
        assert first <= {r.record_key for r in final}

    async def test_a_finished_run_makes_no_calls_when_run_again(self, tmp_path):
        items = make_items(2)
        await run(tmp_path, items, ["classic"], ScriptedExecutor())

        again = ScriptedExecutor()
        result = await run(tmp_path, items, ["classic"], again)

        assert again.calls == [] and result.skipped == 2
        assert len(records(tmp_path)) == 2

    async def test_a_line_cut_short_by_a_crash_is_ignored(self, tmp_path):
        items = make_items(2)
        await run(tmp_path, items, ["classic"], ScriptedExecutor())
        path = tmp_path / "run" / GENERATIONS
        path.write_text(path.read_text(encoding="utf-8") + '{"record_key": "cut', encoding="utf-8")

        again = ScriptedExecutor()
        await run(tmp_path, items, ["classic"], again)

        assert again.calls == []


class TestKeys:
    async def test_a_changed_arm_config_regenerates_only_that_arm(self, tmp_path, monkeypatch):
        items = make_items(3)
        await run(tmp_path, items, ["classic", "hybrid"], ScriptedExecutor())

        classic = get_arm("classic")
        changed = dataclasses.replace(
            classic,
            config=classic.config.model_copy(update={"diversify": DiversifyConfig(total=11)}),
        )
        monkeypatch.setitem(ARMS, "classic", changed)
        again = ScriptedExecutor()
        await run(tmp_path, items, ["classic", "hybrid"], again)

        assert sorted({arm for _, arm, _ in again.calls}) == ["classic"]
        assert len(again.calls) == 3
        assert len(final_records(records(tmp_path))) == 9  # three stale classic records stay

    async def test_a_changed_question_regenerates_only_that_item(self, tmp_path):
        items = make_items(3)
        await run(tmp_path, items, ["classic", "hybrid"], ScriptedExecutor())

        rephrased = [items[0].model_copy(update={"question": "Asked another way?"}), *items[1:]]
        assert rephrased[0].id == items[0].id  # the id ignores the phrasing
        again = ScriptedExecutor()
        await run(tmp_path, rephrased, ["classic", "hybrid"], again)

        assert sorted(again.calls) == sorted(
            [(items[0].id, "classic", 0), (items[0].id, "hybrid", 0)]
        )

    def test_the_key_ignores_the_arm_name_but_not_the_model_or_the_repeat(self):
        item = make_items(1)[0]
        classic = get_arm("classic")
        renamed = dataclasses.replace(classic, name="renamed")
        other_model = dataclasses.replace(classic, model="another-model")

        assert expected_key(item, classic) == expected_key(item, renamed)
        assert expected_key(item, classic) != expected_key(item, other_model)
        assert expected_key(item, classic) != expected_key(item, classic, repeat=1)
        assert expected_key(item, classic) != expected_key(item, get_arm("hybrid"))

    def test_the_agent_key_carries_the_product_prompt_version(self, monkeypatch):
        import evals.run.generate as module

        item = make_items(1)[0]
        before = expected_key(item, get_arm("agent"))
        monkeypatch.setattr(module, "PROMPT_VERSION", "agent-next")

        assert expected_key(item, get_arm("agent")) != before

    async def test_the_instruction_is_part_of_the_key(self, tmp_path, monkeypatch):
        import evals.run.generate as module

        item = make_items(1)[0]
        before = expected_key(item, get_arm("classic"))
        monkeypatch.setattr(module, "EVAL_INSTRUCTION", EVAL_INSTRUCTION + " Be brief.")

        assert expected_key(item, get_arm("classic")) != before


class TestErrors:
    async def test_a_failing_pair_is_an_error_record_after_three_attempts_not_a_score(
        self, tmp_path
    ):
        items = make_items(2)
        victim = items[0].id
        executor = ScriptedExecutor(fail={(victim, "classic"): 99})

        result = await run(tmp_path, items, ["classic"], executor)

        (bad,) = [r for r in records(tmp_path) if r.item_id == victim]
        assert (bad.status, bad.error, bad.attempts) == ("error", "boom", MAX_ATTEMPTS)
        assert executor.calls.count((victim, "classic", 0)) == MAX_ATTEMPTS == 3
        assert (result.ok, result.errors) == (1, 1)
        # Every attempt was paid for and is on the record.
        assert bad.cost_usd == pytest.approx(3 * PEAK_CALL_COST)

    async def test_a_pair_that_recovers_on_a_retry_is_an_ok_record(self, tmp_path):
        items = make_items(1)
        executor = ScriptedExecutor(fail={(items[0].id, "classic"): 2})

        await run(tmp_path, items, ["classic"], executor)

        (record,) = records(tmp_path)
        assert (record.status, record.attempts) == ("ok", 3)
        assert record.cost_usd == pytest.approx(3 * PEAK_CALL_COST)

    async def test_an_exception_becomes_an_error_record_naming_it(self, tmp_path):
        items = make_items(1)
        executor = ScriptedExecutor(raise_for={(items[0].id, "classic")})

        await run(tmp_path, items, ["classic"], executor)

        (record,) = records(tmp_path)
        assert record.status == "error"
        assert record.error == "RuntimeError: provider down"
        assert record.answer == "" and record.cost_usd == 0

    async def test_an_error_record_is_retried_on_the_next_run_and_only_ok_counts_as_done(
        self, tmp_path
    ):
        items = make_items(3)
        victim = items[1].id
        await run(tmp_path, items, ["classic"], ScriptedExecutor(fail={(victim, "classic"): 99}))

        again = ScriptedExecutor()
        await run(tmp_path, items, ["classic"], again)

        assert again.calls == [(victim, "classic", 0)]
        final = final_records(records(tmp_path))
        assert len(final) == 3 and all(r.status == "ok" for r in final)
        assert len(records(tmp_path)) == 4  # the superseded error line is kept, append-only


class TestBudget:
    async def test_crossing_the_stop_ends_the_run_before_the_next_pair(self, tmp_path):
        items = make_items(6)
        executor = ScriptedExecutor()

        result = await run(tmp_path, items, ["classic"], executor, budget=budget(1.0, 0.35))

        assert len(executor.calls) == 4  # $0.30 is under the stop, $0.40 is over
        assert len(records(tmp_path)) == 4 and all(r.status == "ok" for r in records(tmp_path))
        stopped = json.loads((tmp_path / "run" / STOPPED).read_text(encoding="utf-8"))
        assert stopped["spent_usd"] == pytest.approx(0.40)
        assert "stop" in stopped["reason"] and result.stopped == stopped["reason"]
        assert result.spent_usd == pytest.approx(0.40)

    async def test_a_resumed_run_rebuilds_its_spend_from_the_records(self, tmp_path):
        items = make_items(6)
        await run(tmp_path, items, ["classic"], ScriptedExecutor(), budget=budget(1.0, 0.35))

        fresh = budget(1.0, 0.45)
        executor = ScriptedExecutor()
        result = await run(tmp_path, items, ["classic"], executor, budget=fresh)

        assert len(executor.calls) == 1  # $0.40 carried over; the next brings it to $0.50
        assert result.spent_usd == pytest.approx(0.50)
        assert len(records(tmp_path)) == 5
        assert (tmp_path / "run" / STOPPED).exists()

    async def test_a_completed_run_removes_a_stale_stop_marker(self, tmp_path):
        items = make_items(2)
        await run(tmp_path, items, ["classic"], ScriptedExecutor(), budget=budget(1.0, 0.1))
        assert (tmp_path / "run" / STOPPED).exists()

        await run(tmp_path, items, ["classic"], ScriptedExecutor(), budget=budget(1.0, 0.9))

        assert not (tmp_path / "run" / STOPPED).exists()

    async def test_a_pair_that_would_pass_the_cap_is_not_started(self, tmp_path):
        items = make_items(6)
        executor = ScriptedExecutor()

        result = await run(tmp_path, items, ["classic"], executor, budget=budget(0.45, 0.45))

        assert len(executor.calls) == 4  # $0.40 spent; one more measured pair would reach $0.50
        assert "cap" in (result.stopped or "")

    async def test_every_attempt_of_a_failing_pair_is_charged(self, tmp_path):
        items = make_items(1)
        executor = ScriptedExecutor(fail={(items[0].id, "classic"): 99})
        tracker = budget()

        await run(tmp_path, items, ["classic"], executor, budget=tracker)

        assert tracker.spent_usd == pytest.approx(3 * PEAK_CALL_COST)

    async def test_usage_of_a_model_with_no_price_stops_the_run_but_keeps_the_record(
        self, tmp_path
    ):
        items = make_items(3)
        executor = ScriptedExecutor(usages=lambda item, arm: [usage_call(model="mystery")])

        result = await run(tmp_path, items, ["classic"], executor)

        assert len(executor.calls) == 1 and len(records(tmp_path)) == 1
        assert "mystery" in (result.stopped or "")

    async def test_the_composed_record_does_not_count_its_target_twice(self, tmp_path):
        items = make_items(2)

        async def router(item):
            return _route(item, "classic")

        tracker = budget()
        await run(
            tmp_path, items, ["classic", "auto"], ScriptedExecutor(), router=router, budget=tracker
        )

        assert tracker.spent_usd == pytest.approx(2 * PEAK_CALL_COST + 2 * ROUTE_COST)


class TestOrdering:
    def test_the_shuffle_is_deterministic_per_arm_and_ignores_input_order(self):
        items = make_items(12)

        first = [i.id for i in order_items(items, "classic", seed=7)]
        again = [i.id for i in order_items(list(reversed(items)), "classic", seed=7)]
        other_arm = [i.id for i in order_items(items, "hybrid", seed=7)]
        other_seed = [i.id for i in order_items(items, "classic", seed=8)]

        assert first == again
        assert sorted(first) == sorted(i.id for i in items)
        assert first != other_arm and first != other_seed

    def test_a_subset_is_deterministic_and_the_first_n_by_hash(self):
        items = make_items(20)

        chosen = subset_ids(items, 5, seed=3)

        assert chosen == subset_ids(list(reversed(items)), 5, seed=3)
        assert len(chosen) == 5 and set(chosen) <= {i.id for i in items}
        assert chosen != subset_ids(items, 5, seed=4)
        assert subset_ids(items, 8, seed=3)[:5] == chosen  # growing N only adds items

    async def test_a_subset_restricts_one_arm_and_is_recorded_in_the_manifest(self, tmp_path):
        items = make_items(10)
        executor = ScriptedExecutor()

        await run(tmp_path, items, ["classic", "hybrid"], executor, subsets={"hybrid": 4}, seed=3)

        by_arm = {
            arm: [i for i, a, _ in executor.calls if a == arm] for arm in ("classic", "hybrid")
        }
        assert len(by_arm["classic"]) == 10
        assert sorted(by_arm["hybrid"]) == sorted(subset_ids(items, 4, 3))
        manifest = json.loads((tmp_path / "run" / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["run"]["subsets"] == {"hybrid": 4} and manifest["run"]["seed"] == 3

    async def test_each_arm_runs_its_items_in_its_own_shuffled_order(self, tmp_path):
        items = make_items(8)
        executor = ScriptedExecutor()

        await run(tmp_path, items, ["classic", "hybrid"], executor, seed=5)

        for arm in ("classic", "hybrid"):
            ran = [i for i, a, _ in executor.calls if a == arm]
            assert ran == [i.id for i in order_items(items, arm, seed=5)]

    def test_agent_arms_repeat_on_a_subset_and_the_others_run_once(self):
        items = make_items(10)

        pairs = plan_pairs(
            items,
            [get_arm("classic"), get_arm("agent")],
            seed=1,
            repeats=3,
            repeats_subset=4,
        )

        agent = [p for p in pairs if p.arm.name == "agent"]
        assert len([p for p in pairs if p.arm.name == "classic"]) == 10
        assert len(agent) == 10 + 2 * 4
        repeated = {p.item.id for p in agent if p.repeat > 0}
        assert repeated == set(subset_ids(items, 4, seed=1))
        assert len({p.key for p in pairs}) == len(pairs)  # every repeat has its own key


class TestRateLimit:
    async def test_calls_to_one_provider_are_spaced_by_its_interval(self):
        now = [100.0]
        slept: list[float] = []

        async def sleep(seconds: float) -> None:
            slept.append(seconds)
            now[0] += seconds

        limiter = RateLimiter({"deepseek": 2.0}, clock=lambda: now[0], sleep=sleep)
        starts = []
        for _ in range(3):
            await limiter.wait("deepseek")
            starts.append(now[0])
        await limiter.wait("openai")  # no limit configured

        assert starts == [100.0, 102.0, 104.0]
        assert slept == [2.0, 2.0]

    async def test_the_runner_spaces_its_pairs_by_the_configured_interval(self, tmp_path):
        now = [0.0]

        async def sleep(seconds: float) -> None:
            now[0] += seconds

        starts: list[float] = []
        executor = ScriptedExecutor(on_call=lambda *_: starts.append(now[0]))

        await run(
            tmp_path,
            make_items(3),
            ["classic"],
            executor,
            min_intervals={"deepseek": 5.0},
            monotonic=lambda: now[0],
            sleep=sleep,
        )

        assert starts == [0.0, 5.0, 10.0]


class TestOffPeak:
    async def test_the_first_pair_waits_for_the_window_to_open(self, tmp_path):
        clock = [NOON]
        seen: list[datetime] = []

        async def sleep(seconds: float) -> None:
            clock[0] += timedelta(seconds=seconds)

        executor = ScriptedExecutor(on_call=lambda *_: seen.append(clock[0]))

        await run(
            tmp_path,
            make_items(2),
            ["classic"],
            executor,
            off_peak_only=True,
            clock=lambda: clock[0],
            sleep=sleep,
        )

        assert seen[0] == datetime(2026, 11, 19, 16, 30, tzinfo=UTC)
        assert all(r.cost_usd == pytest.approx(OFF_PEAK_CALL_COST) for r in records(tmp_path))

    async def test_it_pauses_when_the_window_closes_and_resumes_when_it_reopens(self, tmp_path):
        clock = [datetime(2026, 11, 19, 0, 0, tzinfo=UTC)]  # the window closes at 00:30
        seen: list[datetime] = []

        async def sleep(seconds: float) -> None:
            clock[0] += timedelta(seconds=seconds)

        def on_call(*_):
            seen.append(clock[0])
            clock[0] += timedelta(minutes=20)

        await run(
            tmp_path,
            make_items(3),
            ["classic"],
            ScriptedExecutor(on_call=on_call),
            off_peak_only=True,
            clock=lambda: clock[0],
            sleep=sleep,
        )

        assert seen[:2] == [
            datetime(2026, 11, 19, 0, 0, tzinfo=UTC),
            datetime(2026, 11, 19, 0, 20, tzinfo=UTC),
        ]
        assert seen[2] == datetime(2026, 11, 19, 16, 30, tzinfo=UTC)  # 00:40 was closed

    async def test_without_the_flag_pairs_run_at_peak_and_are_charged_peak_rates(self, tmp_path):
        await run(tmp_path, make_items(1), ["classic"], ScriptedExecutor())

        assert records(tmp_path)[0].cost_usd == pytest.approx(PEAK_CALL_COST)


ROUTE_COST = 0.00004


def _route(item, target, *, fail_to_route=False):
    return RouteRecord(
        item_id=item.id,
        route="local",
        confidence=0.95,
        resolved_preset="hybrid_rerank",
        target_arm=target,
        model="fake-router",
        usages=[
            Usage(
                provider="openrouter",
                model="fake-router",
                kind="decision",
                reported_cost_usd=ROUTE_COST,
            )
        ],
    )


class TestAuto:
    def make_router(self, targets, *, fail_for=()):
        calls = []

        async def router(item):
            calls.append(item.id)
            if item.id in fail_for:
                raise RuntimeError("router down")
            return _route(item, targets[item.id])

        router.calls = calls
        return router

    async def test_routes_are_resumable(self, tmp_path):
        items = make_items(3)
        targets = {i.id: "classic" for i in items}
        flaky = self.make_router(targets, fail_for={items[2].id})

        first = await run(tmp_path, items, ["classic", "auto"], ScriptedExecutor(), router=flaky)

        assert len(read_routes(tmp_path / "run" / ROUTES)) == 2 and first.route_errors == 1
        assert first.auto_written == 2

        second_router = self.make_router(targets)
        second = await run(
            tmp_path, items, ["classic", "auto"], ScriptedExecutor(), router=second_router
        )

        assert second_router.calls == [items[2].id]  # only the one that failed
        assert (second.routes_written, second.auto_written) == (1, 1)
        assert len(read_routes(tmp_path / "run" / ROUTES)) == 3

        third_router = self.make_router(targets)
        third = await run(
            tmp_path, items, ["classic", "auto"], ScriptedExecutor(), router=third_router
        )
        assert third_router.calls == [] and third.auto_written == 0

    async def test_missing_target_pairs_are_generated_only_for_the_routed_items(self, tmp_path):
        items = make_items(3)
        targets = {
            items[0].id: "classic",
            items[1].id: "classic",
            items[2].id: "structural_rerank",
        }
        executor = ScriptedExecutor()

        result = await run(
            tmp_path, items, ["classic", "auto"], executor, router=self.make_router(targets)
        )

        assert [call for call in executor.calls if call[1] == "structural_rerank"] == [
            (items[2].id, "structural_rerank", 0)
        ]
        assert sorted(a for _, a, _ in executor.calls).count("classic") == 3
        assert result.auto_written == 3
        auto = {r.item_id: r for r in records(tmp_path) if r.arm == "auto"}
        assert {i: r.composed_from for i, r in auto.items()} == {
            items[0].id: "classic",
            items[1].id: "classic",
            items[2].id: "structural_rerank",
        }

    async def test_a_subset_on_auto_routes_only_those_items_and_reuses_their_answers(
        self, tmp_path
    ):
        items = make_items(10)
        targets = {item.id: "classic" for item in items}
        router = self.make_router(targets)
        executor = ScriptedExecutor()

        result = await run(
            tmp_path,
            items,
            ["classic", "auto"],
            executor,
            router=router,
            subsets={"classic": 3, "auto": 3},
            seed=3,
        )

        chosen = sorted(subset_ids(items, 3, 3))
        assert sorted(router.calls) == chosen
        assert sorted(i for i, _, _ in executor.calls) == chosen  # no fill generations
        assert result.auto_written == 3

    async def test_auto_records_carry_the_route_and_the_decision_cost(self, tmp_path):
        items = make_items(1)
        targets = {items[0].id: "classic"}

        await run(
            tmp_path,
            items,
            ["classic", "auto"],
            ScriptedExecutor(),
            router=self.make_router(targets),
        )

        by_arm = {r.arm: r for r in records(tmp_path)}
        auto, target = by_arm["auto"], by_arm["classic"]
        assert auto.route is not None and auto.route.target_arm == "classic"
        assert auto.composed_from == "classic" and auto.answer == target.answer
        assert auto.record_key != target.record_key and auto.config_hash != target.config_hash
        assert [u.kind for u in auto.usages] == ["generate", "decision"]
        assert auto.cost_usd == pytest.approx(PEAK_CALL_COST + ROUTE_COST)
        assert auto.route.cost_usd == pytest.approx(ROUTE_COST)

    async def test_an_errored_target_makes_an_error_auto_record_that_is_not_repeated(
        self, tmp_path
    ):
        items = make_items(1)
        targets = {items[0].id: "classic"}
        executor = ScriptedExecutor(fail={(items[0].id, "classic"): 99})

        await run(tmp_path, items, ["classic", "auto"], executor, router=self.make_router(targets))
        await run(
            tmp_path,
            items,
            ["classic", "auto"],
            ScriptedExecutor(fail={(items[0].id, "classic"): 99}),
            router=self.make_router(targets),
        )

        autos = [r for r in records(tmp_path) if r.arm == "auto"]
        assert [r.status for r in autos] == ["error"]  # written once, not once per run

    async def test_the_auto_arm_needs_a_router(self, tmp_path):
        with pytest.raises(ValueError, match="router"):
            await run(tmp_path, make_items(1), ["auto"], ScriptedExecutor())

    async def test_no_target_means_no_auto_record_for_a_stopped_run(self, tmp_path):
        items = make_items(3)
        targets = {i.id: "classic" for i in items}

        result = await run(
            tmp_path,
            items,
            ["classic", "auto"],
            ScriptedExecutor(),
            router=self.make_router(targets),
            budget=budget(1.0, 0.1),
        )

        assert result.stopped and result.auto_written == 0
        assert [r for r in records(tmp_path) if r.arm == "auto"] == []


class TestMeterCheck:
    def agent_usages(self, metered: dict[str, int]):
        def usages(item, arm):
            tokens = metered[item.id]
            return [usage_call("agent", tokens=tokens)]

        return usages

    async def test_the_gap_is_stored_per_record_and_summarised_per_arm(self, tmp_path):
        items = make_items(2)

        async def executor(item, arm, repeat):
            full = await inner(item, arm, repeat)
            counted = RunTokens(input_tokens=100_000, output_tokens=0)
            return full.model_copy(update={"run_tokens": counted})

        inner = ScriptedExecutor(
            usages=self.agent_usages({items[0].id: 100_000, items[1].id: 40_000})
        )

        result = await run(tmp_path, items, ["agent"], executor)

        gaps = {r.item_id: r.meter_gap_tokens for r in records(tmp_path)}
        assert gaps == {items[0].id: 0, items[1].id: -60_000}
        check = result.summary["meter_check"]["agent"]
        assert check["runs"] == 2 and check["min_gap_tokens"] == -60_000
        assert (check["metered_tokens"], check["product_tokens"]) == (140_000, 200_000)
        assert check["suspect"] is True
        saved = json.loads((tmp_path / "run" / SUMMARY).read_text(encoding="utf-8"))
        assert saved["meter_check"]["agent"]["suspect"] is True

    async def test_a_matching_meter_is_not_suspect(self, tmp_path):
        items = make_items(2)

        async def executor(item, arm, repeat):
            full = await inner(item, arm, repeat)
            return full.model_copy(
                update={"run_tokens": RunTokens(input_tokens=100_000, output_tokens=0)}
            )

        inner = ScriptedExecutor(usages=self.agent_usages({i.id: 100_000 for i in items}))

        result = await run(tmp_path, items, ["agent"], executor)

        assert result.summary["meter_check"]["agent"]["suspect"] is False
        assert {r.meter_gap_tokens for r in records(tmp_path)} == {0}

    async def test_single_shot_arms_have_no_gap(self, tmp_path):
        await run(tmp_path, make_items(1), ["classic"], ScriptedExecutor())

        assert records(tmp_path)[0].meter_gap_tokens is None


class TestManifestAndSummary:
    async def test_the_manifest_records_what_produced_the_numbers(self, tmp_path):
        items = make_items(2)

        await run(
            tmp_path,
            items,
            ["classic", "agent"],
            ScriptedExecutor(),
            slice_name="pilot",
            split_hash="abc",
            manifest_overrides={"git": {"sha": "deadbeef", "dirty": False}, "uv_lock_sha256": "x"},
        )

        manifest = json.loads((tmp_path / "run" / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["arms"] == {
            "classic": get_arm("classic").config_hash(),
            "agent": get_arm("agent").config_hash(),
        }
        assert manifest["agent_token_cap"] == EVAL_AGENT_MAX_INPUT_TOKENS == 300_000
        assert manifest["eval_instruction"] == EVAL_INSTRUCTION
        assert manifest["price_table_version"] == "test-1" and manifest["split_hash"] == "abc"
        assert manifest["models"]["generator"] == GENERATOR
        assert manifest["prompt_version"].startswith("agent=agent-")
        assert manifest["corpus_pins"] == {items[0].repo: items[0].base_commit}
        run_settings = manifest["run"]
        assert run_settings["reranker_kind"] == "cohere" and run_settings["decider"] == "jev"
        assert run_settings["slice"] == "pilot" and run_settings["budget"]["cap_usd"] == 100.0
        assert manifest["reported_snapshots"] == {"generator": GENERATOR}

    async def test_the_summary_counts_pairs_errors_and_cost_per_arm(self, tmp_path):
        items = make_items(2)
        executor = ScriptedExecutor(fail={(items[0].id, "hybrid"): 99})

        result = await run(tmp_path, items, ["classic", "hybrid"], executor)

        summary = result.summary
        assert (summary["planned"], summary["ok"], summary["errors"]) == (4, 3, 1)
        assert summary["per_arm"]["classic"]["ok"] == 2
        assert summary["per_arm"]["hybrid"]["errors"] == 1
        assert summary["per_arm"]["classic"]["mean_cost_usd"] == pytest.approx(PEAK_CALL_COST)
        assert summary["spent_usd"] == pytest.approx(0.2 + 0.1 + 0.3)

    async def test_pairs_can_run_concurrently(self, tmp_path):
        items = make_items(6)
        executor = ScriptedExecutor()

        await run(tmp_path, items, ["classic", "hybrid"], executor, concurrency=4)

        final = final_records(records(tmp_path))
        assert len(final) == 12 and len({r.record_key for r in final}) == 12
        assert len(executor.calls) == 12
