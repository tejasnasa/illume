"""Retrieval-augmented question answering over a repository.

:func:`answer_question` is the chat endpoint's entry point. It runs the Classic
preset of the retrieval pipeline (see :mod:`app.services.retrieval`): embed the
query, search stored embeddings in pgvector by cosine distance, apply per-source-type
diversity caps, resolve the hits to their underlying records in one query per
source type, and prompt an LLM with the assembled context to produce a grounded
answer plus source references.

The pgvector search, the caps and the resolver also live on here as the helpers
that path was built from (:func:`_vector_search`, :func:`_apply_diversity_caps`,
:func:`_resolve_source`). They are kept because other code and tests import them,
and because they are the reference the Classic preset is held equal to.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal, Sequence
from uuid import UUID

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Embedding
from app.services.llm_config import LLMConfig
from app.services.retrieval.channels.base import RetrievalContext
from app.services.retrieval.config import CLASSIC
from app.services.retrieval.resolve import SourceReference, resolve_sources
from app.services.retrieval.single_shot import answer, build_classic_prompt
from app.services.retrieval.vector import prepare_filtered_vector_search

logger = logging.getLogger(__name__)

TOP_K = 10

# Max chunks of each source type allowed in one answer's context, so no
# single source type crowds out the others.
TYPE_CAPS = {
    "symbol": 5,
    "commit": 2,
    "pull_request": 1,
    "document": 1,
    "file": 2,
}


@dataclass
class RAGResponse:
    """Final RAG result: generated answer text and its source citations.

    Attributes:
        answer: The model's response text, or the canned fallback when
            retrieval returned nothing.
        sources: Citation objects backing each chunk the model saw. Empty
            when nothing survived the similarity filter.
        generated: ``True`` when the LLM was called and produced an
            answer; ``False`` when the pipeline short-circuited on its
            no-context early return. The chat route charges a free-tier
            message only when this is ``True``; inferring the same fact
            from ``sources`` would let a stubbed answer bypass the quota.
    """

    answer: str
    sources: list[SourceReference]
    generated: bool = False


@dataclass
class ChatMessage:
    """One prior conversation turn replayed into the LLM prompt."""

    role: Literal["user", "assistant"]
    content: str


def _apply_diversity_caps(embeddings: Sequence[Embedding], total: int = TOP_K) -> list[Embedding]:
    """Selects up to `total` hits while respecting per-type caps, then fills any remaining slots by relevance order."""
    type_counts: defaultdict[str, int] = defaultdict(int)
    selected = []

    for e in embeddings:
        cap = TYPE_CAPS.get(e.source_type, 2)
        # Pass 1: take hits in relevance order until each type's cap fills,
        # guaranteeing representation for every source type.
        if type_counts[e.source_type] < cap:
            selected.append(e)
            type_counts[e.source_type] += 1
        if len(selected) == total:
            return selected

    # Pass 2: backfill any unfilled slots with the next-best hits overall.
    for e in embeddings:
        if e not in selected:
            selected.append(e)
        if len(selected) == total:
            return selected

    return selected


async def _embed_query(client: AsyncOpenAI, query: str) -> list[float]:
    """Embeds the query with text-embedding-3-small."""
    response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=query,
    )
    return response.data[0].embedding


async def _vector_search(db: AsyncSession, repository_id, query_vector, top_k=TOP_K):
    """Finds nearest embeddings via pgvector cosine distance, filtered to similarity above 0.3 (distance < 0.7)."""
    # The repository filter is applied after the index walk, so tell pgvector to
    # keep scanning until it has enough surviving rows (see the helper).
    await prepare_filtered_vector_search(db)
    result = await db.execute(
        select(Embedding)
        .filter(
            Embedding.repository_id == repository_id,
            # Distance < 0.7 ≈ cosine similarity > 0.3: prune weak matches so
            # diversity caps can't waste slots on irrelevant chunks.
            Embedding.embedding.cosine_distance(query_vector) < 0.7,
        )
        .order_by(Embedding.embedding.cosine_distance(query_vector))
        .limit(50)
    )
    embeddings = result.scalars().all()
    return _apply_diversity_caps(embeddings, top_k)


async def _resolve_source(db: AsyncSession, embedding: Embedding) -> SourceReference:
    """Loads the record behind one embedding hit and builds its citation.

    Kept for callers that hold a single hit; the batched
    :func:`app.services.retrieval.resolve.resolve_sources` is what the answer
    path uses, so a larger candidate pool does not mean one query per hit.
    """
    resolved = await resolve_sources(db, [embedding])
    return resolved[0]


# The Classic prompt lives with the answerer that uses it; this name stays for importers.
_build_prompt = build_classic_prompt


async def answer_question(
    query: str,
    repository_id: UUID,
    db: AsyncSession,
    history: list[ChatMessage] | None = None,
    *,
    llm: LLMConfig | None = None,
) -> RAGResponse:
    """Answer a natural-language question about a repository.

    Runs the Classic preset through :func:`app.services.retrieval.single_shot.answer`:
    embed the query, run a pgvector cosine-distance search scoped to the
    repository, cap results per source type for diversity, resolve each hit to a
    citable source, then prompt the LLM with the retrieved context, prior chat
    history, and the question. The model is instructed to answer only from the
    provided context. The behaviour is the chat endpoint's long-standing one,
    byte for byte; this function only supplies the clients.

    Args:
        query: The user's question.
        repository_id: Repository whose embeddings to search.
        db: Async SQLAlchemy session for vector search and lookups.
        history: Optional prior conversation turns included before the new
            user message.
        llm: The credential bundle forwarded to the generation call.
            ``None`` falls through to the server key -- the route layer's
            quota gates are what make ``None``
            legitimate in production. The **embedding** client is always
            the server key by decision: a per-user embedding key would
            make the index provider-dependent and trigger a migration,
            since the 1536 dimensions are baked into the schema.

    Returns:
        A :class:`RAGResponse` carrying ``generated=False`` (and a canned
        answer with empty ``sources``) when retrieval returned nothing --
        the LLM was never called. When generation succeeds, ``generated``
        is ``True``. The flag is what the chat route uses to decide
        whether to charge a free-tier message; inferring the same fact
        from a non-empty ``sources`` would be brittle (a stub answer with
        no retrieved chunks is exactly the case where the free tier
        should not be billed).
    """
    # Embeddings stay on the server key by design -- the 1536-dim vector
    # column is shared across all users, and a per-user embedding key would
    # shard the index. The retrieval half of the pipeline therefore keeps
    # its single client; the generation client is built by the answerer from
    # the resolved credential, through the factory below.
    embed_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def embed(texts: Sequence[str]) -> list[list[float]]:
        return [await _embed_query(embed_client, text) for text in texts]

    def generation_client(**client_kwargs):
        # Resolved on each call so the name patched on this module is the one used.
        return AsyncOpenAI(**client_kwargs)

    logger.info(f"Answering query for repo {repository_id}: {query!r}")
    ctx = RetrievalContext(repository_id=repository_id, db=db, embed=embed)
    result = await answer(
        CLASSIC,
        query,
        ctx=ctx,
        history=history or (),
        llm=llm,
        client_factory=generation_client,
    )
    logger.info(f"Retrieved {len(result.retrieval.candidates)} chunks from pgvector")

    return RAGResponse(answer=result.answer, sources=result.sources, generated=result.generated)
