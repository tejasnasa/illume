"""``gold build``, ``phrase``, ``check``, ``verify`` and ``split``: a repository's gold items."""

import asyncio
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from evals.corpus.corpus import CORPUS_PATH, CorpusError, load_corpus
from evals.gold.build import DEFAULT_SEED, BuildOutcome, GoldBuildError, build_gold
from evals.gold.check import (
    all_checks,
    apply_checks,
    check_items,
    checks_path,
    read_checks,
    spent_on_disk,
)
from evals.gold.hand import HandError, hand_path, load_hand_items
from evals.gold.phrase import make_leak_context_factory, phrase_items
from evals.gold.schema import read_jsonl, write_jsonl
from evals.gold.split import LOCK_NAME, make_pilot, make_split, write_lock, write_slices
from evals.gold.verify import (
    DEFAULT_ANNOTATOR,
    agreement_report,
    apply_labels,
    format_error_report,
    gold_error_report,
    labels_path,
    read_labels,
    run_verification,
    sample_for_verification,
)
from evals.mining.clones import clone_dir, rev_exists, show_file
from evals.run.budget import Budget
from evals.run.endpoint import JudgeConfigError, JudgeEndpoint
from evals.run.metering import Meter
from evals.run.pricing import PRICES_PATH, PricesIncomplete, PriceTable

ITEMS = "items.jsonl"
PHRASED = "items.phrased.jsonl"
VERIFIED = "items.verified.jsonl"
PHRASE_CONCURRENCY = 8


async def _run(
    *,
    async_url: str,
    out_dir: Path,
    clones_dir: Path,
    repo_name: str,
    corpus_path: Path,
    seed: int,
    options: dict[str, bool],
) -> BuildOutcome:
    corpus_repo = load_corpus(corpus_path).get(repo_name)
    engine = create_async_engine(async_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            return await build_gold(
                db,
                corpus_repo=corpus_repo,
                out_dir=out_dir,
                clones_dir=clones_dir,
                seed=seed,
                **options,
            )
    finally:
        await engine.dispose()


def cmd_gold_build(
    *,
    async_url: str,
    out_dir: Path,
    clones_dir: Path,
    repo_name: str,
    corpus_path: Path = CORPUS_PATH,
    seed: int = DEFAULT_SEED,
    include_anchor: bool = False,
    include_rationale: bool = False,
    include_structural: bool = False,
    include_unanswerable: bool = False,
) -> int:
    """Build one repository's gold items and print the counts against its question mix.

    Args:
        async_url: The eval database's async URL.
        out_dir: The eval output directory.
        clones_dir: Where harness clones live.
        repo_name: The corpus entry to build.
        corpus_path: The corpus file.
        seed: The sampling seed.
        include_anchor: Also build the change questions that name a starting file.
        include_rationale: Also build the "why" questions.
        include_structural: Also build the import-graph questions.
        include_unanswerable: Keep the hand items marked unanswerable.

    Returns:
        The process exit status.
    """
    options = {
        "include_anchor": include_anchor,
        "include_rationale": include_rationale,
        "include_structural": include_structural,
        "include_unanswerable": include_unanswerable,
    }
    try:
        outcome = asyncio.run(
            _run(
                async_url=async_url,
                out_dir=out_dir,
                clones_dir=clones_dir,
                repo_name=repo_name,
                corpus_path=corpus_path,
                seed=seed,
                options=options,
            )
        )
    except (CorpusError, GoldBuildError, HandError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for kind, entry in outcome.log["mix"].items():
        line = f"{kind:<11} {entry['selected']:>4} of {entry['requested']} requested"
        if entry["shortfall"]:
            line += f" (short by {entry['shortfall']}; {entry['available']} available)"
        print(line)
    for family, found in outcome.counts.items():
        print(f"family {family:<11} {found:>4}")
    for reason, count in outcome.log["drops"].items():
        print(f"dropped {reason}: {count}")
    checks = outcome.log["checks"]
    if checks["dropped_unsupported"]:
        print(f"dropped as unsupported by the check: {len(checks['dropped_unsupported'])}")
    for flagged in checks["partly_supported"]:
        print(f"partly supported, fix: {flagged['item']}: {flagged['faulty_claim']}")
    print(f"written: {outcome.items_path}")
    return 0


def _gold_dir(out_dir: Path, repo_name: str) -> Path:
    return Path(out_dir) / "gold" / repo_name


def _best_items_path(directory: Path) -> Path | None:
    """The most processed items file present: verified, then phrased, then built."""
    for name in (VERIFIED, PHRASED, ITEMS):
        if (directory / name).exists():
            return directory / name
    return None


def cmd_gold_phrase(
    *,
    out_dir: Path,
    clones_dir: Path,
    endpoint: JudgeEndpoint,
    repo_name: str,
    corpus_path: Path = CORPUS_PATH,
    client_factory: Callable[[], Any] | None = None,
) -> int:
    """Phrase a repository's built items and write the phrased file.

    Args:
        out_dir: The eval output directory.
        clones_dir: Where harness clones live.
        endpoint: The phraser's model, where it is reached and its key; the judge's by default.
        repo_name: The corpus entry.
        corpus_path: The corpus file.
        client_factory: Builds the model client; a client for ``endpoint`` when omitted.

    Returns:
        The process exit status.
    """
    directory = _gold_dir(out_dir, repo_name)
    source = directory / ITEMS
    if not source.exists():
        print(f"{source} not found; run `gold build` first", file=sys.stderr)
        return 1
    if client_factory is None:
        try:
            endpoint.require_key()
        except JudgeConfigError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        def client_factory() -> Any:
            return AsyncOpenAI(**endpoint.client_kwargs())

    try:
        corpus_repo = load_corpus(corpus_path).get(repo_name)
    except CorpusError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    clone = clone_dir(clones_dir, corpus_repo.slug)
    if not clone.exists() or not rev_exists(clone, corpus_repo.base_commit):
        print("no clone at the base commit; run `mine` first", file=sys.stderr)
        return 1
    result = asyncio.run(
        phrase_items(
            read_jsonl(source),
            client_factory=client_factory,
            model=endpoint.model,
            cache_path=directory / "phrased.jsonl",
            leak_context=make_leak_context_factory(clone, corpus_repo.base_commit),
            concurrency=PHRASE_CONCURRENCY,
            api_style=endpoint.api_style,
        )
    )
    path = write_jsonl(directory / PHRASED, result.items)
    print(f"phrased {len(result.items)} items ({result.calls} calls, {result.cached} cached)")
    reasons: dict[str, int] = {}
    for drop in result.drops:
        reasons[drop.reason] = reasons.get(drop.reason, 0) + 1
    for reason, count in sorted(reasons.items()):
        print(f"dropped {reason}: {count}")
    print(f"written: {path}")
    return 0


def cmd_gold_verify(
    *,
    out_dir: Path,
    repo_name: str,
    annotator: str | None,
    report: bool,
    corpus_path: Path = CORPUS_PATH,
    seed: int = DEFAULT_SEED,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
) -> int:
    """Label a sample interactively, or with ``report`` print the error and agreement report.

    The report also writes ``items.verified.jsonl``: the phrased (or built) items with the
    verdicts applied.

    Args:
        out_dir: The eval output directory.
        repo_name: The corpus entry.
        annotator: Reads and writes ``labels.<annotator>.jsonl`` when given.
        report: Print the report and write the verified items instead of labelling.
        corpus_path: The corpus file.
        seed: The sampling seed.
        input_fn: Reads a line of input.
        print_fn: Prints text.

    Returns:
        The process exit status.
    """
    directory = _gold_dir(out_dir, repo_name)
    base = directory / PHRASED if (directory / PHRASED).exists() else directory / ITEMS
    if not base.exists():
        print(f"no items in {directory}; run `gold build` first", file=sys.stderr)
        return 1
    items = read_jsonl(base)
    path = labels_path(directory, annotator)
    labels = read_labels(path)
    if report:
        print_fn(format_error_report(gold_error_report(items, labels)))
        for candidate in sorted(directory.glob("labels*.jsonl")):
            if candidate == path:
                continue
            agreement = agreement_report(labels, read_labels(candidate))
            if agreement.n and agreement.kappa is not None:
                print_fn(
                    f"agreement with {candidate.name}: n={agreement.n} kappa={agreement.kappa:.3f}"
                )
        kept = apply_labels(items, labels)
        out = write_jsonl(directory / VERIFIED, kept)
        print_fn(f"written: {out} ({len(kept)} items)")
        return 0
    try:
        slug = load_corpus(corpus_path).get(repo_name).slug
    except CorpusError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    outcome = run_verification(
        sample_for_verification(items, seed=seed),
        slug=slug,
        path=path,
        annotator=annotator or DEFAULT_ANNOTATOR,
        input_fn=input_fn,
        print_fn=print_fn,
    )
    print_fn(f"labelled {outcome.labelled}, remaining {outcome.remaining}")
    return 0


def cmd_gold_split(
    *,
    out_dir: Path,
    repo_name: str | None,
    all_repos: bool,
    pilot: bool = True,
    seed: int = DEFAULT_SEED,
) -> int:
    """Split the items into slices and write the lock.

    Args:
        out_dir: The eval output directory.
        repo_name: Restrict to one repository.
        all_repos: Use every repository that has items.
        pilot: Put everything in one ``pilot`` slice, the default; false makes the tuning and
            test split.
        seed: The hashing seed.

    Returns:
        The process exit status.
    """
    root = Path(out_dir) / "gold"
    if all_repos:
        directories = sorted(path for path in root.glob("*") if path.is_dir())
    elif repo_name:
        directories = [root / repo_name]
    else:
        print("gold split needs --repo NAME or --all", file=sys.stderr)
        return 2
    items = []
    for directory in directories:
        source = _best_items_path(directory)
        if source is None:
            print(f"no items in {directory}; run `gold build` first", file=sys.stderr)
            return 1
        print(f"{directory.name}: {source.name}")
        items.extend(read_jsonl(source))
    split = make_pilot(items, seed=seed) if pilot else make_split(items, seed=seed)
    write_slices(split, root)
    lock = write_lock(split, root / LOCK_NAME)
    for name, count in lock["counts"].items():
        print(f"{name:<8} {count:>5}")
    print(f"written: {root / LOCK_NAME}")
    return 0


def cmd_gold_check(
    *,
    out_dir: Path,
    clones_dir: Path,
    repo_name: str,
    endpoint: JudgeEndpoint,
    budget_usd: float,
    stop_usd: float,
    corpus_path: Path = CORPUS_PATH,
    hand_file: Path | None = None,
    concurrency: int = 4,
    table: PriceTable | None = None,
    client_factory: Callable[..., Any] = AsyncOpenAI,
    clock: Callable[[], datetime] | None = None,
    print_fn: Callable[[str], None] = print,
) -> int:
    """Check a repository's hand-written reference answers against its files at the base commit.

    Each hand item with a reference answer and required files goes to the checker model with its
    question, the reference answer and the text of its files from the harness clone. Results are
    appended to ``checks.<checker>.jsonl`` in the repository's gold directory; items already
    checked are skipped and failed ones tried again. Afterwards the verdicts are summarised:
    ``unsupported`` items are dropped by the next ``gold build``, and ``partly_supported`` ones
    are listed with the claim at fault so they can be fixed.

    Args:
        out_dir: The eval output directory.
        clones_dir: Where harness clones live.
        repo_name: The corpus entry.
        endpoint: The checker model and where it is reached.
        budget_usd: The spending cap; the checks already on disk count against it.
        stop_usd: The spend at which checking stops cleanly.
        corpus_path: The corpus file.
        hand_file: Overrides where the hand questions are read from.
        concurrency: Items checked at once.
        table: The price table; the shipped one when omitted.
        client_factory: Builds the client; ``AsyncOpenAI`` by default.
        clock: The wall clock, replaced in tests.
        print_fn: Prints a line.

    Returns:
        The process exit status: 0 when every item has a verdict, 1 when something failed or
        stopped the run, 2 for a bad argument.
    """
    try:
        corpus_repo = load_corpus(corpus_path).get(repo_name)
        budget = Budget(cap_usd=budget_usd, stop_usd=stop_usd)
        hand = load_hand_items(
            hand_file or hand_path(repo_name),
            repo_name=repo_name,
            base_commit=corpus_repo.base_commit,
        )
    except (CorpusError, HandError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    clone = clone_dir(clones_dir, corpus_repo.slug)
    base = corpus_repo.base_commit
    if not clone.exists() or not rev_exists(clone, base):
        print("no clone at the base commit; run `mine` first", file=sys.stderr)
        return 1
    items = [item for item in hand if item.reference_answer and item.gold_files]
    if not items:
        print(f"no hand items with a reference answer for {repo_name}", file=sys.stderr)
        return 1
    prices = table or PriceTable.load(PRICES_PATH)
    try:
        endpoint.require_key()
        prices.require_complete([endpoint.model])
    except (JudgeConfigError, PricesIncomplete) as failure:
        print(str(failure), file=sys.stderr)
        return 1

    directory = _gold_dir(out_dir, repo_name)
    path = checks_path(directory, endpoint)
    budget.spent_usd = spent_on_disk(read_checks(path))
    kwargs: dict[str, Any] = {} if clock is None else {"clock": clock}
    result = asyncio.run(
        check_items(
            items,
            endpoint=endpoint,
            out_path=path,
            budget=budget,
            table=prices,
            read_file=lambda _item, file_path: show_file(clone, base, file_path),
            client_factory=client_factory,
            meter=Meter(),
            concurrency=concurrency,
            **kwargs,
        )
    )
    print_fn(
        f"{result.ok} checked, {result.skipped} already done, {result.errors} errors; "
        f"spent ${result.spent_usd:.4f} of ${budget.cap_usd:.2f}"
    )
    if result.stopped:
        print_fn(f"stopped: {result.stopped}")
    outcome = apply_checks(items, all_checks(directory))
    supported = len(outcome.kept) - len(outcome.partly_supported) - len(outcome.unchecked)
    print_fn(
        f"supported {supported}, partly supported {len(outcome.partly_supported)}, "
        f"unsupported {len(outcome.unsupported)}, unchecked {len(outcome.unchecked)}"
    )
    for item, record in outcome.partly_supported:
        print_fn(f"partly supported, fix: {item.question[:80]!r}: {record.faulty_claim}")
    for item in outcome.unsupported:
        print_fn(f"unsupported, dropped by `gold build`: {item.question[:80]!r}")
    if result.errors:
        print_fn("some checks failed; running the command again retries them")
    print_fn(f"checks: {path}")
    return 1 if (result.errors or result.stopped or outcome.unchecked) else 0
