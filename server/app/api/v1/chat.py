import logging
import uuid
from typing import Literal

from app.core.database import AsyncSession, get_async_db
from app.models.repository import Repository
from app.services.rag import ChatMessage, answer_question
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/repository", tags=["chat"])


class ChatMessageRequest(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    question: str
    history: list[ChatMessageRequest] = []


class SourceReferenceResponse(BaseModel):
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


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceReferenceResponse]


@router.post("/{repo_id}/chat", response_model=ChatResponse)
async def chat(
    repo_id: uuid.UUID,
    payload: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    user_id = getattr(request.state, "user_id", None)
    repo = (
        await db.execute(
            select(Repository).filter(
                Repository.id == repo_id, Repository.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    if repo.status != "ready":
        raise HTTPException(
            status_code=400,
            detail=f"Repository is not ready for querying (status: {repo.status})",
        )

    history = payload.history[-5:]

    result = await answer_question(
        query=payload.question,
        repository_id=repo_id,
        db=db,
        history=[ChatMessage(role=m.role, content=m.content) for m in history],
    )

    return ChatResponse(
        answer=result.answer,
        sources=[
            SourceReferenceResponse(
                source_type=s.source_type,
                chunk_text=s.chunk_text,
                file_path=s.file_path,
                symbol_name=s.symbol_name,
                start_line=s.start_line,
                end_line=s.end_line,
                commit_hash=s.commit_hash,
                author_name=s.author_name,
                pr_number=s.pr_number,
                pr_title=s.pr_title,
            )
            for s in result.sources
        ],
    )
