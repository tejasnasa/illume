"""Retrieval-augmented question answering over a repository.

Embeds the user's query, searches stored embeddings in pgvector via
cosine distance, applies per-source-type diversity caps to keep results
varied, resolves the hits back to their underlying records in one query
per source type (symbol, commit, PR, file, or document), and prompts an
LLM with the assembled context to produce a grounded answer plus source
references.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal, Sequence, cast
from uuid import UUID

from openai import AsyncOpenAI
from openai.types.responses import ResponseInputParam
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Embedding
from app.services.llm_config import LLMConfig
from app.services.retrieval.resolve import SourceReference, resolve_sources

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

# pgvector 0.8 added iterative index scans. Below it, a filtered HNSW query
# returns the global ``ef_search`` nearest rows and applies ``repository_id``
# afterwards, so a small repository on a large instance can come back with too
# few hits. The extension version is fixed for the life of a process, so the
# answer is cached rather than re-read on every search.
_ITERATIVE_SCAN_MIN_VERSION = (0, 8)
_pgvector_supports_iterative_scan: bool | None = None


def _version_tuple(raw: str | None) -> tuple[int, ...]:
    """Parses a dotted version string into its numeric components."""
    if not raw:
        return ()
    parts: list[int] = []
    for chunk in raw.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


async def _prepare_filtered_vector_search(db: AsyncSession) -> None:
    """Tunes pgvector for a repository-filtered HNSW search.

    ``hnsw.ef_search`` is raised from its 40-row default to 200 so the walk has
    a wider candidate pool, and ``hnsw.iterative_scan`` is set to
    ``strict_order`` so the scan keeps going until the filter has produced
    enough rows instead of stopping at the global top of the index.
    ``strict_order`` rather than ``relaxed_order`` because the diversity caps
    take hits in the order they arrive, and ``relaxed_order`` may return them
    slightly out of distance order.

    Both settings are transactional (``SET LOCAL``), which is why they are
    issued on the search's own session rather than on a connection pool. On a
    pgvector older than 0.8 ``iterative_scan`` does not exist and is skipped;
    the index is still used there, so a small repository on a large instance
    can come back with fewer hits than asked for.
    """
    global _pgvector_supports_iterative_scan
    if _pgvector_supports_iterative_scan is None:
        raw_version = (
            await db.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
        ).scalar_one_or_none()
        _pgvector_supports_iterative_scan = (
            _version_tuple(raw_version)[:2] >= _ITERATIVE_SCAN_MIN_VERSION
        )

    await db.execute(text("SET LOCAL hnsw.ef_search = 200"))
    if _pgvector_supports_iterative_scan:
        await db.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))


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
    await _prepare_filtered_vector_search(db)
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


def _build_prompt(query: str, sources: list[SourceReference]) -> str:
    """Builds the system prompt with labeled context blocks and the grounding rules."""
    context_blocks = []

    for i, src in enumerate(sources):
        if src.source_type == "symbol":
            header = f"[Source {i + 1}] [Code] {src.file_path} — {src.symbol_name} (lines {src.start_line}–{src.end_line})"
        elif src.source_type == "commit":
            header = f"[Source {i + 1}] [Commit] {src.commit_hash} by {src.author_name}"
        elif src.source_type == "pull_request":
            header = f"[Source {i + 1}] [PR #{src.pr_number}] {src.pr_title}"
        elif src.source_type == "file":
            header = f"[Source {i + 1}] [Code] {src.file_path}"
        else:
            header = f"[Source {i + 1}] [README]"
        context_blocks.append(f"{header}\n{src.chunk_text}")

    context = "\n\n---\n\n".join(context_blocks)
    return f"""You are an expert code assistant analyzing a software repository.
            Answer the user's question using ONLY the context provided below.
            Context includes code, commit messages, pull requests, files and documentation.
            Be specific — reference file names, function names, line numbers, commit hashes, or PR numbers where relevant.
            If the answer cannot be found in the context, say so clearly.

            ## Context
            {context}

            ## Question
            {query}

            ## Answer
        """


async def answer_question(
    query: str,
    repository_id: UUID,
    db: AsyncSession,
    history: list[ChatMessage] | None = None,
    *,
    llm: LLMConfig | None = None,
) -> RAGResponse:
    """Answer a natural-language question about a repository.

    Flow: embed the query, run a pgvector cosine-distance search scoped to
    the repository, cap results per source type for diversity, resolve each
    hit to a citable source, then prompt the LLM (`settings.AI_MODEL`) with
    the retrieved context, prior chat history, and the question. The model
    is instructed to answer only from the provided context.

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
    # its single client; the generation half gets a second client built
    # from the resolved credential.
    embed_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    logger.info(f"Embedding query for repo {repository_id}: {query!r}")
    query_vector = await _embed_query(embed_client, query)

    chunks = await _vector_search(db, repository_id, query_vector, 10)
    logger.info(f"Retrieved {len(chunks)} chunks from pgvector")

    if not chunks:
        return RAGResponse(
            answer="No relevant code was found in this repository for your question.",
            sources=[],
            generated=False,
        )

    sources = await resolve_sources(db, chunks)
    prompt = _build_prompt(query, sources)

    # Retrieved context goes in the system role; history replays as turns so
    # the model can resolve follow-up questions against prior context.
    messages: list[dict] = [{"role": "system", "content": prompt}]

    if history:
        for turn in history:
            messages.append({"role": turn.role, "content": turn.content})

    messages.append({"role": "user", "content": query})

    # Generation client: the user's BYOK key when present, otherwise the
    # server key. ``client_kwargs`` omits ``base_url`` when None so the
    # SDK default applies (which is also how the E2E stub is reached).
    generation_client_kwargs = (
        llm.client_kwargs() if llm is not None else {"api_key": settings.OPENAI_API_KEY}
    )
    generation_client = AsyncOpenAI(**generation_client_kwargs)
    generation_model = llm.model if llm is not None else settings.AI_MODEL
    generation_response_kwargs = (
        llm.response_kwargs("minimal") if llm is not None else {"reasoning": {"effort": "minimal"}}
    )

    logger.info("Calling LLM for answer generation")
    response = await generation_client.responses.create(
        model=generation_model,
        **generation_response_kwargs,
        input=cast(ResponseInputParam, messages),
        max_output_tokens=3000,
    )

    answer = (response.output_text or "").strip()

    return RAGResponse(answer=answer, sources=sources, generated=True)
