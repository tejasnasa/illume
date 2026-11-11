"""What every tool handler is handed besides its arguments."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Repository
from app.services.llm_config import LLMConfig
from app.services.retrieval.channels.base import Embedder, Emit, RetrievalContext, no_emit
from app.services.retrieval.config import PipelineConfig
from app.services.retrieval.dates import DateRange
from app.services.retrieval.embedding import embed_texts


class SharedBudget(Protocol):
    """Counts the limits of one run across everything that shares it.

    One object serves the whole run, so every counter is read and changed behind
    one lock: a limit is enforced the moment it is crossed, not at the next
    point where concurrent updates are merged.
    """

    async def reserve_tool_calls(self, count: int) -> int:
        """Claims up to ``count`` tool calls and returns how many were granted."""
        ...

    async def add_usage(self, input_tokens: int, output_tokens: int = 0) -> None:
        """Adds the tokens a provider reported for one model call."""
        ...

    async def exceeded(self) -> str | None:
        """The name of a limit that has been reached, or ``None`` when none has."""
        ...


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
        budget: The run's shared limits, if there are any.
        emit: Where progress and degradation events go.
        embed: How query text becomes vectors.
        question: The run's question as typed, which ``search_history`` reads a
            time span from when the model gives none.
    """

    run_id: UUID
    repository: RepoSnapshot
    session_factory: async_sessionmaker[AsyncSession]
    llm: LLMConfig
    pipeline: PipelineConfig
    worker_id: str | None = None
    github_token: str | None = None
    budget: SharedBudget | None = None
    emit: Emit = field(default=no_emit)
    embed: Embedder = field(default=embed_texts)
    question: str | None = None

    def retrieval(self, db: AsyncSession, date_range: DateRange | None = None) -> RetrievalContext:
        """A retrieval context over this repository for one call's session.

        Args:
            db: The call's own session.
            date_range: A time span to restrict history to; ``None`` lets the
                pipeline read one from the question.
        """
        return RetrievalContext(
            repository_id=self.repository.id,
            db=db,
            embed=self.embed,
            emit=self.emit,
            date_range=date_range,
        )
