"""Two copies of the retrieval fixture repository, wired for the agent tools.

Both repositories hold the same files, symbols and import graph, so a tool that
joined on a path or a name instead of the repository would return the other
copy's rows. They differ only by a marker written into the copy's free text
(symbol bodies, commit messages, glossary, owner, guide), which is what a test
looks for to prove nothing crossed over.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Repository, User
from app.services.agent.tools.context import RepoSnapshot, ToolContext
from app.services.retrieval.config import HYBRID
from tests.factories import make_code_owner, make_glossary_entry, make_guide
from tests.fixtures.retrieval import (
    RETRIEVAL_FIXTURE,
    RepoSpec,
    SeededRepo,
    SymbolSpec,
    fake_embedder,
    make_llm,
    seed_repo,
)

MARKER = "B_MARKER"

SECURITY = "app/auth/security.py"


def session_factory_for(connection) -> async_sessionmaker[AsyncSession]:
    """Sessions that join a test's open transaction, so tools see its uncommitted rows."""
    return async_sessionmaker(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )


def _marked_symbol(symbol: SymbolSpec, marker: str) -> SymbolSpec:
    # The marker goes at the end of the first line, so line numbers do not move.
    first, newline, rest = symbol.source_code.partition("\n")
    return replace(symbol, source_code=f"{first}  # {marker}{newline}{rest}")


def marked_spec(spec: RepoSpec, marker: str) -> RepoSpec:
    """The spec with ``marker`` written into its symbol bodies, commits and pull requests."""
    files = tuple(
        replace(f, symbols=tuple(_marked_symbol(s, marker) for s in f.symbols)) for f in spec.files
    )
    return replace(
        spec,
        files=files,
        commits=tuple(replace(c, message=f"{c.message} {marker}") for c in spec.commits),
        pull_requests=tuple(
            replace(p, title=f"{p.title} {marker}", chunk_text=None) for p in spec.pull_requests
        ),
    )


async def _seed_extras(db: AsyncSession, seeded: SeededRepo, marker: str) -> None:
    """The guide, glossary and ownership rows ingestion would have written."""
    suffix = f" {marker}" if marker else ""
    await make_guide(
        db,
        seeded.repo,
        reading_order=[
            {
                "path": SECURITY,
                "tier": 0,
                "position": 1,
                "annotation": f"Start here: password hashing.{suffix}",
                "fan_in": 5,
            }
        ],
        critical_files=[
            {
                "path": SECURITY,
                "criticality": "critical",
                "reasons": ["imported by many files"],
                "fan_in": 5,
            }
        ],
        architecture_brief={
            "narrative": f"A small web API with auth, billing and jobs.{suffix}",
            "tech_stack": {"language": "python"},
            "entry_points": ["app/main.py"],
        },
    )
    await make_glossary_entry(
        db,
        seeded.repo,
        name="password hashing",
        definition=f"Storing passwords as salted bcrypt digests.{suffix}",
        file_path=SECURITY,
        line_number=10,
    )
    await make_code_owner(
        db,
        seeded.files[SECURITY],
        primary_owner=f"Grace Hopper{suffix}",
        bus_factor=2,
        is_knowledge_silo=False,
    )


@dataclass(frozen=True)
class ToolRepos:
    """The two seeded repositories.

    Attributes:
        a: The repository the tests ask about.
        b: The copy that must never show up in a result for ``a``.
    """

    a: SeededRepo
    b: SeededRepo


async def seed_tool_repos(db: AsyncSession, user: User) -> ToolRepos:
    """Seeds repository A, and repository B with the same paths and the marker."""
    a = await seed_repo(db, user, RETRIEVAL_FIXTURE, name="tools-a")
    b = await seed_repo(db, user, marked_spec(RETRIEVAL_FIXTURE, MARKER), name="tools-b")
    await _seed_extras(db, a, "")
    await _seed_extras(db, b, MARKER)
    return ToolRepos(a=a, b=b)


def make_tool_context(
    session_factory: async_sessionmaker[AsyncSession], repo: Repository, **overrides: Any
) -> ToolContext:
    """A tool context over one repository, with the fake query embedder."""
    fields: dict[str, Any] = {
        "run_id": uuid.uuid4(),
        "repository": RepoSnapshot.from_repository(repo),
        "session_factory": session_factory,
        "llm": make_llm(),
        "pipeline": HYBRID,
        "embed": fake_embedder(),
    }
    fields.update(overrides)
    return ToolContext(**fields)
