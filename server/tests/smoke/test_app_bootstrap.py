"""The application assembles correctly: routers mounted, middleware installed.

Routers are identified by their ``tags`` rather than their path prefix. Seven of the
ten routers are mounted under ``/api/v1/repository`` (repository, chat, glossary, graph,
guide, ownership, stats), so prefix matching cannot tell them apart -- a missing
``glossary`` router would look identical to a missing ``stats`` router.
"""

import pytest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from starlette.routing import WebSocketRoute

from app.main import app
from app.middleware.auth import AuthMiddleware

pytestmark = pytest.mark.smoke

# Endpoints mounted under /api/v1. Deliberate tripwire: update when a route is added
# or removed so that an accidental drop shows up as a failing test, not a silent gap.
EXPECTED_API_ROUTE_COUNT = 27

EXPECTED_TAGS = {
    "auth",
    "chat",
    "github",
    "glossary",
    "graph",
    "guide",
    "ownership",
    "repository",
    "stats",
}

# One representative path per router group, so a router that mounts zero routes is
# caught even if its tag is registered.
REPRESENTATIVE_PATHS = {
    "/healthz",
    "/api/v1/auth/login",
    "/api/v1/auth/me",
    "/api/v1/github/repos",
    "/api/v1/repository",
    "/api/v1/repository/{repo_id}/graph",
    "/api/v1/repository/{repo_id}/glossary",
    "/api/v1/repository/{repo_id}/guide",
    "/api/v1/repository/{repo_id}/ownership",
    "/api/v1/repository/{repo_id}/stats",
    "/api/v1/repository/{repo_id}/chat",
    "/api/v1/repository/{repo_id}/export/illume",
}


def _api_routes():
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1")
    ]


def _mounted_tags() -> set[str]:
    tags: set[str] = set()
    for route in _api_routes():
        tags.update(route.tags or [])
    return tags


def test_app_imports_and_carries_routes():
    assert _api_routes(), "no versioned routes were mounted"


def test_every_router_tag_is_present():
    missing = EXPECTED_TAGS - _mounted_tags()

    assert not missing, f"routers missing from the app: {sorted(missing)}"


def test_representative_paths_are_mounted():
    mounted = {route.path for route in app.routes}

    missing = REPRESENTATIVE_PATHS - mounted

    assert not missing, f"expected paths not mounted: {sorted(missing)}"


def test_api_route_count_is_stable():
    """Guards against a route being silently dropped or duplicated."""
    assert len(_api_routes()) == EXPECTED_API_ROUTE_COUNT


def test_websocket_route_is_mounted():
    ws_routes = [r for r in app.routes if isinstance(r, WebSocketRoute)]

    assert [r.path for r in ws_routes] == ["/api/v1/ws/ingest/{repo_id}"]


def test_auth_and_cors_middleware_are_installed():
    installed = {middleware.cls for middleware in app.user_middleware}

    assert AuthMiddleware in installed
    assert CORSMiddleware in installed


async def test_openapi_schema_is_served_and_parses(client):
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"]
    assert "/healthz" in schema["paths"]
