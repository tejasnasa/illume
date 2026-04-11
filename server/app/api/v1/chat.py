import logging
import uuid
from typing import Literal

from app.core.database import get_sync_db
from app.models.repository import Repository
from app.services.rag import ChatMessage, answer_question
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/repository", tags=["chat"])


class ChatMessageRequest(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    question: str
    history: list[ChatMessageRequest] = []


class SourceReferenceResponse(BaseModel):
    file_path: str
    symbol_name: str
    start_line: int | None
    end_line: int | None
    chunk_text: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceReferenceResponse]


@router.post("/{repo_id}/chat", response_model=ChatResponse)
def chat(
    repo_id: uuid.UUID,
    payload: ChatRequest,
    request: Request,
    db: Session = Depends(get_sync_db),
):
    user_id = getattr(request.state, "user_id", None)
    repo = (
        db.query(Repository)
        .filter(Repository.id == repo_id, Repository.user_id == user_id)
        .first()
    )
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    if repo.status != "ready":
        raise HTTPException(
            status_code=400,
            detail=f"Repository is not ready for querying (status: {repo.status})",
        )

    history = payload.history[-5:]

    result = answer_question(
        query=payload.question,
        repository_id=repo_id,
        db=db,
        history=[ChatMessage(role=m.role, content=m.content) for m in history],
    )

    return ChatResponse(
        answer=result.answer,
        sources=[
            SourceReferenceResponse(
                file_path=s.file_path,
                symbol_name=s.symbol_name,
                start_line=s.start_line,
                end_line=s.end_line,
                chunk_text=s.chunk_text,
            )
            for s in result.sources
        ],
    )
