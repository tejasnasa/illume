"""Run the agent on three fixture questions against a real model.

Run from ``server/``::

    AGENT_SMOKE_API_KEY=sk-... uv run python -m tests.tools.agent_smoke
    AGENT_SMOKE_API_KEY=... AGENT_SMOKE_PROVIDER=deepseek AGENT_SMOKE_MODEL=... \\
        uv run python -m tests.tools.agent_smoke --question 2

The provider defaults to ``openai`` and the model to that provider's default. The key is
read from ``AGENT_SMOKE_API_KEY`` only, never from ``server/.env``. This is not part of CI
and **spends real credit**: each question is a full agent run on your key. It prints, per
question, the stop reason, tokens used, the tools called in order and the answer.

The repository is the 30-file retrieval fixture, seeded inside a transaction that is rolled
back on exit, on the test database. Queries are embedded with the deterministic fake
embedder, so retrieval ranks by keyword only, and ``read_file`` reaches GitHub for
``example/example-repo``, which does not exist; the agent should route around that.

The same refusal as the tool script applies: it exits unless every connection setting names
a test-stack port.
"""

from __future__ import annotations

# The environment bootstrap has to run before any ``app`` import, so this import
# is first and is not sorted away.
import tests.conftest as _bootstrap  # isort: skip  # noqa: I001

import argparse
import asyncio
import os
import sys

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.tools.call_tool import _assert_test_stack

_assert_test_stack()

from app.core.config import settings  # noqa: E402
from app.services.agent.events import EventLog  # noqa: E402
from app.services.agent.runner import run_agent  # noqa: E402
from app.services.agent.tools.context import RepoSnapshot  # noqa: E402
from app.services.llm_config import LLMConfig  # noqa: E402
from app.services.llm_providers import get_provider  # noqa: E402
from app.services.retrieval.config import DEEP_AGENT  # noqa: E402
from tests.factories import make_user  # noqa: E402
from tests.fixtures.agent_tools import seed_tool_repos, session_factory_for  # noqa: E402
from tests.fixtures.retrieval import fake_embedder, rolled_back_session  # noqa: E402

QUESTIONS = (
    "Where is `verify_password` defined, and what does it do?",
    "What relies on RateLimiter, and how do those files reach it?",
    "Why was password hashing switched to bcrypt?",
)


def _llm() -> LLMConfig:
    key = os.environ.get("AGENT_SMOKE_API_KEY")
    if not key:
        sys.exit("set AGENT_SMOKE_API_KEY to a real provider key")
    provider = get_provider(os.environ.get("AGENT_SMOKE_PROVIDER", "openai"))
    return LLMConfig(
        api_key=key,
        model=os.environ.get("AGENT_SMOKE_MODEL") or provider.default_model,
        base_url=provider.base_url,
        supports_reasoning=provider.supports_reasoning,
        source="user",
        supports_strict_tools=provider.supports_strict_tools,
    )


async def _main(selected: list[int]) -> None:
    llm = _llm()
    settings.OPENROUTER_API_KEY = ""
    engine = create_async_engine(_bootstrap.TEST_DB_URL, poolclass=NullPool)
    try:
        async with rolled_back_session(engine) as db:
            repos = await seed_tool_repos(db, await make_user(db))
            snapshot = RepoSnapshot.from_repository(repos.a.repo)
            for number in selected:
                question = QUESTIONS[number - 1]
                events = EventLog()
                result = await run_agent(
                    question,
                    (),
                    repository=snapshot,
                    session_factory=session_factory_for(db.bind),
                    llm=llm,
                    config=DEEP_AGENT,
                    embed=fake_embedder(),
                    emit=events,
                )
                tools = [p["tool"] for p in events.named("tool_call")]
                print(f"\n=== {number}. {question}")
                print(
                    f"status={result.status} stop={result.stop_reason.value} "
                    f"turns={result.iterations} input_tokens={result.input_tokens} "
                    f"seconds={result.elapsed_seconds}"
                )
                print("tools:", " -> ".join(tools) or "(none)")
                if result.error:
                    print("error:", result.error.message)
                print(result.answer)
                if result.unresolved:
                    print("unresolved citations:", ", ".join(result.unresolved))
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--question", type=int, choices=[1, 2, 3], help="run only this question")
    args = parser.parse_args(argv)
    asyncio.run(_main([args.question] if args.question else [1, 2, 3]))


if __name__ == "__main__":
    main()
