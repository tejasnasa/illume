"""Retrieval-augmented question answering over a repository.

Embeds the user's query, searches stored embeddings in pgvector via
cosine distance, applies per-source-type diversity caps to keep results
varied, resolves each hit back to its underlying record (symbol, commit,
PR, file, or document), and prompts an LLM with the assembled context to
produce a grounded answer plus source references.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal, Sequence, cast
from uuid import UUID

from openai import AsyncOpenAI
from openai.types.responses import ResponseInputParam
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import AstSymbol, Commit, Embedding, File, PullRequest

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
class SourceReference:
    """A resolved citation backing part of a RAG answer.

    Attributes:
        source_type: One of "symbol", "commit", "pull_request", "file",
            or "document".
        chunk_text: The embedded text that matched the query.
        file_path: Path for symbol/file sources.
        symbol_name: Name for symbol sources.
        start_line: Start line for symbol sources.
        end_line: End line for symbol sources.
        commit_hash: Hash for commit sources.
        author_name: Author for commit sources.
        pr_number: Number for pull request sources.
        pr_title: Title for pull request sources.
    """

    source_type: str
    chunk_text: str
    file_path: str | None = None
    symbol_name: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    commit_hash: str | None = None
    author_name: str | None = None
    pr_number: int | None = None
    pr_title: str | None = None


@dataclass
class RAGResponse:
    """Final RAG result: generated answer text and its source citations."""

    answer: str
    sources: list[SourceReference]


@dataclass
class ChatMessage:
    """One prior conversation turn replayed into the LLM prompt."""

    role: Literal["user", "assistant"]
    content: str


def _apply_diversity_caps(
    embeddings: Sequence[Embedding], total: int = TOP_K
) -> list[Embedding]:
    """Selects up to `total` hits while respecting per-type caps, then fills any remaining slots by relevance order."""
    type_counts = defaultdict(int)
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
    """Loads the record behind an embedding hit and builds its citation."""
    # Branch per type because source_id points at a different table each time;
    # missing rows degrade to None fields rather than dropping the citation.
    if embedding.source_type == "symbol":
        symbol = (
            await db.execute(
                select(AstSymbol).filter(AstSymbol.id == embedding.source_id)
            )
        ).scalar_one_or_none()
        file = (
            await db.execute(select(File).filter(File.id == embedding.file_id))
        ).scalar_one_or_none()
        return SourceReference(
            source_type="symbol",
            chunk_text=embedding.chunk_text,
            file_path=file.path if file else None,
            symbol_name=symbol.name if symbol else None,
            start_line=symbol.start_line if symbol else None,
            end_line=symbol.end_line if symbol else None,
        )

    elif embedding.source_type == "commit":
        commit = (
            await db.execute(select(Commit).filter(Commit.id == embedding.source_id))
        ).scalar_one_or_none()
        return SourceReference(
            source_type="commit",
            chunk_text=embedding.chunk_text,
            commit_hash=commit.hash if commit else None,
            author_name=commit.author_name if commit else None,
        )

    elif embedding.source_type == "pull_request":
        pr = (
            await db.execute(
                select(PullRequest).filter(PullRequest.id == embedding.source_id)
            )
        ).scalar_one_or_none()
        return SourceReference(
            source_type="pull_request",
            chunk_text=embedding.chunk_text,
            pr_number=pr.number if pr else None,
            pr_title=pr.title if pr else None,
        )

    elif embedding.source_type == "file":
        file = (
            await db.execute(select(File).filter(File.id == embedding.file_id))
        ).scalar_one_or_none()
        return SourceReference(
            source_type="file",
            chunk_text=embedding.chunk_text,
            file_path=file.path if file else None,
        )

    else:
        # Documents (README sections) are keyed by repository_id, not a row ID.
        return SourceReference(
            source_type="document",
            chunk_text=embedding.chunk_text,
        )


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

    Returns:
        A RAGResponse with the generated answer and resolved sources. If no
        sufficiently similar chunks exist, returns a fallback message with
        empty sources without calling the LLM.
    """
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    logger.info(f"Embedding query for repo {repository_id}: {query!r}")
    query_vector = await _embed_query(client, query)

    chunks = await _vector_search(db, repository_id, query_vector, 10)
    logger.info(f"Retrieved {len(chunks)} chunks from pgvector")

    if not chunks:
        return RAGResponse(
            answer="No relevant code was found in this repository for your question.",
            sources=[],
        )

    sources = [await _resolve_source(db, e) for e in chunks]
    prompt = _build_prompt(query, sources)

    # Retrieved context goes in the system role; history replays as turns so
    # the model can resolve follow-up questions against prior context.
    messages: list[dict] = [{"role": "system", "content": prompt}]

    if history:
        for turn in history:
            messages.append({"role": turn.role, "content": turn.content})

    messages.append({"role": "user", "content": query})

    logger.info("Calling LLM for answer generation")
    response = await client.responses.create(
        model=settings.AI_MODEL,
        reasoning={"effort": "minimal"},
        input=cast(ResponseInputParam, messages),
        max_output_tokens=1000,
    )

    answer = (response.output_text or "").strip()

    return RAGResponse(answer=answer, sources=sources)
