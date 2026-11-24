"""The generation runner: every item on every arm, resumable, budgeted and append-only.

The runner writes one JSONL line per finished pair into the run directory and never rewrites a
line. A record is keyed by a hash of everything that affects the answer (see
:func:`~evals.run.records.record_key`), so a restarted run skips the pairs that already finished
``ok``, regenerates the ones whose item, arm configuration, prompt, model or instruction changed,
and retries the ones that ended as errors. Where a key appears more than once the last line wins.

What a pair is allowed to do:

* An error is retried up to twice; the last failure is written as an error record, never a score
  of zero.
* The spend limit is checked before each pair starts, never inside one, so a stop leaves no
  half-finished pair. Spend is rebuilt from the records on disk when a run resumes.
* Calls are spaced per provider, and with ``off_peak_only`` a pair waits for the provider's
  off-peak window before it starts.

``auto`` is composed, not generated: one routing decision per item, then the generation of the
arm that decision picks, copied. Any target arm without a generation for a routed item is
generated first.

The model calls themselves are made by an injected ``executor``; this module knows nothing about
providers, sessions or clones. Library code here takes nothing from ``evals.settings``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.agent.prompts import PROMPT_VERSION
from app.services.retrieval.embedding import EMBEDDING_MODEL
from evals.arms import (
    AUTO,
    DECIDER,
    EVAL_AGENT_MAX_INPUT_TOKENS,
    EVAL_INSTRUCTION,
    RERANKER_KIND,
    Arm,
    get_arm,
)
from evals.gold.schema import GoldItem
from evals.manifest import write_manifest
from evals.models import COHERE_RERANK_MODEL, JEV_MODEL
from evals.run.adapters import SINGLE_SHOT_PROMPT_VERSION, compose_auto
from evals.run.budget import Budget, BudgetStop, UnpricedSpend
from evals.run.pricing import PriceTable
from evals.run.records import Generation, RouteRecord, record_key

GENERATIONS = "generations.jsonl"
ROUTES = "routes.jsonl"
STOPPED = "stopped.json"
SUMMARY = "run_summary.json"

MAX_ATTEMPTS = 3
"""One try and two retries."""

SUSPECT_UNMETERED_FRACTION = 0.05
"""An arm whose metered agent tokens fall this far below the product's own count is suspect."""

_OFF_PEAK_CHUNK_SECONDS = 600.0

Executor = Callable[[GoldItem, Arm, int], Awaitable[Generation]]
"""Runs one arm on one item for one repeat and returns its record; it may also raise."""

Router = Callable[[GoldItem], Awaitable[RouteRecord]]
"""Makes the routing decision for one item."""


# --- keys and plans -----------------------------------------------------------------


def prompt_version_for(arm: Arm) -> str:
    """The prompt version a generation by ``arm`` is keyed with.

    An agent arm is keyed with the product's agent prompt version, a single-shot arm with a hash
    of the single-shot templates; either changing re-keys the results.
    """
    return PROMPT_VERSION if arm.is_agent else SINGLE_SHOT_PROMPT_VERSION


def expected_key(item: GoldItem, arm: Arm, repeat: int = 0) -> str:
    """The key the generation of ``item`` by ``arm`` will have, known before it runs."""
    return record_key(
        item_id=item.id,
        question=item.question,
        repo=item.repo,
        base_commit=item.base_commit,
        arm_config_hash=arm.config_hash(),
        model=arm.model,
        prompt_version=prompt_version_for(arm),
        instruction=EVAL_INSTRUCTION,
        repeat=repeat,
    )


def route_key(item: GoldItem, decider_id: str) -> str:
    """The key of an item's routing decision: the item as asked and who decides."""
    payload = {
        "route": {
            "id": item.id,
            "question": item.question,
            "repo": item.repo,
            "base": item.base_commit,
        },
        "decider": decider_id,
    }
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def subset_ids(items: Iterable[GoldItem], n: int, seed: int) -> list[str]:
    """The ids of a deterministic subset: the first ``n`` items by ``sha256(seed:item_id)``."""
    ranked = sorted(
        (item.id for item in items),
        key=lambda item_id: (hashlib.sha256(f"{seed}:{item_id}".encode()).hexdigest(), item_id),
    )
    return ranked[: max(n, 0)]


def order_items(items: Iterable[GoldItem], arm_name: str, seed: int) -> list[GoldItem]:
    """The items in the order ``arm_name`` runs them: sorted by id, then shuffled per arm.

    The shuffle uses ``random.Random(f"{seed}:{arm_name}")``, so it is the same on every run and
    independent of the order the items were given in.
    """
    ordered = sorted(items, key=lambda item: item.id)
    random.Random(f"{seed}:{arm_name}").shuffle(ordered)
    return ordered


@dataclass(frozen=True)
class Pair:
    """One item on one arm for one repeat.

    Attributes:
        item: The gold item.
        arm: The arm.
        repeat: Which repeat; ``0`` is the first.
    """

    item: GoldItem
    arm: Arm
    repeat: int = 0

    @property
    def key(self) -> str:
        """The key of the record this pair produces."""
        return expected_key(self.item, self.arm, self.repeat)


def plan_pairs(
    items: Sequence[GoldItem],
    arms: Sequence[Arm],
    *,
    seed: int,
    subsets: Mapping[str, int] | None = None,
    repeats: int = 1,
    repeats_subset: int = 0,
) -> list[Pair]:
    """Every pair to run, arm by arm.

    Each arm runs its items once in its own shuffled order. An arm named in ``subsets`` runs only
    that many items, chosen by :func:`subset_ids`. When ``repeats`` is above one, agent arms then
    run repeats ``1..repeats-1`` on the ``repeats_subset`` items chosen the same way.

    Args:
        items: The slice's items.
        arms: The generated arms, in run order; composed arms are ignored.
        seed: The seed of the shuffles and subsets.
        subsets: Arm name to the number of items it is restricted to.
        repeats: How many times in all an agent arm runs an item of the repeat subset.
        repeats_subset: How many items the repeats cover.

    Returns:
        The pairs in run order.
    """
    pairs: list[Pair] = []
    repeat_ids = set(subset_ids(items, repeats_subset, seed)) if repeats > 1 else set()
    for arm in arms:
        if arm.composed:
            continue
        chosen = list(items)
        if subsets and arm.name in subsets:
            keep = set(subset_ids(items, subsets[arm.name], seed))
            chosen = [item for item in chosen if item.id in keep]
        ordered = order_items(chosen, arm.name, seed)
        pairs.extend(Pair(item, arm, 0) for item in ordered)
        if arm.is_agent and repeat_ids:
            for repeat in range(1, repeats):
                pairs.extend(Pair(item, arm, repeat) for item in ordered if item.id in repeat_ids)
    return pairs


# --- rate limits ---------------------------------------------------------------------


def default_providers(arm: Arm) -> tuple[str, ...]:
    """The providers a generation by ``arm`` calls, by the names the rate limits use."""
    providers = ["deepseek", "openai"]
    config = arm.config
    if config is not None and (config.rerank.kind != "none" or config.execution != "single_shot"):
        providers.append("openrouter")
    return tuple(providers)


class RateLimiter:
    """A minimum interval between the starts of calls to one provider.

    Args:
        min_intervals: Provider name to the seconds that must separate two of its calls; a
            provider with none is not limited.
        clock: A monotonic clock, in seconds.
        sleep: Waits for a number of seconds.
    """

    def __init__(
        self,
        min_intervals: Mapping[str, float] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        self._intervals = dict(min_intervals or {})
        self._clock = clock
        self._sleep = sleep
        self._next_free: dict[str, float] = {}

    async def wait(self, provider: str) -> None:
        """Returns when a call to ``provider`` may start; slots are handed out in order."""
        interval = self._intervals.get(provider, 0.0)
        if interval <= 0:
            return
        now = self._clock()
        slot = max(now, self._next_free.get(provider, now))
        self._next_free[provider] = slot + interval
        if slot > now:
            await self._sleep(slot - now)


# --- the files ---------------------------------------------------------------------------


def _read_lines(path: Path) -> Iterator[dict[str, Any]]:
    """The JSON objects of a JSONL file; an unreadable line (a write cut short) is skipped."""
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                yield value


def read_generations(path: Path) -> list[Generation]:
    """Every record in ``generations.jsonl``, in file order, superseded ones included."""
    return [Generation.model_validate(entry) for entry in _read_lines(path)]


def final_records(generations: Iterable[Generation]) -> list[Generation]:
    """One record per key, the last one written, in the order each key first appeared."""
    latest: dict[str, Generation] = {}
    for generation in generations:
        latest[generation.record_key] = generation
    return list(latest.values())


def read_routes(path: Path) -> dict[str, RouteRecord]:
    """The routing decisions in ``routes.jsonl`` by key; the last line for a key wins."""
    return {
        str(entry["key"]): RouteRecord.model_validate(entry["route"]) for entry in _read_lines(path)
    }


def _append(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(payload + "\n")
        handle.flush()


def meter_gap(generation: Generation) -> int | None:
    """Metered agent-model tokens minus the product's own count for the same run.

    The product's count covers the agent's own turns, which are the calls the meter files under
    ``agent``. A negative gap means the meter missed calls; ``None`` for a run with no count.
    """
    if generation.run_tokens is None:
        return None
    metered_in, metered_out = generation.metered_tokens("agent")
    counted = generation.run_tokens.input_tokens + generation.run_tokens.output_tokens
    return metered_in + metered_out - counted


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --- the result --------------------------------------------------------------------------


@dataclass
class GenerateResult:
    """What a run did.

    Attributes:
        planned: Pairs the run was asked for.
        skipped: Pairs already finished ``ok``.
        ok: Pairs generated successfully this run.
        errors: Pairs that ended as error records this run.
        spent_usd: Spend on the run so far, earlier sessions included.
        stopped: Why the run stopped early, or ``None`` when it ran to the end.
        auto_written: Composed ``auto`` records written.
        routes_written: Routing decisions made this run.
        route_errors: Routing decisions that failed and will be retried.
        summary: The ``run_summary.json`` content.
    """

    planned: int = 0
    skipped: int = 0
    ok: int = 0
    errors: int = 0
    spent_usd: float = 0.0
    stopped: str | None = None
    auto_written: int = 0
    routes_written: int = 0
    route_errors: int = 0
    summary: dict[str, Any] = field(default_factory=dict)


# --- the runner -------------------------------------------------------------------------


class _Run:
    def __init__(
        self,
        *,
        run_dir: Path,
        executor: Executor,
        router: Router | None,
        budget: Budget,
        table: PriceTable,
        limiter: RateLimiter,
        providers_of: Callable[[Arm], Sequence[str]],
        concurrency: int,
        off_peak_only: bool,
        clock: Callable[[], datetime],
        sleep: Callable[[float], Awaitable[Any]],
        retry_delay: float,
        decider_id: str,
        router_provider: str,
        seed: int,
    ) -> None:
        self.seed = seed
        self.run_dir = run_dir
        self.executor = executor
        self.router = router
        self.budget = budget
        self.table = table
        self.limiter = limiter
        self.providers_of = providers_of
        self.concurrency = max(1, concurrency)
        self.off_peak_only = off_peak_only
        self.clock = clock
        self.sleep = sleep
        self.retry_delay = retry_delay
        self.decider_id = decider_id
        self.router_provider = router_provider

        self.generations_path = run_dir / GENERATIONS
        self.routes_path = run_dir / ROUTES
        self.latest: dict[str, Generation] = {}
        self.routes: dict[str, RouteRecord] = {}
        self.claimed: set[str] = set()
        self.stop: BudgetStop | None = None
        self.result = GenerateResult()
        self._arm_costs: dict[str, list[float]] = defaultdict(list)

    # --- state -------------------------------------------------------------------------

    def load(self) -> None:
        existing = read_generations(self.generations_path)
        self.latest = {g.record_key: g for g in final_records(existing)}
        self.routes = read_routes(self.routes_path)
        self.budget.restore(existing, self.routes.values())
        for generation in self.latest.values():
            if generation.composed_from is None and generation.cost_usd is not None:
                self._arm_costs[generation.arm].append(generation.cost_usd)

    def _finished(self, key: str) -> bool:
        record = self.latest.get(key)
        return record is not None and record.status == "ok"

    def _estimate(self, arm: Arm) -> float | None:
        costs = self._arm_costs.get(arm.name)
        return sum(costs) / len(costs) if costs else None

    def _stop_with(self, stop: BudgetStop) -> None:
        if self.stop is None:
            self.stop = stop

    def _record(self, generation: Generation) -> None:
        _append(self.generations_path, generation.model_dump_json())
        self.latest[generation.record_key] = generation

    # --- generating pairs ----------------------------------------------------------------

    async def drain(self, pairs: Sequence[Pair]) -> None:
        iterator = iter(pairs)
        workers = [self._worker(iterator) for _ in range(min(self.concurrency, len(pairs) or 1))]
        await asyncio.gather(*workers)

    async def _worker(self, pairs: Iterator[Pair]) -> None:
        for pair in pairs:
            if self.stop is not None:
                return
            key = pair.key
            if self._finished(key) or key in self.claimed:
                self.result.skipped += 1
                continue
            await self._wait_for_off_peak()
            await self._wait_for_providers(pair.arm)
            if self.stop is not None:
                return
            try:
                self.budget.check_before_next()
                if self.budget.would_exceed(self._estimate(pair.arm)):
                    raise BudgetStop(
                        f"the next {pair.arm.name} pair would pass the "
                        f"${self.budget.cap_usd:.2f} cap",
                        self.budget.spent_usd,
                    )
            except BudgetStop as stop:
                self._stop_with(stop)
                return
            self.claimed.add(key)
            await self._run_pair(pair, key)

    async def _wait_for_off_peak(self) -> None:
        if not self.off_peak_only:
            return
        while self.stop is None:
            delay = self.table.seconds_until_off_peak(self.clock())
            if delay <= 0:
                return
            await self.sleep(min(delay, _OFF_PEAK_CHUNK_SECONDS))

    async def _wait_for_providers(self, arm: Arm) -> None:
        for provider in self.providers_of(arm):
            await self.limiter.wait(provider)

    def _charge(self, usages: Sequence[Any], when: datetime) -> float:
        try:
            return self.budget.charge(usages, self.table, when)
        except UnpricedSpend as failure:
            self._stop_with(
                BudgetStop(f"no price for {', '.join(failure.models)}", self.budget.spent_usd)
            )
            return failure.cost_usd

    async def _run_pair(self, pair: Pair, key: str) -> None:
        spent = 0.0
        generation: Generation | None = None
        attempts = 0
        for attempts in range(1, MAX_ATTEMPTS + 1):
            if attempts > 1:
                await self._wait_for_providers(pair.arm)
            started = self.clock()
            try:
                generation = await self.executor(pair.item, pair.arm, pair.repeat)
            except Exception as failure:
                generation = _error_record(pair, key, f"{type(failure).__name__}: {failure}")
            spent += self._charge(generation.usages, started)
            if generation.status == "ok":
                break
            if attempts < MAX_ATTEMPTS:
                await self.sleep(self.retry_delay)
        assert generation is not None
        final = generation.model_copy(
            update={
                "record_key": key,
                "cost_usd": spent,
                "attempts": attempts,
                "meter_gap_tokens": meter_gap(generation) if pair.arm.is_agent else None,
            }
        )
        self._record(final)
        if final.status == "ok":
            self.result.ok += 1
            self._arm_costs[pair.arm.name].append(spent)
        else:
            self.result.errors += 1

    # --- the composed arm ------------------------------------------------------------------

    async def route_all(self, items: Sequence[GoldItem]) -> list[RouteRecord]:
        assert self.router is not None
        for item in sorted(items, key=lambda entry: entry.id):
            key = route_key(item, self.decider_id)
            if key in self.routes:
                continue
            if self.stop is not None:
                break
            try:
                self.budget.check_before_next()
            except BudgetStop as stop:
                self._stop_with(stop)
                break
            await self.limiter.wait(self.router_provider)
            try:
                route = await self.router(item)
            except Exception:
                self.result.route_errors += 1
                continue
            route = route.model_copy(update={"cost_usd": self._charge(route.usages, self.clock())})
            _append(
                self.routes_path,
                json.dumps({"key": key, "route": route.model_dump(mode="json")}, sort_keys=True),
            )
            self.routes[key] = route
            self.result.routes_written += 1
        return [
            self.routes[key]
            for item in items
            if (key := route_key(item, self.decider_id)) in self.routes
        ]

    def _targets(self, items: Sequence[GoldItem], routes: Sequence[RouteRecord]) -> dict:
        by_id = {item.id: item for item in items}
        found: dict[tuple[str, str], Generation] = {}
        for route in routes:
            item = by_id.get(route.item_id)
            if item is None:
                continue
            generation = self.latest.get(expected_key(item, get_arm(route.target_arm), 0))
            if generation is not None:
                found[(item.id, route.target_arm)] = generation
        return found

    async def compose(self, items: Sequence[GoldItem], routes: Sequence[RouteRecord]) -> None:
        composition = compose_auto(routes, self._targets(items, routes))
        if composition.missing:
            by_id = {item.id: item for item in items}
            wanted: dict[str, list[GoldItem]] = defaultdict(list)
            for item_id, arm_name in composition.missing:
                wanted[arm_name].append(by_id[item_id])
            fill = [
                pair
                for arm_name, members in wanted.items()
                for pair in plan_pairs(members, [get_arm(arm_name)], seed=self.seed)
            ]
            await self.drain(fill)
            if self.stop is not None:
                return
            composition = compose_auto(routes, self._targets(items, routes))
        for generation in composition.generations:
            route = generation.route
            assert route is not None
            existing = self.latest.get(generation.record_key)
            if existing is not None and existing.status == generation.status:
                continue
            cost = (generation.cost_usd or 0.0) + (route.cost_usd or 0.0)
            self._record(
                generation.model_copy(
                    update={"cost_usd": cost, "attempts": 1, "meter_gap_tokens": None}
                )
            )
            self.result.auto_written += 1


def _error_record(pair: Pair, key: str, message: str) -> Generation:
    return Generation(
        record_key=key,
        item_id=pair.item.id,
        arm=pair.arm.name,
        repeat=pair.repeat,
        config_hash=pair.arm.config_hash(),
        model=pair.arm.model,
        prompt_version=prompt_version_for(pair.arm),
        status="error",
        error=message[:500],
    )


# --- summary ---------------------------------------------------------------------------


def summarise(
    records: Sequence[Generation], result: GenerateResult, arm_names: Sequence[str]
) -> dict[str, Any]:
    """The ``run_summary.json`` content for the records of a run.

    Includes per-arm counts and cost, the flagged and unmetered counts, and the meter check: for
    each agent arm, metered agent-model tokens against the product's own count.
    """
    per_arm: dict[str, dict[str, Any]] = {}
    for name in arm_names:
        mine = [r for r in records if r.arm == name]
        if not mine:
            continue
        costs = [r.cost_usd for r in mine if r.cost_usd is not None]
        per_arm[name] = {
            "records": len(mine),
            "ok": sum(r.status == "ok" for r in mine),
            "errors": sum(r.status == "error" for r in mine),
            "flagged": sum(r.flagged for r in mine),
            "unmetered": sum(bool(r.unmetered_paths) for r in mine),
            "mean_cost_usd": sum(costs) / len(costs) if costs else None,
            "attempts": sum(r.attempts for r in mine),
        }

    meter_check: dict[str, dict[str, Any]] = {}
    for name in arm_names:
        agents = [
            r
            for r in records
            if r.arm == name and r.composed_from is None and r.meter_gap_tokens is not None
        ]
        if not agents:
            continue
        counted = sum(
            r.run_tokens.input_tokens + r.run_tokens.output_tokens for r in agents if r.run_tokens
        )
        metered = sum(sum(r.metered_tokens("agent")) for r in agents)
        gaps = [r.meter_gap_tokens for r in agents if r.meter_gap_tokens is not None]
        meter_check[name] = {
            "runs": len(agents),
            "metered_tokens": metered,
            "product_tokens": counted,
            "mean_gap_tokens": sum(gaps) / len(gaps),
            "min_gap_tokens": min(gaps),
            "suspect": metered < counted * (1 - SUSPECT_UNMETERED_FRACTION),
        }

    return {
        "planned": result.planned,
        "skipped": result.skipped,
        "ok": result.ok,
        "errors": result.errors,
        "spent_usd": round(result.spent_usd, 6),
        "stopped": result.stopped,
        "auto_written": result.auto_written,
        "routes_written": result.routes_written,
        "route_errors": result.route_errors,
        "per_arm": per_arm,
        "meter_check": meter_check,
    }


# --- the entry point -----------------------------------------------------------------------


async def generate(
    *,
    items: Sequence[GoldItem],
    arm_names: Sequence[str],
    run_dir: Path,
    executor: Executor,
    budget: Budget,
    table: PriceTable,
    router: Router | None = None,
    seed: int = 0,
    subsets: Mapping[str, int] | None = None,
    repeats: int = 1,
    repeats_subset: int = 0,
    concurrency: int = 1,
    off_peak_only: bool = False,
    min_intervals: Mapping[str, float] | None = None,
    providers_of: Callable[[Arm], Sequence[str]] = default_providers,
    router_provider: str = "openrouter",
    clock: Callable[[], datetime] = _utcnow,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    retry_delay: float = 1.0,
    decider_id: str = DECIDER,
    slice_name: str = "",
    split_hash: str = "",
    manifest_overrides: Mapping[str, Any] | None = None,
) -> GenerateResult:
    """Runs every item on every arm, writing resumable records into ``run_dir``.

    Args:
        items: The slice's gold items.
        arm_names: The arms to run, in order; ``auto`` is composed after the others.
        run_dir: The run's directory; created, and resumed when it already holds records.
        executor: Runs one pair and returns its record.
        budget: The spend limits; its spend is set from the records already on disk.
        table: The price table, for charging and for the off-peak window.
        router: Makes a routing decision; required when ``auto`` is among the arms.
        seed: The seed of the per-arm shuffles and the subsets.
        subsets: Arm name to the number of items it is restricted to.
        repeats: How many times in all an agent arm runs an item of the repeat subset.
        repeats_subset: How many items the repeats cover.
        concurrency: How many pairs may run at once. The budget is checked as each pair starts,
            so with more than one the pairs already in flight when the stop is reached still
            finish; keep the stop below the cap by that many pairs' cost.
        off_peak_only: Wait for the off-peak window before each pair.
        min_intervals: Provider name to the minimum seconds between its calls.
        providers_of: The providers a generation by an arm calls.
        router_provider: The provider the routing decision calls.
        clock: The wall clock, for peak and off-peak.
        monotonic: A monotonic clock for the rate limiter.
        sleep: Waits for a number of seconds; replaced in tests.
        retry_delay: Seconds to wait between attempts at a failing pair.
        decider_id: Who decides the routes; part of a route's key and recorded in the manifest.
        slice_name: The slice being run, recorded in the manifest.
        split_hash: The frozen split's hash, recorded in the manifest.
        manifest_overrides: Arguments for :func:`evals.manifest.write_manifest` that replace the
            ones the runner computes, such as a fixed ``git`` state.

    Returns:
        What the run did. A stop on the budget is a normal return with ``stopped`` set and a
        ``stopped.json`` in the run directory.

    Raises:
        ValueError: When ``auto`` is requested without a router.
        KeyError: When an arm name is unknown.
    """
    arms = [get_arm(name) for name in dict.fromkeys(arm_names)]
    wants_auto = any(arm.name == AUTO for arm in arms)
    if wants_auto and router is None:
        raise ValueError("the auto arm needs a router")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / STOPPED).unlink(missing_ok=True)

    run = _Run(
        run_dir=run_dir,
        executor=executor,
        router=router,
        budget=budget,
        table=table,
        limiter=RateLimiter(min_intervals, clock=monotonic, sleep=sleep),
        providers_of=providers_of,
        concurrency=concurrency,
        off_peak_only=off_peak_only,
        clock=clock,
        sleep=sleep,
        retry_delay=retry_delay,
        decider_id=decider_id,
        router_provider=router_provider,
        seed=seed,
    )
    run.load()

    generated = [arm for arm in arms if not arm.composed]
    _write_run_manifest(
        run_dir,
        arms,
        items,
        table,
        budget,
        seed=seed,
        subsets=subsets,
        repeats=repeats,
        repeats_subset=repeats_subset,
        off_peak_only=off_peak_only,
        decider_id=decider_id,
        slice_name=slice_name,
        split_hash=split_hash,
        overrides=manifest_overrides,
        reported={},
    )

    pairs = plan_pairs(
        items,
        generated,
        seed=seed,
        subsets=subsets,
        repeats=repeats,
        repeats_subset=repeats_subset,
    )
    run.result.planned = len(pairs)
    await run.drain(pairs)

    if wants_auto and run.stop is None:
        auto_items = list(items)
        if subsets and AUTO in subsets:
            keep = set(subset_ids(auto_items, subsets[AUTO], seed))
            auto_items = [item for item in auto_items if item.id in keep]
        routes = await run.route_all(auto_items)
        if run.stop is None:
            await run.compose(auto_items, routes)

    result = run.result
    result.spent_usd = budget.spent_usd
    if run.stop is not None:
        result.stopped = run.stop.reason
        (run_dir / STOPPED).write_text(
            json.dumps(
                {
                    "reason": run.stop.reason,
                    "spent_usd": round(run.stop.spent_usd, 6),
                    "cap_usd": budget.cap_usd,
                    "stop_usd": budget.stop_usd,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    records = final_records(read_generations(run.generations_path))
    result.summary = summarise(records, result, [arm.name for arm in arms])
    (run_dir / SUMMARY).write_text(
        json.dumps(result.summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    reported = sorted(
        {u.model for r in records for u in r.usages if u.kind in ("generate", "agent")}
    )
    _write_run_manifest(
        run_dir,
        arms,
        items,
        table,
        budget,
        seed=seed,
        subsets=subsets,
        repeats=repeats,
        repeats_subset=repeats_subset,
        off_peak_only=off_peak_only,
        decider_id=decider_id,
        slice_name=slice_name,
        split_hash=split_hash,
        overrides=manifest_overrides,
        reported={"generator": ",".join(reported)} if reported else {},
    )
    return result


def _write_run_manifest(
    run_dir: Path,
    arms: Sequence[Arm],
    items: Sequence[GoldItem],
    table: PriceTable,
    budget: Budget,
    *,
    seed: int,
    subsets: Mapping[str, int] | None,
    repeats: int,
    repeats_subset: int,
    off_peak_only: bool,
    decider_id: str,
    slice_name: str,
    split_hash: str,
    overrides: Mapping[str, Any] | None,
    reported: Mapping[str, str],
) -> None:
    pins = {item.repo: item.base_commit for item in items}
    fields: dict[str, Any] = {
        "arms": {arm.name: arm.config_hash() for arm in arms},
        "prompt_version": f"agent={PROMPT_VERSION};single_shot={SINGLE_SHOT_PROMPT_VERSION}",
        "models": {
            "generator": ",".join(sorted({arm.model for arm in arms})),
            "embedding": EMBEDDING_MODEL,
            "reranker": COHERE_RERANK_MODEL,
            "decider": JEV_MODEL,
        },
        "reported_snapshots": dict(reported),
        "price_table_version": table.version,
        "agent_token_cap": EVAL_AGENT_MAX_INPUT_TOKENS,
        "corpus_pins": pins,
        "split_hash": split_hash,
        "eval_instruction": EVAL_INSTRUCTION,
        "extra": {
            "kind": "generate",
            "slice": slice_name,
            "seed": seed,
            "items": len(items),
            "subsets": dict(subsets or {}),
            "repeats": repeats,
            "repeats_subset": repeats_subset,
            "off_peak_only": off_peak_only,
            "reranker_kind": RERANKER_KIND,
            "decider": decider_id,
            "price_table_as_of": table.as_of.isoformat() if table.as_of else None,
            "budget": {"cap_usd": budget.cap_usd, "stop_usd": budget.stop_usd},
        },
    }
    fields.update(overrides or {})
    write_manifest(run_dir, **fields)


__all__ = [
    "GENERATIONS",
    "MAX_ATTEMPTS",
    "ROUTES",
    "STOPPED",
    "SUMMARY",
    "Executor",
    "GenerateResult",
    "Pair",
    "RateLimiter",
    "Router",
    "default_providers",
    "expected_key",
    "final_records",
    "generate",
    "meter_gap",
    "order_items",
    "plan_pairs",
    "prompt_version_for",
    "read_generations",
    "read_routes",
    "route_key",
    "subset_ids",
    "summarise",
]
