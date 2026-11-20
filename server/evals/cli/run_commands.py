"""``run generate`` and ``budget``: the generation pass from the command line.

The command checks everything that could waste money before it spends any: the slice exists, its
pre-registration is frozen, the price table is complete for the models the run will call, and the
keys those calls need are configured. Only then does it open the real runtime (the eval database,
the harness clones, the providers) and hand the pairs to :func:`evals.run.generate.generate`.

Nothing here is exercised against a real provider in the tests; they inject a runtime.

Library code here takes nothing from ``evals.settings``; the entry point passes in what it needs.
"""

from __future__ import annotations

import asyncio
import dataclasses
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Repository, User
from app.services.agent.tools.context import RepoSnapshot
from app.services.retrieval.channels.base import RetrievalContext
from app.services.retrieval.embedding import EMBEDDING_MODEL, embed_texts
from evals.arms import ARMS, AUTO, STARTER_ARMS, Arm, get_arm
from evals.cli.corpus_commands import EVAL_USER_EMAIL, generator_config
from evals.corpus.corpus import CORPUS_PATH, CorpusError, load_corpus
from evals.gold.schema import GoldItem, read_jsonl
from evals.gold.split import LOCK_NAME, PreregNotFrozen, read_lock, require_frozen_prereg
from evals.mining.clones import clone_dir, rev_exists
from evals.run.adapters import route_item, run_agent_arm, run_single_shot
from evals.run.budget import Budget, ProjectionPlan, project, spent_in
from evals.run.clone_tools import build_clone_registry
from evals.run.generate import (
    GENERATIONS,
    ROUTES,
    STOPPED,
    Executor,
    Router,
    final_records,
    generate,
    read_generations,
    read_routes,
)
from evals.run.metering import Meter
from evals.run.pricing import PRICES_PATH, PricesIncomplete, PriceTable
from evals.run.records import RouteRecord

SERVER_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = SERVER_ROOT.parent
PREREG_DIR = SERVER_ROOT / "evals" / "prereg"

DEFAULT_MIN_INTERVALS = {"deepseek": 0.2, "openai": 0.1, "openrouter": 0.2}
"""Seconds between calls to each provider; a courtesy, not a quota."""

DEFAULT_CONCURRENCY = 4

Runtime = Callable[[Sequence[GoldItem]], AbstractAsyncContextManager[tuple[Executor, Router]]]
"""Opens whatever the generation needs (database, clones, clients) and yields the executor and
router that use it."""


class RunSetupError(RuntimeError):
    """The run cannot start: something it needs is missing or inconsistent."""


# --- arguments ------------------------------------------------------------------------


def resolve_arms(spec: str) -> list[str]:
    """The arm names a ``--arms`` value stands for.

    Args:
        spec: ``starter`` for the starter run's arms, or comma-separated arm names.

    Raises:
        RunSetupError: When a name is not an arm.
    """
    if spec.strip() == "starter":
        return list(STARTER_ARMS)
    names = [name.strip() for name in spec.split(",") if name.strip()]
    unknown = [name for name in names if name not in ARMS]
    if unknown or not names:
        raise RunSetupError(
            f"unknown arm(s) {', '.join(unknown) or '(none given)'}; arms: {', '.join(ARMS)}"
        )
    return names


def parse_subsets(values: Sequence[str]) -> dict[str, int]:
    """Parses ``--subset arm=N`` values.

    Raises:
        RunSetupError: When a value is not ``arm=N`` for a known arm.
    """
    subsets: dict[str, int] = {}
    for value in values:
        name, _, count = value.partition("=")
        if name not in ARMS or not count.isdigit():
            raise RunSetupError(f"--subset expects ARM=N for a known arm, got {value!r}")
        subsets[name] = int(count)
    return subsets


def models_needed(arm_names: Sequence[str]) -> list[str]:
    """The model ids a run of these arms will be charged for."""
    models = [get_arm(name).model for name in arm_names if not get_arm(name).composed]
    return [*dict.fromkeys(models), EMBEDDING_MODEL]


def keys_needed(arm_names: Sequence[str]) -> list[str]:
    """The ``.env.eval`` keys a run of these arms calls providers with."""
    keys = ["AI_API_KEY", "OPENAI_API_KEY"]
    for name in arm_names:
        arm = get_arm(name)
        config = arm.config
        if arm.composed or (
            config is not None
            and (config.rerank.kind != "none" or config.execution != "single_shot")
        ):
            keys.append("OPENROUTER_API_KEY")
            break
    return keys


def run_dir_for(out_dir: Path, run_name: str) -> Path:
    """Where a named run keeps its files."""
    return Path(out_dir) / "runs" / run_name


# --- the real runtime ---------------------------------------------------------------------


@dataclass(frozen=True)
class _RepoHandle:
    snapshot: RepoSnapshot
    registry: Any


async def _repo_handles(
    sessions: Any, items: Sequence[GoldItem], clones_dir: Path, corpus_path: Path
):
    corpus = load_corpus(corpus_path)
    handles: dict[str, _RepoHandle] = {}
    for name in sorted({item.repo for item in items}):
        try:
            corpus_repo = corpus.get(name)
        except CorpusError as failure:
            raise RunSetupError(str(failure)) from None
        async with sessions() as db:
            repository = (
                (
                    await db.execute(
                        select(Repository)
                        .join(User, User.id == Repository.user_id)
                        .where(
                            User.email == EVAL_USER_EMAIL,
                            Repository.name == name,
                            Repository.status == "ready",
                        )
                        .order_by(Repository.created_at.desc())
                    )
                )
                .scalars()
                .first()
            )
        if repository is None:
            raise RunSetupError(f"{name} is not ingested; run `corpus ingest --repo {name}`")
        if repository.ingested_commit_sha != corpus_repo.base_commit:
            raise RunSetupError(f"{name} is ingested at a commit other than its pinned base")
        clone = clone_dir(clones_dir, corpus_repo.slug)
        if not clone.exists() or not rev_exists(clone, corpus_repo.base_commit):
            raise RunSetupError(f"no clone of {name} at its base commit; run `mine --repo {name}`")
        handles[name] = _RepoHandle(
            snapshot=RepoSnapshot.from_repository(repository),
            registry=build_clone_registry(clone, corpus_repo.base_commit),
        )
    return handles


def real_runtime(*, async_url: str, clones_dir: Path, corpus_path: Path, api_key: str) -> Runtime:
    """The runtime that calls the real providers and reads the eval database and clones.

    Args:
        async_url: The eval database's async URL.
        clones_dir: Where the harness clones live.
        corpus_path: The corpus file, for each repository's slug and pinned base.
        api_key: The generator's API key.
    """

    @asynccontextmanager
    async def open_runtime(items: Sequence[GoldItem]):
        engine = create_async_engine(async_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            base_llm = generator_config(api_key)
            handles = await _repo_handles(sessions, items, clones_dir, corpus_path)
            meter = Meter()

            async def executor(item: GoldItem, arm: Arm, repeat: int):
                handle = handles[item.repo]
                llm = dataclasses.replace(base_llm, model=arm.model)
                if arm.is_agent:
                    return await run_agent_arm(
                        item,
                        arm,
                        repository=handle.snapshot,
                        session_factory=sessions,
                        llm=llm,
                        meter=meter,
                        registry=handle.registry,
                        repeat=repeat,
                    )

                @asynccontextmanager
                async def open_context():
                    async with sessions() as db:
                        yield RetrievalContext(
                            repository_id=handle.snapshot.id, db=db, embed=embed_texts
                        )

                return await run_single_shot(
                    item, arm, ctx_factory=open_context, llm=llm, meter=meter, repeat=repeat
                )

            async def router(item: GoldItem):
                return await route_item(item)

            yield executor, router
        finally:
            await engine.dispose()

    return open_runtime


# --- generate -------------------------------------------------------------------------------


def _slice_path(out_dir: Path, slice_name: str) -> Path:
    return Path(out_dir) / "gold" / f"{slice_name}.jsonl"


def cmd_run_generate(
    *,
    out_dir: Path,
    slice_name: str,
    arms_spec: str,
    run_name: str,
    budget_usd: float,
    stop_usd: float,
    runtime: Runtime | None = None,
    clones_dir: Path | None = None,
    async_url: str | None = None,
    corpus_path: Path = CORPUS_PATH,
    require_key: Callable[[str], str] | None = None,
    table: PriceTable | None = None,
    subsets: Sequence[str] = (),
    repeats: int = 1,
    repeats_subset: int = 0,
    off_peak_only: bool = False,
    seed: int = 0,
    concurrency: int = DEFAULT_CONCURRENCY,
    prereg_dir: Path = PREREG_DIR,
    repo_root: Path = REPO_ROOT,
    min_intervals: Mapping[str, float] | None = None,
    capture: Callable[[Path, Sequence[GoldItem]], None] | None = None,
    sync_url: str | None = None,
) -> int:
    """Generate answers for a slice, every arm on every question.

    Args:
        out_dir: The eval output directory.
        slice_name: ``pilot``, ``tuning`` or ``test``; the last two need a frozen
            pre-registration where the guard demands one.
        arms_spec: ``starter`` or comma-separated arm names.
        run_name: The run's name; it resumes when the run already exists.
        budget_usd: The spending cap.
        stop_usd: The spend at which the run stops cleanly.
        runtime: Opens the executor and router; the real providers when omitted.
        clones_dir: Where the harness clones live; needed for the real runtime.
        async_url: The eval database's async URL; needed for the real runtime.
        corpus_path: The corpus file.
        require_key: Returns a configured key or raises; needed for the real runtime.
        table: The price table; the shipped one when omitted.
        subsets: ``ARM=N`` restrictions.
        repeats: Runs of each agent arm on the repeat subset.
        repeats_subset: Items the repeats cover.
        off_peak_only: Wait for the off-peak window before each pair.
        seed: The seed of the shuffles and subsets.
        concurrency: Pairs that may run at once.
        prereg_dir: Where the pre-registrations live.
        repo_root: The git repository's root, for the frozen check.
        min_intervals: Seconds between calls per provider.
        capture: Writes the report's context files into the run directory after the pass; when
            omitted and ``sync_url`` is given, the files are captured from that database.
        sync_url: The eval database's sync URL, for the default capture.

    Returns:
        The process exit status: 0 on success, 1 when something stopped it from starting or any
        pair ended as an error, 2 for a bad argument.
    """
    try:
        arm_names = resolve_arms(arms_spec)
        subset_map = parse_subsets(subsets)
    except RunSetupError as failure:
        print(str(failure), file=sys.stderr)
        return 2
    if repeats < 1 or repeats_subset < 0:
        print("--repeats must be at least 1 and --repeats-subset at least 0", file=sys.stderr)
        return 2

    source = _slice_path(out_dir, slice_name)
    if not source.exists():
        print(f"{source} not found; run `gold split` first", file=sys.stderr)
        return 1
    items = read_jsonl(source)
    if not items:
        print(f"{source} has no items", file=sys.stderr)
        return 1

    try:
        require_frozen_prereg(slice_name, prereg_dir, repo_root=repo_root)
    except (PreregNotFrozen, ValueError) as failure:
        print(str(failure), file=sys.stderr)
        return 1

    prices = table or PriceTable.load(PRICES_PATH)
    try:
        prices.require_complete(models_needed(arm_names))
    except PricesIncomplete as failure:
        print(str(failure), file=sys.stderr)
        return 1

    if runtime is None:
        if require_key is None or clones_dir is None or async_url is None:
            print("the real runtime needs keys, a clones directory and a database", file=sys.stderr)
            return 1
        try:
            for key in keys_needed(arm_names):
                require_key(key)
            runtime = real_runtime(
                async_url=async_url,
                clones_dir=clones_dir,
                corpus_path=corpus_path,
                api_key=require_key("AI_API_KEY"),
            )
        except Exception as failure:
            print(str(failure), file=sys.stderr)
            return 1

    lock = _read_split_lock(out_dir)
    run_dir = run_dir_for(out_dir, run_name)
    try:
        budget = Budget(cap_usd=budget_usd, stop_usd=stop_usd)
    except ValueError as failure:
        print(str(failure), file=sys.stderr)
        return 2

    async def run() -> Any:
        assert runtime is not None
        async with runtime(items) as (executor, router):
            return await generate(
                items=items,
                arm_names=arm_names,
                run_dir=run_dir,
                executor=executor,
                router=router if AUTO in arm_names else None,
                budget=budget,
                table=prices,
                seed=seed,
                subsets=subset_map,
                repeats=repeats,
                repeats_subset=repeats_subset,
                concurrency=concurrency,
                off_peak_only=off_peak_only,
                min_intervals=DEFAULT_MIN_INTERVALS if min_intervals is None else min_intervals,
                slice_name=slice_name,
                split_hash=lock.get("frozen_sha256", ""),
            )

    try:
        result = asyncio.run(run())
    except RunSetupError as failure:
        print(str(failure), file=sys.stderr)
        return 1

    print(
        f"{result.ok} ok, {result.errors} errors, {result.skipped} already done; "
        f"spent ${result.spent_usd:.4f} of ${budget.cap_usd:.2f}"
    )
    if result.stopped:
        print(f"stopped: {result.stopped} (see {run_dir / STOPPED})")
    if result.errors:
        print("some pairs ended as errors; running the command again retries them")
    print(f"records: {run_dir / GENERATIONS}")
    _capture_context(capture, sync_url, run_dir, items, out_dir, corpus_path)
    return 1 if result.errors else 0


def _capture_context(
    capture: Callable[[Path, Sequence[GoldItem]], None] | None,
    sync_url: str | None,
    run_dir: Path,
    items: Sequence[GoldItem],
    out_dir: Path,
    corpus_path: Path,
) -> None:
    """Write the report's context files into the run directory; a failure is only reported."""
    if capture is None and sync_url is None:
        return
    try:
        if capture is not None:
            capture(run_dir, items)
            return
        from evals.report.capture import capture_from_url

        assert sync_url is not None
        missing = capture_from_url(
            sync_url,
            run_dir=run_dir,
            items=items,
            out_dir=out_dir,
            user_email=EVAL_USER_EMAIL,
            corpus_path=corpus_path,
        )
        if missing:
            print(f"no ingested repository to capture for: {', '.join(missing)}", file=sys.stderr)
    except Exception as failure:
        print(f"could not capture the report's context: {failure}", file=sys.stderr)


def _read_split_lock(out_dir: Path) -> dict[str, Any]:
    path = Path(out_dir) / "gold" / LOCK_NAME
    return read_lock(path) if path.exists() else {}


# --- budget -------------------------------------------------------------------------------


def cmd_budget(
    *,
    out_dir: Path,
    budget_usd: float,
    stop_usd: float,
    run_name: str | None = None,
    project_run: bool = False,
    items: int | None = None,
    arms_spec: str = "starter",
    repeats: int = 1,
    repeats_subset: int = 0,
    print_fn: Callable[[str], None] = print,
) -> int:
    """Show spend against the budget, or project a larger run from the measured cost.

    Args:
        out_dir: The eval output directory.
        budget_usd: The spending cap.
        stop_usd: The stop threshold.
        run_name: The run to read; every run under the output directory when omitted.
        project_run: Project a planned run instead of showing spend.
        items: With ``project_run``, how many items the planned run has.
        arms_spec: With ``project_run``, ``starter`` or comma-separated arm names.
        repeats: With ``project_run``, runs of each agent arm on the repeat subset.
        repeats_subset: With ``project_run``, items the repeats cover.
        print_fn: Prints a line.

    Returns:
        The process exit status.
    """
    runs_root = Path(out_dir) / "runs"
    directories = (
        [run_dir_for(out_dir, run_name)]
        if run_name
        else sorted(path for path in runs_root.glob("*") if path.is_dir())
    )
    generations = []
    routes: list[RouteRecord] = []
    for directory in directories:
        generations.extend(read_generations(directory / GENERATIONS))
        routes.extend(read_routes(directory / ROUTES).values())
    if not generations and not routes:
        where = directories[0] if run_name else runs_root
        print(f"no records under {where}", file=sys.stderr)
        return 1

    if not project_run:
        spent = spent_in(generations, routes)
        print_fn(f"spent ${spent:.4f} of ${budget_usd:.2f} (stop at ${stop_usd:.2f})")
        counts: dict[str, int] = {}
        for record in final_records(generations):
            counts[record.arm] = counts.get(record.arm, 0) + 1
        for arm_name, count in sorted(counts.items()):
            print_fn(f"  {arm_name:<24} {count:>5} records")
        return 0

    if not items or items < 1:
        print("--project needs --items N", file=sys.stderr)
        return 2
    try:
        arm_names = resolve_arms(arms_spec)
    except RunSetupError as failure:
        print(str(failure), file=sys.stderr)
        return 2
    projection = project(
        generations,
        ProjectionPlan(
            arms=tuple(arm_names), items=items, repeats=repeats, repeats_subset=repeats_subset
        ),
    )
    print_fn(f"{'arm':<24} {'n':>4} {'mean':>10} {'p95':>10} {'runs':>5} {'expected':>10}")
    for arm in projection.arms:
        print_fn(
            f"{arm.arm:<24} {arm.measured:>4} {arm.mean_usd:>10.5f} {arm.p95_usd:>10.5f} "
            f"{arm.runs:>5} {arm.expected_usd:>10.4f}"
        )
    print_fn(
        f"projected ${projection.expected_usd:.2f} (high ${projection.high_usd:.2f}) "
        f"against a cap of ${budget_usd:.2f}"
    )
    if projection.unmeasured:
        print_fn(f"no measurements for: {', '.join(projection.unmeasured)} (not in the totals)")
    return 0


__all__ = [
    "DEFAULT_CONCURRENCY",
    "DEFAULT_MIN_INTERVALS",
    "PREREG_DIR",
    "RunSetupError",
    "Runtime",
    "cmd_budget",
    "cmd_run_generate",
    "keys_needed",
    "models_needed",
    "parse_subsets",
    "real_runtime",
    "resolve_arms",
    "run_dir_for",
]
