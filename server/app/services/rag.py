import logging
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from app.core.config import settings
from app.models.ast_symbol import AstSymbol
from app.models.embedding import Embedding
from app.models.file import File
from openai import OpenAI
from openai.types.responses import ResponseInputParam
from sqlalchemy import Row
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

TOP_K = 10


@dataclass
class SourceReference:
    file_path: str
    symbol_name: str
    start_line: int | None
    end_line: int | None
    chunk_text: str


@dataclass
class RAGResponse:
    answer: str
    sources: list[SourceReference]


@dataclass
class ChatMessage:
    role: Literal["user", "assistant"]
    content: str


def _embed_query(client: OpenAI, query: str) -> list[float]:
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=query,
    )
    return response.data[0].embedding


def _vector_search(
    db: Session,
    repository_id: UUID,
    query_vector: list[float],
    top_k: int = TOP_K,
) -> list[Row[tuple[Embedding, AstSymbol, File]]]:
    results = (
        db.query(Embedding, AstSymbol, File)
        .join(AstSymbol, Embedding.symbol_id == AstSymbol.id)
        .join(File, Embedding.file_id == File.id)
        .filter(Embedding.repository_id == repository_id)
        .order_by(Embedding.embedding.cosine_distance(query_vector))
        .limit(top_k)
        .all()
    )
    return results


def _build_prompt(
    query: str, chunks: list[Row[tuple[Embedding, AstSymbol, File]]]
) -> str:
    context_blocks = []
    for i, (embedding, symbol, file) in enumerate(chunks):
        block = (
            f"[Source {i + 1}] {file.path} — {symbol.kind}: {symbol.name} "
            f"(lines {symbol.start_line}–{symbol.end_line})\n"
            f"{embedding.chunk_text}"
        )
        context_blocks.append(block)

    context = "\n\n---\n\n".join(context_blocks)

    return f"""You are an expert code assistant analyzing a software repository.
        Answer the user's question using ONLY the code context provided below.
        Be specific — reference file names, function names, and line numbers where relevant.
        If the answer cannot be found in the context, say so clearly.

        ## Code Context

        {context}

        ## Question

        {query}

        ## Answer
    """


def answer_question(
    query: str,
    repository_id: UUID,
    db: Session,
    history: list[ChatMessage] | None = None,
) -> RAGResponse:
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    logger.info(f"Embedding query for repo {repository_id}: {query!r}")
    query_vector = _embed_query(client, query)

    chunks = _vector_search(db, repository_id, query_vector)
    logger.info(f"Retrieved {len(chunks)} chunks from pgvector")

    if not chunks:
        return RAGResponse(
            answer="No relevant code was found in this repository for your question.",
            sources=[],
        )

    prompt = _build_prompt(query, chunks)

    messages: list[dict] = [{"role": "system", "content": prompt}]

    if history:
        for turn in history:
            messages.append({"role": turn.role, "content": turn.content})

    messages.append({"role": "user", "content": query})

    logger.info("Calling LLM for answer generation")
    response = client.responses.create(
        model=settings.AI_MODEL,
        reasoning={"effort": "minimal"},
        input=cast(ResponseInputParam, messages),
        max_output_tokens=1000,
    )

    answer = (response.output_text or "").strip()

    sources = [
        SourceReference(
            file_path=file.path,
            symbol_name=symbol.name,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            chunk_text=embedding.chunk_text,
        )
        for embedding, symbol, file in chunks
    ]

    return RAGResponse(answer=answer, sources=sources)
