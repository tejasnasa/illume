"""Chat conversations: titles, ownership lookups and the writes a turn makes.

A conversation is a named thread of chat turns for one user and one repository.
Every query here is scoped by ``user_id`` as well as the repository, so a
conversation that is not the caller's is indistinguishable from one that does
not exist.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models.conversation import Conversation

TITLE_LIMIT = 60
"""Longest generated title, ellipsis included."""

DEFAULT_TITLE = "New chat"
"""Title of a conversation created without one and not yet titled by a question."""

_WHITESPACE = re.compile(r"\s+")


def title_from_question(question: str) -> str:
    """The title a conversation gets from its first question.

    Whitespace is collapsed to single spaces, and a question longer than
    :data:`TITLE_LIMIT` characters is cut so that the result, ellipsis included,
    is exactly that long.

    Args:
        question: The question as typed.

    Returns:
        The title; :data:`DEFAULT_TITLE` when the question has no text.
    """
    collapsed = _WHITESPACE.sub(" ", question).strip()
    if not collapsed:
        return DEFAULT_TITLE
    if len(collapsed) <= TITLE_LIMIT:
        return collapsed
    return collapsed[: TITLE_LIMIT - 1].rstrip() + "…"


async def owned_conversation(
    db: AsyncSession, user_id: Any, repo_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation | None:
    """The conversation, when it is the caller's and belongs to the repository.

    Args:
        db: Async session.
        user_id: The caller.
        repo_id: The repository the conversation must belong to.
        conversation_id: The conversation.

    Returns:
        The row, or ``None`` when there is no such conversation for this caller.
    """
    return (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.repository_id == repo_id,
            )
        )
    ).scalar_one_or_none()


async def touch_conversation(db: AsyncSession, conversation_id: uuid.UUID) -> None:
    """Moves a conversation's ``updated_at`` to now, without committing."""
    await db.execute(
        update(Conversation).where(Conversation.id == conversation_id).values(updated_at=func.now())
    )


async def ensure_conversation(
    db: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    repository_id: uuid.UUID,
    question: str,
) -> None:
    """Creates a conversation titled from its first question, if it is not there yet.

    Safe to call for an id that already exists: the row is left as it is.
    Nothing is committed.

    Args:
        db: Async session.
        conversation_id: The id the conversation is to have.
        user_id: The owner.
        repository_id: The repository it is about.
        question: The first question, which becomes the title.
    """
    await db.execute(
        insert(Conversation)
        .values(
            id=conversation_id,
            user_id=user_id,
            repository_id=repository_id,
            title=title_from_question(question),
        )
        .on_conflict_do_nothing(index_elements=[Conversation.id])
    )
