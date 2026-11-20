"""``gold build``: generate a repository's gold items."""

import asyncio
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from evals.corpus.corpus import CORPUS_PATH, CorpusError, load_corpus
from evals.gold.build import DEFAULT_SEED, TARGETS, BuildOutcome, GoldBuildError, build_gold
from evals.gold.hand import HandError


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
