"""Which ``Host`` and ``Origin`` values the MCP endpoint answers to.

The allow-lists are derived from settings at import, so these tests call the
builders directly with patched settings rather than reloading the module.
"""

import pytest

from app.core.config import settings
from app.mcp import server
from app.mcp.server import _api_host_names, _origin

pytestmark = pytest.mark.unit

PROD_CALLBACK = "https://api.illume.example/api/v1/auth/github/callback"


@pytest.mark.parametrize(
    ("url", "hosts"),
    [
        (PROD_CALLBACK, ["api.illume.example"]),
        ("http://localhost:8000/api/v1/auth/github/callback", ["localhost:8000"]),
        ("https://user:pw@api.illume.example:8443/cb", ["api.illume.example:8443"]),
        ("http://[::1]:8000/cb", ["[::1]:8000"]),
        ("not a url", []),
    ],
)
def test_api_host_names_follow_the_url(url, hosts):
    assert _api_host_names(url) == hosts


def test_an_origin_is_scheme_host_and_port_only():
    assert _origin("https://user:pw@app.example:3000/path?q=1") == "https://app.example:3000"
    assert _origin("nonsense") is None


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "GITHUB_REDIRECT_URL", PROD_CALLBACK)
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://illume.example")


def test_production_answers_only_to_the_api_host(production):
    assert server._allowed_hosts() == ["api.illume.example"]


def test_production_allows_only_its_own_origins(production):
    assert server._allowed_origins() == ["https://illume.example", "https://api.illume.example"]


def test_development_also_answers_to_local_and_test_hosts():
    hosts = server._allowed_hosts()

    assert {"localhost:*", "127.0.0.1:*", "testserver"} <= set(hosts)
    assert server.MCP_ALLOWED_HOSTS == hosts


def test_the_domain_setting_is_not_used_as_the_api_host(production, monkeypatch):
    # `DOMAIN` is the cookie domain, which can be a parent of the API host.
    monkeypatch.setattr(settings, "DOMAIN", "illume.example")

    assert "illume.example" not in server._allowed_hosts()
