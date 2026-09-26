"""Repository chat routes backed by the RAG pipeline.

Asks questions against an ingested repository, persists each Q&A turn,
and exposes history listing plus single-message and full-history deletion.
"""

import logging
import uuid
from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select

from app.api.validation import FreeText
from app.core.database import AsyncSession, get_async_db
from app.models.chat_message import ChatMessage as ChatMessageModel
from app.models.repository import Repository
from app.models.user import User
from app.services.entitlements import (
    FREE_CHAT_MESSAGES,
    aclaim_free_chat_message,
    llm_config_for,
)
from app.services.rag import ChatMessage, answer_question

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/repository", tags=["chat"])


class ChatMessageRequest(BaseModel):
    """One prior conversation turn sent by the client."""

    role: Literal["user", "assistant"]
    content: FreeText


class ChatRequest(BaseModel):
    """Question plus optional client-side history for follow-ups."""

    question: FreeText
    history: list[ChatMessageRequest] = []


class SourceReferenceResponse(BaseModel):
    """Citation backing part of an answer, across all source types."""

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
    """Newly created chat turn with generated answer and sources."""

    id: uuid.UUID
    answer: str
    sources: list[SourceReferenceResponse]


class ChatMessageHistoryResponse(BaseModel):
    """Persisted chat turn returned by the history endpoint."""

    id: uuid.UUID
    repository_id: uuid.UUID
    user_id: uuid.UUID
    question: str
    answer: str
    sources: list[SourceReferenceResponse] | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.post("/{repo_id}/chat", response_model=ChatResponse)
async def chat(
    repo_id: uuid.UUID,
    payload: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    """Answer a question against a ready repository and persist the turn.

    Only the last 5 history turns are forwarded to the RAG pipeline to bound
    prompt size; sources are serialized onto the stored record.

    Args:
        repo_id: ID of the repository to query.
        payload: Question plus optional conversation history.
        request: Request carrying the authenticated user ID in state.
        db: Async database session.

    Returns:
        The new chat record's ID, answer text, and source citations.

    Raises:
        HTTPException: 404 if the repo is not found, 400 if not ready.
    """
    user_id = getattr(request.state, "user_id", None)
    repo = (
        await db.execute(
            select(Repository).filter(Repository.id == repo_id, Repository.user_id == user_id)
        )
    ).scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    if repo.status != "ready":
        raise HTTPException(
            status_code=400,
            detail=f"Repository is not ready for querying (status: {repo.status})",
        )

    # Cap forwarded history so long sessions don't blow up the LLM prompt.
    history = payload.history[-5:]

    # Resolve the credential bundle: the user's stored BYOK key wins
    # over the server key, and ``None`` from ``llm_config_for`` is the
    # route layer's cue to return 402. ``llm_config`` is then forwarded
    # to the RAG pipeline as a frozen value object; the embedding call
    # still uses the server key, the generation call is what honours
    # this override. ``populate_existing=True`` is the read-through-
    # cached-row guard the free-tier charge depends on: without it, a
    # session with ``expire_on_commit=False`` would silently serve a
    # stale ``free_chat_messages_used`` value across requests in the
    # same session, so the quota pre-check would always be 0 and the
    # (N+1)-th call would never get the 402 it is owed.
    owner = (
        (
            await db.execute(
                select(User).where(User.id == user_id).execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if user_id
        else None
    )
    llm_config = llm_config_for(owner)
    if llm_config is None:
        # Neither the user nor the server holds a key. The free tier is the
        # one place this can land in production -- if the operator never
        # set ``AI_API_KEY``, the entire tier is off and the very first
        # question is refused.
        raise HTTPException(
            status_code=402,
            detail=(
                "Add your own API key to ask questions about this repository. "
                "Configure one in your account settings."
            ),
        )

    on_free_tier = owner is not None and owner.ai_api_key is None
    if on_free_tier and owner is not None and owner.free_chat_messages_used >= FREE_CHAT_MESSAGES:
        # Pre-check so a doomed request doesn't spend an LLM call. The
        # ``aclaim_*`` helper enforces the bound atomically again at charge
        # time, but the pre-check preserves the existing client UX: the
        # quota message is a 402 with a stable ``detail``.
        raise HTTPException(
            status_code=402,
            detail=(
                "You've used all of your free chat questions. "
                "Add your own API key in your account settings to keep asking."
            ),
        )

    try:
        result = await answer_question(
            query=payload.question,
            repository_id=repo_id,
            db=db,
            history=[ChatMessage(role=m.role, content=m.content) for m in history],
            llm=llm_config,
        )
    except AuthenticationError as exc:
        # The credential was rejected -- forward as a 502 with the SDK's
        # message. The user owns the key, so the operator's logs are the
        # only place they can debug; opaque 500s would just hide that.
        raise HTTPException(
            status_code=502,
            detail=f"Provider rejected the API key: {exc}",
        ) from exc
    except (APIConnectionError, APITimeoutError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach the LLM provider: {exc}",
        ) from exc
    except APIStatusError as exc:
        # Any other status error from the provider (4xx/5xx responses
        # other than auth/connect/timeout). Include the SDK's message
        # verbatim -- the operator's logs and the client error banner
        # both benefit from the real reason.
        raise HTTPException(
            status_code=502,
            detail=f"Provider returned an error: {exc}",
        ) from exc

    if on_free_tier and result.generated:
        # Charge the free tier only when an answer was actually generated.
        # The ``RAGResponse.generated`` flag is the authoritative signal
        # here -- the no-context fallback short-circuits before any LLM
        # call and must not eat an allowance unit. ``aclaim_free_chat_message``
        # commits in its own transaction, so the ``users`` row lock is
        # released long before the response serialises.
        # ``user_id`` is narrowed to ``None`` only by ``getattr`` falling
        # back to a default; the route is always reached via a verified
        # session so the value is, in practice, always present. mypy
        # cannot infer that, so the cast is the documented way to tell
        # it "trust me, the AuthMiddleware wouldn't have let us this far
        # without a user".
        await aclaim_free_chat_message(db, cast(uuid.UUID, user_id))

    serialized_sources = [
        {
            "source_type": s.source_type,
            "chunk_text": s.chunk_text,
            "file_path": s.file_path,
            "symbol_name": s.symbol_name,
            "start_line": s.start_line,
            "end_line": s.end_line,
            "commit_hash": s.commit_hash,
            "author_name": s.author_name,
            "pr_number": s.pr_number,
            "pr_title": s.pr_title,
        }
        for s in result.sources
    ]

    chat_record = ChatMessageModel(
        repository_id=repo_id,
        user_id=user_id,
        question=payload.question,
        answer=result.answer,
        sources=serialized_sources,
    )
    db.add(chat_record)
    await db.commit()
    await db.refresh(chat_record)

    return ChatResponse(
        id=chat_record.id,
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


@router.get("/{repo_id}/chat/history", response_model=list[ChatMessageHistoryResponse])
async def get_chat_history(
    repo_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    """List a user's chat history for a repository in chronological order.

    Args:
        repo_id: ID of the repository whose history to list.
        request: Request carrying the authenticated user ID in state.
        db: Async database session.

    Returns:
        Chronologically ordered chat turns.

    Raises:
        HTTPException: 401 if unauthenticated, 404 if the repo is not found.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    repo = (
        await db.execute(
            select(Repository).filter(Repository.id == repo_id, Repository.user_id == user_id)
        )
    ).scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    messages = (
        (
            await db.execute(
                select(ChatMessageModel)
                .filter(
                    ChatMessageModel.repository_id == repo_id,
                    ChatMessageModel.user_id == user_id,
                )
                .order_by(ChatMessageModel.created_at.asc())
            )
        )
        .scalars()
        .all()
    )

    return messages


@router.delete("/{repo_id}/chat/{message_id}", status_code=204)
async def delete_chat_message(
    repo_id: uuid.UUID,
    message_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    """Delete one chat turn scoped to the user and repository.

    Args:
        repo_id: ID of the repository the message belongs to.
        message_id: ID of the chat message to delete.
        request: Request carrying the authenticated user ID in state.
        db: Async database session.

    Returns:
        None (204 No Content).

    Raises:
        HTTPException: 401 if unauthenticated, 404 if not found.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    message = (
        await db.execute(
            select(ChatMessageModel).filter(
                ChatMessageModel.id == message_id,
                ChatMessageModel.repository_id == repo_id,
                ChatMessageModel.user_id == user_id,
            )
        )
    ).scalar_one_or_none()

    if not message:
        raise HTTPException(status_code=404, detail="Chat message not found")

    await db.delete(message)
    await db.commit()
    return None


@router.delete("/{repo_id}/chat", status_code=204)
async def clear_chat_history(
    repo_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    """Delete all of the user's chat history for a repository.

    Args:
        repo_id: ID of the repository whose history to clear.
        request: Request carrying the authenticated user ID in state.
        db: Async database session.

    Returns:
        None (204 No Content).

    Raises:
        HTTPException: 401 if unauthenticated.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    await db.execute(
        delete(ChatMessageModel).where(
            ChatMessageModel.repository_id == repo_id,
            ChatMessageModel.user_id == user_id,
        )
    )
    await db.commit()
    return None
