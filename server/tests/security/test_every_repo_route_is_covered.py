"""Guards the IDOR matrix against drift.

`test_idor.py` parametrizes over a hand-written list. A hand-written list goes stale: the
next repository-scoped endpoint someone adds will be protected by whatever the author
wrote, and nothing will notice that it never landed in the matrix.

This module closes that hole by deriving the route list from the application itself and
asserting the two agree. It is the reason the matrix can stay declarative without
becoming a liability.
"""

import pytest
from starlette.routing import WebSocketRoute

from tests.security.test_idor import REPO_ROUTES

pytestmark = pytest.mark.security

REPO_PARAMS = ("{repo_id}", "{repo_num}")
IGNORED_METHODS = {"HEAD", "OPTIONS"}


def normalise(path: str) -> str:
    """
    Reduce an application or matrix path to a comparable form.

    Both identifier spellings collapse to `{ref}`, and the query string is dropped -- the
    matrix records one entry per route and varies the query within the test, while the
    application's `path` never carries a query at all.
    """
    for param in REPO_PARAMS:
        path = path.replace(param, "{ref}")
    return path.split("?", 1)[0].rstrip("/") or "/"


def app_repo_routes() -> set[tuple[str, str]]:
    """Every HTTP route on the app whose path is scoped to a repository."""
    from app.main import app

    found: set[tuple[str, str]] = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        if not any(param in path for param in REPO_PARAMS):
            continue
        # WebSocket routes carry no methods and are covered by the WS suite, which has
        # to drive a connection rather than a request.
        if isinstance(route, WebSocketRoute):
            continue
        for method in getattr(route, "methods", None) or ():
            if method not in IGNORED_METHODS:
                found.add((method, normalise(path)))
    return found


def matrix_routes() -> set[tuple[str, str]]:
    """Every route the IDOR matrix claims to cover."""
    return {(route.method, normalise(route.template)) for route in REPO_ROUTES}


class TestMatrixMatchesTheApplication:
    def test_every_repository_route_is_in_the_matrix(self):
        """
        A new `/{repo_id}` endpoint fails here until it is added to `REPO_ROUTES`.

        This is the assertion that makes the matrix a gate rather than a snapshot of
        whatever existed the day it was written.
        """
        missing = app_repo_routes() - matrix_routes()

        assert missing == set(), (
            "These repository-scoped routes exist but are not in the IDOR matrix in "
            f"tests/security/test_idor.py: {sorted(missing)}"
        )

    def test_the_matrix_has_no_stale_entries(self):
        """
        The other direction: a route deleted from the application must not linger in the
        matrix, where it would silently test nothing (or 404 forever for the wrong
        reason).
        """
        stale = matrix_routes() - app_repo_routes()

        assert stale == set(), f"These matrix entries match no route on the app: {sorted(stale)}"

    def test_the_sweep_is_not_vacuous(self):
        """
        Both assertions above pass trivially if the discovery finds nothing -- which is
        exactly what a refactor that renames the path parameter would cause.
        """
        assert len(app_repo_routes()) >= 15

    def test_the_repo_number_route_is_present(self):
        """
        `GET /{repo_num}` is the route a UUID-keyed sweep would skip, so it is asserted
        by name rather than left to the set comparison.
        """
        assert ("GET", "/api/v1/repository/{ref}") in matrix_routes()

    def test_both_identifier_spellings_are_discovered(self):
        """If only one spelling were collected, half the surface would go unchecked."""
        from app.main import app

        paths = {getattr(r, "path", "") for r in app.routes}
        assert any("{repo_num}" in p for p in paths)
        assert any("{repo_id}" in p for p in paths)


class TestWebSocketRoutes:
    def test_the_ingest_socket_is_the_only_websocket(self):
        """
        WebSocket routes are excluded from the HTTP matrix, so they need their own
        accounting -- otherwise a new socket would be covered by neither. When another
        one is added, this fails and points at the WS suite.
        """
        from app.main import app

        sockets = {r.path for r in app.routes if isinstance(r, WebSocketRoute)}

        assert sockets == {"/api/v1/ws/ingest/{repo_id}"}
