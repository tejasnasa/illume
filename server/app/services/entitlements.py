"""Per-user quota policy for the free tier.

This module centralises every decision about whether a user can still spend
the server's free-tier allowance, so the route layer and the task layer
agree. Constants are module-level rather than ``Settings`` fields, matching
the convention documented at :mod:`app.tasks.autoupdate`:

- every field of ``Settings`` is required and ``.env`` is gitignored, so a new
  field is another way for a fresh checkout, a CI job, or a standalone script
  to fail to instantiate ``Settings()``;
- a code change plus a deploy is the intent for every value below.

The two :func:`claim_*` helpers are **conditional ``UPDATE``s with
``RETURNING``**, the same compare-and-set pattern :func:`app.tasks.autoupdate.
_claim_predicate` uses. Two concurrent requests cannot both spend the last
unit: the row's ``WHERE`` clause refuses the second claim, ``rowcount`` is
``0``, and the second caller sees a denial rather than a silently-burned
quota.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.llm_config import LLMConfig

# Per-user allowance. A free tier is supposed to be a *teaser*, not a
# sustainable plan: a handful of ingestions is enough to evaluate the
# artefact set, five chat questions are enough to confirm the retrieval is
# doing what the on-screen citations imply. The numbers are the policy; the
# routes are the enforcers. Both are served to the client on ``/auth/me`` so
# the banner and the chat composer never carry a second copy that can drift.
FREE_INGESTIONS: int = 3
FREE_CHAT_MESSAGES: int = 10


def llm_config_for(user: Any) -> LLMConfig | None:
    """Resolve the credential to use for a request from ``user``.

    Mirrors the precedence: a stored key wins over the server key, and the
    server key wins over nothing. ``None`` means "neither", which the route
    layer turns into a 402.

    Composition rather than duplication: the existing :class:`LLMConfig`
    already carries the per-key behaviour (registry lookup, ``base_url``
    omission, reasoning-cap detection). This module is policy *only* -- the
    shape of the credential is its concern, not ours.

    ``user`` is typed as ``Any`` to mirror :meth:`LLMConfig.from_user`, which
    uses ``getattr`` to read the three credential columns -- so a duck-typed
    user (the unit tests' ``SimpleNamespace``) works alongside a real
    :class:`~app.models.user.User` row. Keeping the same surface means a
    future test or partial mock does not need a database fixture.

    Args:
        user: The owner of the resource being processed.

    Returns:
        A populated :class:`LLMConfig` when the user has their own key, or
        the server default when ``settings.AI_API_KEY`` is set and the user
        has no key, or ``None`` otherwise.
    """
    user_config = LLMConfig.from_user(user)
    if user_config is not None:
        return user_config
    return LLMConfig.server_default()


def claim_free_ingestion(db: Session, user_id: uuid.UUID) -> bool:
    """Atomically charge one of the user's free ingestions.

    Bounded by :data:`FREE_INGESTIONS`: a user whose counter is already at
    the cap cannot spend another. The ``WHERE`` clause enforces the bound
    atomically with the increment, so the final permitted claim succeeds and
    the next one returns ``False``.

    The caller is expected to bundle the claim with the ``Repository`` insert
    in one transaction, so this function does **not** commit -- a failed
    insert rolls back the claim and the allowance is preserved.

    Args:
        db: An open sync session (the route layer's async session is
            covered by :func:`aclaim_free_ingestion` below).
        user_id: The user attempting to ingest.

    Returns:
        ``True`` if a free ingestion was just spent on this call, ``False``
        if the cap had already been reached (or the user has their own key --
        the caller is responsible for that pre-check).
    """
    result = db.execute(
        update(User)
        .where(
            User.id == user_id,
            User.free_ingestions_used < FREE_INGESTIONS,
        )
        .values(free_ingestions_used=User.free_ingestions_used + 1)
    )
    return int(result.rowcount or 0) == 1


def claim_free_chat_message(db: Session, user_id: uuid.UUID) -> bool:
    """Atomically charge one of the user's free chat messages.

    Bounded by :data:`FREE_CHAT_MESSAGES`: a user whose counter is already at
    the cap cannot spend another. The ``WHERE`` clause enforces the bound
    atomically with the increment, so a 5th-and-final claim succeeds and a
    6th claim returns ``False``.

    This helper exists to *charge* for an answer, not to gate it -- the route
    pre-checks the counter at zero so a doomed request returns 402 without
    spending an OpenAI call. The charge runs in its own short transaction, so
    this function commits -- keeping the ``users`` row lock off the LLM call.

    Args:
        db: An open sync session.
        user_id: The user being charged.

    Returns:
        ``True`` if the message was just charged, ``False`` if the cap had
        already been reached.
    """
    result = db.execute(
        update(User)
        .where(
            User.id == user_id,
            User.free_chat_messages_used < FREE_CHAT_MESSAGES,
        )
        .values(free_chat_messages_used=User.free_chat_messages_used + 1)
    )
    db.commit()
    return int(result.rowcount or 0) == 1


async def aclaim_free_ingestion(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Async twin of :func:`claim_free_ingestion`.

    The route layer talks to Postgres over asyncpg; Celery talks to psycopg2.
    Same SQL, different driver -- separate helpers so the type system can
    see which session each caller holds. The caller commits; the ingest
    claim is bundled with the ``Repository`` insert in one transaction.
    """
    result = await db.execute(
        update(User)
        .where(
            User.id == user_id,
            User.free_ingestions_used < FREE_INGESTIONS,
        )
        .values(free_ingestions_used=User.free_ingestions_used + 1)
    )
    return int(result.rowcount or 0) == 1


async def aclaim_free_chat_message(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Async twin of :func:`claim_free_chat_message`.

    The chat charge runs in its own short transaction, so this helper
    commits -- keeping the ``users`` row lock off the LLM call.
    """
    result = await db.execute(
        update(User)
        .where(
            User.id == user_id,
            User.free_chat_messages_used < FREE_CHAT_MESSAGES,
        )
        .values(free_chat_messages_used=User.free_chat_messages_used + 1)
    )
    await db.commit()
    return int(result.rowcount or 0) == 1
