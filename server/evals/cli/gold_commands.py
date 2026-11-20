"""``gold build``: generate a repository's gold items."""

import asyncio
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from evals.corpus.corpus import CORPUS_PATH, CorpusError, load_corpus
from evals.gold.build import DEFAULT_SEED, TARGETS, BuildOutcome, GoldBuildError, build_gold
from evals.gold.hand import HandError
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
from evals.mining.clones import clone_dir, rev_exists

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
) -> BuildOutcome:
    corpus_repo = load_corpus(corpus_path).get(repo_name)
    engine = create_async_engine(async_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            return await build_gold(
                db, corpus_repo=corpus_repo, out_dir=out_dir, clones_dir=clones_dir, seed=seed
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
) -> int:
    """Build one repository's gold items and print the counts against the targets.

    Args:
        async_url: The eval database's async URL.
        out_dir: The eval output directory.
        clones_dir: Where harness clones live.
        repo_name: The corpus entry to build.
        corpus_path: The corpus file.
        seed: The sampling seed.

    Returns:
        The process exit status.
    """
    try:
        outcome = asyncio.run(
            _run(
                async_url=async_url,
                out_dir=out_dir,
                clones_dir=clones_dir,
                repo_name=repo_name,
                corpus_path=corpus_path,
                seed=seed,
            )
        )
    except (CorpusError, GoldBuildError, HandError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for family, target in TARGETS.items():
        found = outcome.counts.get(family, 0)
        print(f"{family:<11} {found:>4} (target {target} after verification)")
    for reason, count in outcome.log["drops"].items():
        print(f"dropped {reason}: {count}")
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
    api_key: str,
    repo_name: str,
    corpus_path: Path = CORPUS_PATH,
    client_factory: Callable[[], Any] | None = None,
) -> int:
    """Phrase a repository's built items and write the phrased file.

    Args:
        out_dir: The eval output directory.
        clones_dir: Where harness clones live.
        api_key: The key for the phraser; required unless ``client_factory`` is given.
        repo_name: The corpus entry.
        corpus_path: The corpus file.
        client_factory: Builds the model client; the real OpenAI client when omitted.

    Returns:
        The process exit status.
    """
    directory = _gold_dir(out_dir, repo_name)
    source = directory / ITEMS
    if not source.exists():
        print(f"{source} not found; run `gold build` first", file=sys.stderr)
        return 1
    if client_factory is None:
        if not api_key:
            print("OPENAI_API_KEY is not set in server/evals/.env.eval", file=sys.stderr)
            return 1

        def client_factory() -> Any:
            from openai import AsyncOpenAI

            return AsyncOpenAI(api_key=api_key)

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
            cache_path=directory / "phrased.jsonl",
            leak_context=make_leak_context_factory(clone, corpus_repo.base_commit),
            concurrency=PHRASE_CONCURRENCY,
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
    pilot: bool,
    seed: int = DEFAULT_SEED,
) -> int:
    """Split the items into slices and write the lock.

    Args:
        out_dir: The eval output directory.
        repo_name: Restrict to one repository.
        all_repos: Use every repository that has items.
        pilot: Put everything in one ``pilot`` slice.
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
