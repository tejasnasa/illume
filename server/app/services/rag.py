import logging
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from app.core.config import settings
from app.models import AstSymbol, Commit, Embedding, File, PullRequest
from openai import AsyncOpenAI
from openai.types.responses import ResponseInputParam
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

TOP_K = 10


@dataclass
class SourceReference:
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
    answer: str
    sources: list[SourceReference]


@dataclass
class ChatMessage:
    role: Literal["user", "assistant"]
    content: str


async def _embed_query(client: AsyncOpenAI, query: str) -> list[float]:
    response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=query,
    )
    return response.data[0].embedding


async def _vector_search(db: AsyncSession, repository_id, query_vector, top_k=TOP_K):
    async def query_type(source_type, limit):
        result = await db.execute(
            select(Embedding)
            .filter(
                Embedding.repository_id == repository_id,
                Embedding.source_type == source_type,
            )
            .order_by(Embedding.embedding.cosine_distance(query_vector))
            .limit(limit)
        )
        return result.scalars().all()

    symbols = await query_type("symbol", 6)
    commits = await query_type("commit", 2)
    prs = await query_type("pull_request", 1)
    docs = await query_type("document", 1)
    return list(symbols) + list(commits) + list(prs) + list(docs)


async def _resolve_source(db: AsyncSession, embedding: Embedding) -> SourceReference:
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

    else:
        return SourceReference(
            source_type="document",
            chunk_text=embedding.chunk_text,
        )


def _build_prompt(query: str, sources: list[SourceReference]) -> str:
    context_blocks = []

    for i, src in enumerate(sources):
        if src.source_type == "symbol":
            header = f"[Source {i + 1}] [Code] {src.file_path} — {src.symbol_name} (lines {src.start_line}–{src.end_line})"
        elif src.source_type == "commit":
            header = f"[Source {i + 1}] [Commit] {src.commit_hash} by {src.author_name}"
        elif src.source_type == "pull_request":
            header = f"[Source {i + 1}] [PR #{src.pr_number}] {src.pr_title}"
        else:
            header = f"[Source {i + 1}] [README]"
        context_blocks.append(f"{header}\n{src.chunk_text}")

    context = "\n\n---\n\n".join(context_blocks)
    return f"""You are an expert code assistant analyzing a software repository.
            Answer the user's question using ONLY the context provided below.
            Context includes code, commit messages, pull requests, and documentation.
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
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    logger.info(f"Embedding query for repo {repository_id}: {query!r}")
    query_vector = await _embed_query(client, query)

    chunks = await _vector_search(db, repository_id, query_vector)
    logger.info(f"Retrieved {len(chunks)} chunks from pgvector")

    if not chunks:
        return RAGResponse(
            answer="No relevant code was found in this repository for your question.",
            sources=[],
        )

    sources = [await _resolve_source(db, e) for e in chunks]
    prompt = _build_prompt(query, sources)

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
