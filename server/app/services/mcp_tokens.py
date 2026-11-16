"""Personal access tokens for MCP clients.

A token is ``ilm_`` followed by 256 bits of randomness. Only its SHA-256 digest
is stored: with that much entropy a fast hash is enough, and a slow one would
be paid on every MCP request. The plaintext leaves this module exactly once,
from :func:`create_token`, and is never logged.

:func:`resolve_token` is the single place a presented token becomes a user.

Every function here is async and **commits** the changes it makes, like the
push-token service: each call is one self-contained operation and a caller
cannot forget to persist it. Every query that involves a user filters on
``user_id``.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mcp_token import McpToken
from app.models.user import User

TOKEN_PREFIX = "ilm_"
"""Marker every token starts with, so it is recognisable in a config file or a leak scan."""

MAX_TOKENS_PER_USER = 10
"""Most active (not revoked, not expired) tokens one user may hold."""

LAST_USED_THROTTLE = timedelta(minutes=1)
"""A use within this long of the last recorded one does not write ``last_used_at`` again."""

DISPLAY_PREFIX_LENGTH = 8
"""Characters after ``ilm_`` kept in the clear so the owner can tell tokens apart."""

_SECRET_LENGTH = len(secrets.token_urlsafe(32))
_TOKEN_PATTERN = re.compile(rf"^{re.escape(TOKEN_PREFIX)}[A-Za-z0-9_-]{{{_SECRET_LENGTH}}}$")


class TokenLimitError(Exception):
    """The user already holds :data:`MAX_TOKENS_PER_USER` active tokens."""


class TokenNotFoundError(Exception):
    """No token with that id belongs to the user."""


def hash_token(plaintext: str) -> str:
    """Return the SHA-256 hex digest under which a token is stored.

    Args:
        plaintext: The full token, including the ``ilm_`` marker.

    Returns:
        A 64-character lowercase hex string.
    """
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _is_active(token: McpToken, now: datetime) -> bool:
    """Whether a token is neither revoked nor expired at ``now``."""
    if token.revoked_at is not None:
        return False
    return token.expires_at is None or token.expires_at > now


async def create_token(
    db: AsyncSession,
    user_id: uuid.UUID,
    name: str,
    expires_in_days: int | None,
) -> tuple[McpToken, str]:
    """Mint a token for a user and commit it.

    Args:
        db: Async database session.
        user_id: The owner.
        name: A label the owner chose, at most 60 characters.
        expires_in_days: Lifetime in days, or ``None`` for a token that never expires.

    Returns:
        The stored row and the plaintext token. The plaintext is not recoverable
        afterwards, so the caller must hand it to the user now.

    Raises:
        TokenLimitError: If the user already holds :data:`MAX_TOKENS_PER_USER`
            active tokens.
    """
    now = datetime.now(UTC)
    # Lock the owner's row so two concurrent creates cannot both pass the count;
    # the lock is released by the commit below.
    await db.execute(select(User.id).where(User.id == user_id).with_for_update())
    active = await db.scalar(
        select(func.count())
        .select_from(McpToken)
        .where(
            McpToken.user_id == user_id,
            McpToken.revoked_at.is_(None),
            (McpToken.expires_at.is_(None)) | (McpToken.expires_at > now),
        )
    )
    if (active or 0) >= MAX_TOKENS_PER_USER:
        raise TokenLimitError(f"at most {MAX_TOKENS_PER_USER} active tokens per user")

    plaintext = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = McpToken(
        user_id=user_id,
        name=name,
        token_prefix=plaintext[len(TOKEN_PREFIX) :][:DISPLAY_PREFIX_LENGTH],
        token_hash=hash_token(plaintext),
        expires_at=now + timedelta(days=expires_in_days) if expires_in_days is not None else None,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)
    return token, plaintext


async def resolve_token(db: AsyncSession, plaintext: str) -> User | None:
    """Turn a presented token into its owner.

    A token that is malformed, unknown, revoked or expired resolves to ``None``;
    the caller cannot tell which, and neither can the client. On success
    ``last_used_at`` is brought up to date, at most once per
    :data:`LAST_USED_THROTTLE`, and that write is committed.

    Args:
        db: Async database session.
        plaintext: The token as presented by the client.

    Returns:
        The owning user, or ``None`` when the token does not authenticate.
    """
    if not isinstance(plaintext, str) or not _TOKEN_PATTERN.match(plaintext):
        return None

    digest = hash_token(plaintext)
    token = await db.scalar(select(McpToken).where(McpToken.token_hash == digest))
    if token is None or not hmac.compare_digest(token.token_hash, digest):
        return None

    now = datetime.now(UTC)
    if not _is_active(token, now):
        return None

    user = await db.scalar(select(User).where(User.id == token.user_id))
    if user is None:
        return None

    if token.last_used_at is None or now - token.last_used_at >= LAST_USED_THROTTLE:
        await db.execute(
            update(McpToken)
            .where(McpToken.id == token.id, McpToken.user_id == token.user_id)
            .values(last_used_at=now)
        )
        await db.commit()
    return user


async def list_tokens(db: AsyncSession, user_id: uuid.UUID) -> list[McpToken]:
    """List a user's active tokens, newest first.

    Revoked and expired tokens are omitted: they can no longer be used, and
    listing them would only crowd out the ones the owner can act on.

    Args:
        db: Async database session.
        user_id: The owner.

    Returns:
        The user's active tokens.
    """
    now = datetime.now(UTC)
    result = await db.execute(
        select(McpToken)
        .where(
            McpToken.user_id == user_id,
            McpToken.revoked_at.is_(None),
            (McpToken.expires_at.is_(None)) | (McpToken.expires_at > now),
        )
        .order_by(McpToken.created_at.desc(), McpToken.id)
    )
    return list(result.scalars().all())


async def revoke_token(db: AsyncSession, user_id: uuid.UUID, token_id: uuid.UUID) -> None:
    """Revoke one of a user's tokens and commit.

    Idempotent: revoking an already revoked token succeeds and keeps its
    original ``revoked_at``.

    Args:
        db: Async database session.
        user_id: The owner.
        token_id: The token to revoke.

    Raises:
        TokenNotFoundError: If no such token belongs to the user. Another
            user's token is indistinguishable from an unknown one.
    """
    token = await db.scalar(
        select(McpToken).where(McpToken.id == token_id, McpToken.user_id == user_id)
    )
    if token is None:
        raise TokenNotFoundError(str(token_id))
    if token.revoked_at is None:
        token.revoked_at = datetime.now(UTC)
        await db.commit()
