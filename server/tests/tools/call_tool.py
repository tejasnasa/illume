"""Call any agent tool by name with JSON arguments, against the fixture repository.

Run from ``server/``::

    uv run python -m tests.tools.call_tool --list
    uv run python -m tests.tools.call_tool grep_code '{"pattern": "bcrypt"}'
    uv run python -m tests.tools.call_tool get_importers '{"path": "app/auth/security.py"}'
    uv run python -m tests.tools.call_tool get_overview
    uv run python -m tests.tools.call_tool list_files '{"path_prefix": "app/auth/"}' --json
    uv run python -m tests.tools.call_tool read_symbol '{"name": "verify_password"}' --schema

The output is the text the model would be shown. ``--json`` adds the structured result
that goes to the step log, and ``--schema`` prints the function-tool definition (add
``--strict`` for the strict form).

The repository is the 30-file retrieval fixture, seeded with a guide, a glossary entry
and an owner, inside a transaction that is rolled back on exit. Queries are embedded
with the deterministic fake embedder, so ``search_code`` and ``search_history`` rank by
keyword only, and no model key is used. ``read_file`` is the one tool that leaves the
machine: it calls the real GitHub API for ``example/example-repo``, so it reports "not
found" unless ``--github-url`` points the repository at a public repository whose files
match the fixture's paths.

**This only ever touches the test database.** Importing ``tests.conftest`` forces
``DATABASE_URL``, ``SYNC_DATABASE_URL`` and ``REDIS_URL`` to the test stack before any
``app`` module is imported, and the checks below refuse to continue unless they all name
a test-stack port. The test stack must be running and migrated (``make test-infra``, then
``make migrate-test`` or one run of the backend suite).
"""

from __future__ import annotations

# The environment bootstrap has to run before any ``app`` import, so this import
# is first and is not sorted away.
import tests.conftest as _bootstrap  # isort: skip  # noqa: I001

import argparse
import asyncio
import json
import os
import sys
from typing import Any

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
from app.services.agent.tools import REGISTRY  # noqa: E402
from tests.factories import make_user  # noqa: E402
from tests.fixtures.agent_tools import (  # noqa: E402
    make_tool_context,
    seed_tool_repos,
    session_factory_for,
)
from tests.fixtures.retrieval import rolled_back_session  # noqa: E402


def _list_tools() -> str:
    rows = []
    for tool in REGISTRY:
        summary = tool.description.split(". ")[0].rstrip(".")
        rows.append(f"{tool.name:<16} {tool.cost:<8} {summary}")
    return "\n".join(rows)


async def _main(name: str, arguments: str, github_url: str | None) -> tuple[str, dict[str, Any]]:
    engine = create_async_engine(_bootstrap.TEST_DB_URL, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            current = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one_or_none()
        if current is None:
            sys.exit("the test database is not migrated; run `make migrate-test`")

        async with rolled_back_session(engine) as db:
            repos = await seed_tool_repos(db, await make_user(db))
            if github_url:
                repos.a.repo.github_url = github_url
                await db.flush()
            ctx = make_tool_context(session_factory_for(db.bind), repos.a.repo)
            # With these empty, the model-backed stages degrade to the plain order, as in CI.
            settings.OPENROUTER_API_KEY = ""
            settings.COHERE_API_KEY = ""
            result = await REGISTRY.call(name, arguments, ctx)
        report = result.model_dump(mode="json")
        header = f"[{result.tool}: {result.status}, {result.elapsed_ms:.1f} ms"
        header += ", truncated]" if result.truncated else "]"
        return f"{header}\n{result.text}", report
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tool", nargs="?", help="the tool name")
    parser.add_argument("arguments", nargs="?", default="{}", help="the arguments as JSON")
    parser.add_argument("--list", action="store_true", help="list the tools and exit")
    parser.add_argument("--json", action="store_true", help="also print the structured result")
    parser.add_argument("--schema", action="store_true", help="print the tool definition and exit")
    parser.add_argument("--strict", action="store_true", help="with --schema, the strict form")
    parser.add_argument("--github-url", help="the repository address read_file will use")
    args = parser.parse_args(argv)

    if args.list or not args.tool:
        print(_list_tools())
        return
    try:
        REGISTRY.get(args.tool)
    except KeyError as error:
        sys.exit(str(error))
    if args.schema:
        (definition,) = REGISTRY.function_tools([args.tool], strict=args.strict)
        print(json.dumps(definition, indent=2))
        return

    text_, report = asyncio.run(_main(args.tool, args.arguments, args.github_url))
    print(text_)
    if args.json:
        print("\n" + json.dumps(report.get("data"), indent=2))


if __name__ == "__main__":
    main()
