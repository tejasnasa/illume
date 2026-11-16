"""Bearer-token authentication for the MCP endpoint.

The SDK's own ``TokenVerifier`` / ``AuthSettings`` are not used: they advertise
OAuth protected-resource metadata, which would send a client with a bad token off
to look for an authorization server. Illume's tokens are personal access tokens
the user pastes into a client, so the only useful answer to a bad one is a plain
``401`` and ``WWW-Authenticate: Bearer``.

:class:`BearerAuthMiddleware` wraps the SDK's ASGI app, so it is the outermost
layer of the MCP app. That fixes the order against the SDK's transport security:
authentication runs first, so a request with a disallowed ``Host`` and no valid
token gets ``401``, not ``421``. A request with a valid token and a bad ``Host``
or ``Origin`` still reaches the transport check and is refused there.

The transport is stateless, so the token is verified on every request and a
revoked token stops working on the very next call.
"""

from __future__ import annotations

import uuid
from typing import Any

from mcp.server import ServerRequestContext
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.services.mcp_tokens import resolve_token

USER_ID_STATE_KEY = "mcp_user_id"
"""Key in the request's ``scope["state"]`` under which the token owner's id is kept."""

_BEARER = "bearer "


def _bearer_token(request: Request) -> str | None:
    """The token from an ``Authorization: Bearer`` header, or ``None`` if absent."""
    header = request.headers.get("authorization", "")
    if header[: len(_BEARER)].lower() != _BEARER:
        return None
    return header[len(_BEARER) :].strip() or None


class BearerAuthMiddleware:
    """Refuse every HTTP request that does not carry a valid Illume token.

    On success the token owner's id is stored in ``scope["state"]`` for the tool
    handlers (see :func:`current_user_id`). The database session used to check the
    token is closed before the wrapped app runs, so no connection is held for the
    length of an SSE stream.

    Args:
        app: The ASGI app to guard.
        session_factory: Source of the sessions used to resolve tokens.
    """

    def __init__(self, app: ASGIApp, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.app = app
        self.session_factory = session_factory

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Authenticate HTTP requests; pass lifespan and other scopes straight through."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        token = _bearer_token(Request(scope))
        user_id: uuid.UUID | None = None
        if token is not None:
            async with self.session_factory() as db:
                user = await resolve_token(db, token)
                user_id = user.id if user is not None else None

        if user_id is None:
            response = PlainTextResponse(
                "invalid or missing Illume token",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        state = scope.setdefault("state", {})
        state[USER_ID_STATE_KEY] = user_id
        await self.app(scope, receive, send)


def current_user_id(ctx: ServerRequestContext[Any]) -> uuid.UUID:
    """The id of the user whose token authenticated the current request.

    Args:
        ctx: The request context handed to a tool handler.

    Returns:
        The token owner's user id.

    Raises:
        RuntimeError: If the request did not pass through :class:`BearerAuthMiddleware`.
    """
    request = ctx.request
    state = getattr(request, "scope", {}).get("state") or {}
    user_id = state.get(USER_ID_STATE_KEY)
    if not isinstance(user_id, uuid.UUID):
        raise RuntimeError("MCP request carries no authenticated user")
    return user_id
