"""Chat conversations: list, create, rename, delete and read one thread.

A repository's chat is a list of conversations, each owning its turns. Every
query is scoped by the caller's ``user_id``, so a conversation or repository that
is not the caller's is a 404, the same as one that does not exist.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, StringConstraints
from sqlalchemy import delete, func, select

from app.api.v1.chat import ChatMessageHistoryResponse
from app.api.validation import NoControlCharacters
from app.core.database import AsyncSession, get_async_db
from app.models.chat_message import ChatMessage as ChatMessageModel
from app.models.conversation import Conversation
from app.models.repository import Repository
from app.services.conversations import DEFAULT_TITLE, owned_conversation

router = APIRouter(prefix="/api/v1/repository", tags=["chat"])

MAX_TITLE_CHARS = 120
"""The longest title a conversation may be renamed to."""

Title = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TITLE_CHARS),
    NoControlCharacters,
]
"""A conversation title: 1 to 120 characters once trimmed, no control characters."""


class ConversationResponse(BaseModel):
    """One conversation in the list.

    Attributes:
        id: The conversation.
        title: Its name.
        created_at: When it was started.
        updated_at: When its last turn was added.
        message_count: How many turns it holds.
    """

    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class CreateConversationRequest(BaseModel):
    """Body for creating a conversation; the title is optional."""

    title: Title | None = None


class RenameConversationRequest(BaseModel):
    """Body for renaming a conversation."""

    title: Title


def _user_id(request: Request) -> Any:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


async def _owned_repository(db: AsyncSession, repo_id: uuid.UUID, user_id: Any) -> None:
    found = (
        await db.execute(
            select(Repository.id).where(Repository.id == repo_id, Repository.user_id == user_id)
        )
    ).scalar_one_or_none()
    if found is None:
        raise HTTPException(status_code=404, detail="Repository not found")


async def _owned(
    db: AsyncSession, repo_id: uuid.UUID, user_id: Any, conversation_id: uuid.UUID
) -> Conversation:
    await _owned_repository(db, repo_id, user_id)
    conversation = await owned_conversation(db, user_id, repo_id, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _response(conversation: Conversation, count: int) -> ConversationResponse:
    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=count,
    )


@router.get("/{repo_id}/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    repo_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    """List the caller's conversations on a repository, most recently active first.

    Args:
        repo_id: ID of the repository.
        request: Request carrying the authenticated user ID in state.
        db: Async database session.

    Returns:
        The conversations with their turn counts.

    Raises:
        HTTPException: 401 if unauthenticated, 404 if the repository is not the caller's.
    """
    user_id = _user_id(request)
    await _owned_repository(db, repo_id, user_id)
    rows = (
        await db.execute(
            select(Conversation, func.count(ChatMessageModel.id))
            .outerjoin(ChatMessageModel, ChatMessageModel.conversation_id == Conversation.id)
            .where(Conversation.repository_id == repo_id, Conversation.user_id == user_id)
            .group_by(Conversation.id)
            .order_by(Conversation.updated_at.desc(), Conversation.id)
        )
    ).all()
    return [_response(conversation, count) for conversation, count in rows]


@router.post("/{repo_id}/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    repo_id: uuid.UUID,
    request: Request,
    payload: CreateConversationRequest | None = None,
    db: AsyncSession = Depends(get_async_db),
):
    """Create an empty conversation.

    Args:
        repo_id: ID of the repository.
        request: Request carrying the authenticated user ID in state.
        payload: Optional title; a placeholder is used without one.
        db: Async database session.

    Returns:
        The new conversation.

    Raises:
        HTTPException: 401 if unauthenticated, 404 if the repository is not the caller's.
    """
    user_id = _user_id(request)
    await _owned_repository(db, repo_id, user_id)
    conversation = Conversation(
        user_id=user_id,
        repository_id=repo_id,
        title=(payload.title if payload and payload.title else DEFAULT_TITLE),
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return _response(conversation, 0)


@router.patch("/{repo_id}/conversations/{conversation_id}", response_model=ConversationResponse)
async def rename_conversation(
    repo_id: uuid.UUID,
    conversation_id: uuid.UUID,
    payload: RenameConversationRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    """Rename a conversation. Its position in the list does not change.

    Args:
        repo_id: ID of the repository.
        conversation_id: ID of the conversation.
        payload: The new title, 1 to 120 characters.
        request: Request carrying the authenticated user ID in state.
        db: Async database session.

    Returns:
        The renamed conversation.

    Raises:
        HTTPException: 401 if unauthenticated, 404 if it is not the caller's.
    """
    user_id = _user_id(request)
    conversation = await _owned(db, repo_id, user_id, conversation_id)
    conversation.title = payload.title
    await db.commit()
    await db.refresh(conversation)
    count = (
        await db.execute(
            select(func.count(ChatMessageModel.id)).where(
                ChatMessageModel.conversation_id == conversation.id
            )
        )
    ).scalar_one()
    return _response(conversation, count)


@router.delete("/{repo_id}/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    repo_id: uuid.UUID,
    conversation_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    """Delete a conversation and every turn in it.

    Args:
        repo_id: ID of the repository.
        conversation_id: ID of the conversation.
        request: Request carrying the authenticated user ID in state.
        db: Async database session.

    Returns:
        None (204 No Content).

    Raises:
        HTTPException: 401 if unauthenticated, 404 if it is not the caller's.
    """
    user_id = _user_id(request)
    conversation = await _owned(db, repo_id, user_id, conversation_id)
    await db.execute(delete(Conversation).where(Conversation.id == conversation.id))
    await db.commit()
    return None


@router.get(
    "/{repo_id}/conversations/{conversation_id}/messages",
    response_model=list[ChatMessageHistoryResponse],
)
async def get_conversation_messages(
    repo_id: uuid.UUID,
    conversation_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    """List one conversation's turns in chronological order.

    Args:
        repo_id: ID of the repository.
        conversation_id: ID of the conversation.
        request: Request carrying the authenticated user ID in state.
        db: Async database session.

    Returns:
        The turns, in the shape the history endpoint returns.

    Raises:
        HTTPException: 401 if unauthenticated, 404 if it is not the caller's.
    """
    user_id = _user_id(request)
    conversation = await _owned(db, repo_id, user_id, conversation_id)
    return (
        (
            await db.execute(
                select(ChatMessageModel)
                .where(
                    ChatMessageModel.conversation_id == conversation.id,
                    ChatMessageModel.user_id == user_id,
                )
                .order_by(ChatMessageModel.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
