"""Authentication middleware.

Decodes the ``access_token`` cookie on every request (except public paths)
and stores the user ID on ``request.state``. Native clients that have no
browser cookie jar carry the same token in an ``Authorization: Bearer``
header instead -- both paths funnel through :func:`_resolve_token` so the
rest of the request lifecycle is identical.
"""

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.security import decode_access_token


def _resolve_token(request: Request) -> str | None:
    """Return whichever token the caller supplied, preferring the cookie.

    The cookie is preferred because it cannot be exfiltrated by any script
    that lands in the browser; ``Authorization`` is the fallback the moment
    a native client (no cookie jar) needs to authenticate. Both paths are
    equivalent once decoded.

    Args:
        request: Incoming HTTP request.

    Returns:
        The raw token string, or ``None`` when the caller sent neither.
    """
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        return cookie_token
    header = request.headers.get("authorization")
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


class AuthMiddleware(BaseHTTPMiddleware):
    """Validate the session cookie or bearer header and attach the user ID to the request."""

    async def dispatch(self, request: Request, call_next):
        """Authenticate the request or reject it with 401.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware/route handler in the chain.

        Returns:
            The downstream response, or a 401 JSON response when the
            token is missing, invalid, or expired.
        """
        # Prefix matches so sub-paths (e.g. /api/v1/ws/ingest/...) also bypass
        # auth; the WS handler performs its own token check from cookie/query.
        public_paths = [
            "/healthz",
            "/api/v1/auth/login",
            "/api/v1/auth/register",
            "/api/v1/auth/logout",
            "/api/v1/auth/github",
            "/api/v1/auth/github/callback",
            "/api/v1/contact",
            "/api/v1/ws",
            "/openapi.json",
        ]

        if any(request.url.path.startswith(path) for path in public_paths):
            # A public route still gets an opportunistic identity when the caller happens
            # to be signed in. The contact endpoint is reachable either way, but a
            # submission carrying a session can be attributed to an account -- and the
            # only place a cookie can be read is here, since it is httpOnly. A bearer
            # header is acceptable on the same footing: the contact form works for
            # native clients too. A missing or invalid token is ignored rather than
            # rejected, because the route does not require one;
            # `decode_access_token` returns None instead of raising, which is
            # what makes ignoring it safe.
            token = _resolve_token(request)
            if token:
                user_id = decode_access_token(token)
                if user_id:
                    request.state.user_id = user_id
            return await call_next(request)

        token = _resolve_token(request)
        if not token:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Not authenticated"},
            )

        user_id = decode_access_token(token)
        if not user_id:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid or expired token"},
            )

        request.state.user_id = user_id
        return await call_next(request)
