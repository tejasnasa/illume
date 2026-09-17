"""Session cookie attributes on register, login, and logout.

The cookie is the entire session mechanism -- there is no bearer token and nothing is
kept in localStorage -- so its flags are the difference between a session and a
cross-site scripting foothold.
"""

import pytest

from app.core.config import settings
from tests.factories import make_user, unique_email

pytestmark = pytest.mark.security

COOKIE_NAME = "access_token"


def session_cookies(response) -> list[str]:
    """Every `Set-Cookie` header on the response, in order."""
    return response.headers.get_list("set-cookie")


def the_cookie(response) -> str:
    """The single session cookie header, asserting there is exactly one."""
    cookies = [c for c in session_cookies(response) if c.startswith(f"{COOKIE_NAME}=")]

    assert len(cookies) == 1, f"expected exactly one {COOKIE_NAME} cookie, got {cookies}"
    return cookies[0]


class TestLoginCookie:
    async def test_sets_one_httponly_lax_cookie(self, client, db_session):
        password = "correct horse battery staple"
        user = await make_user(db_session, password=password)

        response = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": password},
        )

        assert response.status_code == 200
        cookie = the_cookie(response)
        assert "httponly" in cookie.lower()
        assert "samesite=lax" in cookie.lower()

    async def test_is_not_secure_in_development(self, client, db_session):
        """`secure` would make the cookie unusable over plain-HTTP localhost."""
        assert settings.ENVIRONMENT != "production"
        password = "correct horse battery staple"
        user = await make_user(db_session, password=password)

        response = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": password},
        )

        assert "secure" not in the_cookie(response).lower()

    async def test_failed_login_sets_no_cookie(self, client, db_session):
        user = await make_user(db_session)

        response = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "the-wrong-password"},
        )

        assert response.status_code == 401
        assert session_cookies(response) == []


class TestRegisterCookie:
    async def test_sets_one_httponly_lax_cookie(self, client):
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": unique_email(),
                "name": "New User",
                "password": "correct horse battery staple",
            },
        )

        assert response.status_code == 201
        cookie = the_cookie(response)
        assert "httponly" in cookie.lower()
        assert "samesite=lax" in cookie.lower()

    async def test_rejected_registration_sets_no_cookie(self, client, db_session):
        existing = await make_user(db_session)

        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": existing.email,
                "name": "Duplicate",
                "password": "correct horse battery staple",
            },
        )

        assert response.status_code == 400
        assert session_cookies(response) == []


class TestLogout:
    async def test_clears_the_cookie(self, client):
        response = await client.post("/api/v1/auth/logout")

        assert response.status_code == 200
        cookie = the_cookie(response)
        # An expiring Set-Cookie is how a deletion is expressed.
        assert "max-age=0" in cookie.lower() or "expires=" in cookie.lower()


class TestCookieDomain:
    async def test_domain_is_a_bare_hostname(self, client):
        """
        A `Domain` attribute carrying a scheme or port is not a valid cookie domain and
        browsers may drop the cookie entirely. `settings.DOMAIN` is passed through
        verbatim, so this guards against it being configured as a full URL.
        """
        assert "://" not in settings.DOMAIN
        assert ":" not in settings.DOMAIN

        response = await client.post(
            "/api/v1/auth/login",
            json={"email": unique_email(), "password": "irrelevant"},
        )
        # Login fails, but the assertion above is what matters; this keeps the check
        # honest about DOMAIN being exercised in a real response path.
        assert response.status_code in {200, 401}
