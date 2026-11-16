"""The context MCP tool calls run in."""

from __future__ import annotations

import uuid
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.repository import Repository
from app.services.agent.tools.context import RepoSnapshot, ToolContext
from app.services.llm_config import LLMConfig
from app.services.retrieval.channels.base import no_emit
from app.services.retrieval.config import (
    STRUCTURAL,
    PipelineConfig,
    QueryConfig,
    RerankConfig,
)
from app.services.retrieval.embedding import embed_texts

MCP_PIPELINE = PipelineConfig(
    name="mcp",
    query=QueryConfig(transform="identity", condense=False),
    channels=STRUCTURAL.channels,
    fusion=STRUCTURAL.fusion,
    rrf_k=STRUCTURAL.rrf_k,
    rerank=RerankConfig(kind="none"),
    diversify=STRUCTURAL.diversify,
)
"""What ``search_code`` runs over MCP: the structural channels, with every model stage off.

The extra channels (grep, graph, co-change, history) only read the database, so
they cost nothing over a hybrid search and rank better. There is no query
rewrite and no reranker, so a search spends one embedding call on the operator's
key and nothing else; the host's own model does the reasoning.
"""


def build_tool_context(
    repo: Repository,
    github_token: str | None,
    *,
    session_factory: async_sessionmaker[AsyncSession],
) -> ToolContext:
    """The context for one tool call on one of the caller's repositories.

    Args:
        repo: The repository the call is about, already checked to be the caller's.
        github_token: The caller's GitHub token, so ``read_file`` can read a private
            repository; ``None`` reads it unauthenticated.
        session_factory: Opens the session each tool uses for its own queries.

    Returns:
        A context with no run budget and no progress events.
    """
    return ToolContext(
        run_id=uuid.uuid4(),
        repository=RepoSnapshot.from_repository(repo),
        session_factory=session_factory,
        # ``None`` when the operator has no free-tier key. No stage of
        # ``MCP_PIPELINE`` reads it and ``retrieve`` accepts ``None``; the field is
        # annotated non-optional because the agent always has a credential.
        llm=cast(LLMConfig, LLMConfig.server_default()),
        pipeline=MCP_PIPELINE,
        github_token=github_token,
        budget=None,
        emit=no_emit,
        # Looked up here, not bound as a default, so a test can substitute it.
        embed=embed_texts,
        question=None,
    )
