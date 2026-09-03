"""Cookie-based JWT authentication middleware.

Decodes the ``access_token`` cookie on every request (except public paths)
and stores the user ID on ``request.state`` for downstream dependencies.
"""

from app.core.security import decode_access_token
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class AuthMiddleware(BaseHTTPMiddleware):
    """Validate the session cookie and attach the user ID to the request."""

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
            "/api/v1/ws",
            "/openapi.json",
        ]

        if any(request.url.path.startswith(path) for path in public_paths):
            return await call_next(request)

        token = request.cookies.get("access_token")
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
