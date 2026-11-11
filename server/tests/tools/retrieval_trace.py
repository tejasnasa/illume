"""Print which retrieval channels found which files for one fixture question.

Run from ``server/``::

    uv run python -m tests.tools.retrieval_trace
    uv run python -m tests.tools.retrieval_trace "What relies on RateLimiter?"
    uv run python -m tests.tools.retrieval_trace cochange --preset hybrid
    uv run python -m tests.tools.retrieval_trace grep-long-function --preset hybrid --with-grep
    uv run python -m tests.tools.retrieval_trace --list

The argument is a free-text question or the id of a question in
``RETRIEVAL_QUESTIONS``; with an id (or a question that matches one), the gold
items are marked ``*``. ``--preset`` picks ``classic``, ``hybrid``,
``hybrid_rerank`` or ``structural`` (the default). ``--with-grep`` adds the grep
channel to a preset that lacks it, such as ``hybrid``.

The output has three parts: each channel's ranked keys, the fused order with every
candidate's channel hits, and the final list after reranking and diversification.

**This only ever touches the test database.** Importing ``tests.conftest`` forces
``DATABASE_URL``, ``SYNC_DATABASE_URL`` and ``REDIS_URL`` to the test stack before
any ``app`` module is imported, exactly as the test suite does, and the checks
below refuse to continue unless they all name a test-stack port. The fixture
repository is seeded inside a transaction that is rolled back on exit, so nothing
is left behind. The test stack must be running and migrated (``make test-infra``,
then ``make migrate-test`` or one run of the backend suite).
"""

from __future__ import annotations

# The environment bootstrap has to run before any ``app`` import, so this import
# is first and is not sorted away.
import tests.conftest as _bootstrap  # isort: skip  # noqa: I001

import argparse
import asyncio
import os
import sys
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

TEST_PORTS = ("5433", "6380")


def _assert_test_stack() -> None:
    """Refuse to run unless every connection setting names a test-stack port."""
    for key in ("DATABASE_URL", "SYNC_DATABASE_URL", "REDIS_URL"):
        value = os.environ.get(key, "")
        if not any(f":{port}/" in value for port in TEST_PORTS):
            sys.exit(f"refusing to run: {key} does not point at the test stack ({value!r})")
    from app.core.config import settings

    for name in ("DATABASE_URL", "SYNC_DATABASE_URL"):
        value = str(getattr(settings, name))
        if ":5433/" not in value:
            sys.exit(f"refusing to run: settings.{name} is not the test database ({value!r})")


_assert_test_stack()

from app.core.config import settings  # noqa: E402
from app.services.retrieval.candidate import Candidate  # noqa: E402
from app.services.retrieval.channels.base import RetrievalContext  # noqa: E402
from app.services.retrieval.config import PRESETS, GrepChannel, PipelineConfig  # noqa: E402
from app.services.retrieval.pipeline import RetrievalResult, retrieve  # noqa: E402
from tests.factories import make_user  # noqa: E402
from tests.fixtures.retrieval import (  # noqa: E402
    RETRIEVAL_FIXTURE,
    RETRIEVAL_QUESTIONS,
    fake_embedder,
    matches_gold,
    rolled_back_session,
    seed_repo,
)

DEFAULT_QUESTION = "What relies on RateLimiter?"
SINGLE_SHOT_PRESETS = ("classic", "hybrid", "hybrid_rerank", "structural")


def _short(key: str, width: int = 58) -> str:
    return key if len(key) <= width else key[: width - 1] + "…"


def _resolve_question(argument: str):
    """The question text, and the known question it matches (if any)."""
    for question in RETRIEVAL_QUESTIONS:
        if argument in (question.id, question.text):
            return question.text, question
    return argument, None


def _config(preset: str, with_grep: bool) -> PipelineConfig:
    config = PRESETS[preset]
    if with_grep and config.channel("grep") is None:
        config = config.model_copy(
            update={"name": f"{config.name}+grep", "channels": (*config.channels, GrepChannel())}
        )
    return config


def render(result: RetrievalResult, config: PipelineConfig, known) -> str:
    """The three-part report for one retrieval."""
    gold = known.gold if known else ()

    def mark(candidate) -> str:
        return "*" if any(matches_gold(candidate, item) for item in gold) else " "

    lines = [f"question : {result.question}"]
    if known:
        lines += [f"gold     : {', '.join(gold)}", f"designed : {known.needs}"]
    lines += [
        f"preset   : {config.name} ({', '.join(c.kind for c in config.channels)})",
        f"config   : {result.trace.config_hash[:12]}",
        "",
        "== per channel, ranked (variant 0) ==",
    ]

    by_channel: dict[str, list[tuple[int, Candidate]]] = defaultdict(list)
    for candidate in result.pool:
        for hit in candidate.channel_hits:
            if hit.variant == 0:
                by_channel[hit.channel].append((hit.rank, candidate))
    for trace in result.trace.channels:
        if trace.variant != 0:
            continue
        ranked = sorted(by_channel.get(trace.channel, []), key=lambda pair: pair[0])
        status = f"error: {trace.error}" if trace.error else f"{trace.candidates} found"
        lines.append(f"{trace.channel:<8} [{trace.stage}] {status}, {trace.ms:.1f} ms")
        for rank, candidate in ranked[:8]:
            lines.append(f"   {rank:>2}. {mark(candidate)} {_short(candidate.key)}")
        if len(ranked) > 8:
            lines.append(f"   ... {len(ranked) - 8} more")

    lines += ["", "== fused order, with channel hits (top 12 of the pool) =="]
    for position, candidate in enumerate(result.pool[:12], start=1):
        hits = ", ".join(f"{hit.channel}#{hit.rank}" for hit in candidate.channel_hits)
        score = candidate.fused_score or 0.0
        key = _short(candidate.key, 46)
        lines.append(f"{position:>3}. {mark(candidate)} {key:<46} {score:.4f}  [{hits}]")

    lines += ["", "== final list =="]
    for position, candidate in enumerate(result.candidates, start=1):
        lines.append(f"{position:>3}. {mark(candidate)} {_short(candidate.key, 70)}")
    if result.trace.degraded:
        lines += ["", "degraded : " + "; ".join(str(d) for d in result.trace.degraded)]
    return "\n".join(lines)


async def _main(question: str, preset: str, with_grep: bool) -> str:
    text_, known = _resolve_question(question)
    config = _config(preset, with_grep)
    engine = create_async_engine(_bootstrap.TEST_DB_URL, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            current = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one_or_none()
        if current is None:
            sys.exit("the test database is not migrated; run `make migrate-test`")

        async with rolled_back_session(engine) as db:
            user = await make_user(db)
            seeded = await seed_repo(db, user, RETRIEVAL_FIXTURE)
            ctx = RetrievalContext(repository_id=seeded.repo.id, db=db, embed=fake_embedder())
            # No reranker or query-rewrite key is ever used here: with these empty the
            # model-backed stages degrade to the fused order, as they do in CI.
            settings.OPENROUTER_API_KEY = ""
            result = await retrieve(config, text_, ctx=ctx)
        return render(result, config, known)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    parser.add_argument("--preset", choices=SINGLE_SHOT_PRESETS, default="structural")
    parser.add_argument("--with-grep", action="store_true", help="also enable the grep channel")
    parser.add_argument("--list", action="store_true", help="list the fixture questions and exit")
    args = parser.parse_args(argv)

    if args.list:
        for question in RETRIEVAL_QUESTIONS:
            print(f"{question.id:<22} {question.text}")
        return
    print(asyncio.run(_main(args.question, args.preset, args.with_grep)))


if __name__ == "__main__":
    main()
