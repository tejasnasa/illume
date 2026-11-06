"""What every tool handler is handed besides its arguments."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Repository
from app.services.llm_config import LLMConfig
from app.services.retrieval.channels.base import Embedder, Emit, RetrievalContext
from app.services.retrieval.config import PipelineConfig
from app.services.retrieval.embedding import embed_texts


class Decider(Protocol):
    """Makes the narrow yes/no and choice decisions of an agent run.

    No tool consults it; the context carries one so the loop that owns the
    decisions can reach it through the same object it hands to tools.
    """


class SharedBudget(Protocol):
    """Counts the limits of one run across the tool calls that share it.

    No tool charges it; it is carried for the same reason as :class:`Decider`.
    """


class NodeEvent(BaseModel):
    """Files a tool call looked at, for highlighting them in the dependency graph.

    Attributes:
        paths: Repository-relative paths of the files involved.
        action: How the tool used them, such as ``touched`` or ``path``.
    """

    model_config = ConfigDict(frozen=True)

    paths: tuple[str, ...]
    action: str = "touched"


@dataclass(frozen=True)
class RepoSnapshot:
    """The repository facts a tool needs, copied out of the ORM row.

    Attributes:
        id: The only repository a tool may read.
        github_url: Where the repository lives, for reading whole files.
        ingested_branch: The branch that was ingested.
        ingested_commit_sha: The commit every stored row reflects.
    """

    id: UUID
    github_url: str
    ingested_branch: str | None
    ingested_commit_sha: str | None

    @classmethod
    def from_repository(cls, repository: Repository) -> RepoSnapshot:
        """Copies the fields out, so no ORM instance crosses between tool calls."""
        return cls(
            id=repository.id,
            github_url=repository.github_url,
            ingested_branch=repository.ingested_branch,
            ingested_commit_sha=repository.ingested_commit_sha,
        )


async def _discard(event: str, payload: dict[str, Any]) -> None:
    """The default emitter, for callers that do not stream progress."""


@dataclass(frozen=True)
class ToolContext:
    """Everything a tool call may use.

    **Concurrency.** An ``AsyncSession`` is not safe to use from two tasks at
    once, and tool calls and workers run concurrently. The context therefore
    holds a ``session_factory``, never a session: each call opens its own with
    ``async with ctx.session_factory() as db`` for the length of that call. No
    ORM instance crosses between calls either; handlers return plain Pydantic
    models.

    Attributes:
        run_id: The agent run this call belongs to.
        worker_id: The worker making the call, or ``None`` for the main agent.
        repository: The repository being explored.
        session_factory: Opens one session per tool call.
        github_token: The repository owner's GitHub token, or ``None``.
        llm: Credentials for the calls tools make to a model.
        pipeline: The retrieval settings ``search_code`` runs.
        decider: The run's decision maker, if there is one.
        budget: The run's shared limits, if there are any.
        emit: Where progress and degradation events go.
        embed: How query text becomes vectors.
    """

    run_id: UUID
    repository: RepoSnapshot
    session_factory: async_sessionmaker[AsyncSession]
    llm: LLMConfig
    pipeline: PipelineConfig
    worker_id: str | None = None
    github_token: str | None = None
    decider: Decider | None = None
    budget: SharedBudget | None = None
    emit: Emit = field(default=_discard)
    embed: Embedder = field(default=embed_texts)

    def retrieval(self, db: AsyncSession) -> RetrievalContext:
        """A retrieval context over this repository for one call's session."""
        return RetrievalContext(
            repository_id=self.repository.id, db=db, embed=self.embed, emit=self.emit
        )
