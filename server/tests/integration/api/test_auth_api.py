"""Registration, login, logout, and the current-user endpoint."""

import pytest

from tests.factories import make_user, unique_email

pytestmark = pytest.mark.integration

VALID_PASSWORD = "correct horse battery staple"
REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"


class TestRegister:
    async def test_creates_a_user(self, client, db_session):
        from sqlalchemy import select

        from app.models.user import User

        email = unique_email()
        response = await client.post(
            REGISTER,
            json={"email": email, "name": "Ada Lovelace", "password": VALID_PASSWORD},
        )

        assert response.status_code == 201
        result = await db_session.execute(select(User).where(User.email == email))
        assert result.scalar_one_or_none() is not None

    async def test_stores_a_hash_not_the_password(self, client, db_session):
        from sqlalchemy import select

        from app.models.user import User

        email = unique_email()
        await client.post(
            REGISTER,
            json={"email": email, "name": "Ada Lovelace", "password": VALID_PASSWORD},
        )

        result = await db_session.execute(select(User).where(User.email == email))
        stored = result.scalar_one().password
        assert stored != VALID_PASSWORD
        assert stored.startswith("$2")  # bcrypt

    async def test_rejects_a_duplicate_email(self, client, db_session):
        existing = await make_user(db_session)

        response = await client.post(
            REGISTER,
            json={
                "email": existing.email,
                "name": "Second User",
                "password": VALID_PASSWORD,
            },
        )

        assert response.status_code == 400
        assert "already registered" in response.json()["detail"].lower()

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("email", "not-an-email"),
            ("email", ""),
            ("name", "ab"),  # min_length=3
            ("name", ""),
            ("password", "short"),  # min_length=8
            ("password", ""),
        ],
        ids=[
            "malformed-email",
            "empty-email",
            "name-too-short",
            "name-empty",
            "password-too-short",
            "password-empty",
        ],
    )
    async def test_rejects_invalid_payloads(self, client, field, value):
        payload = {
            "email": unique_email(),
            "name": "Valid Name",
            "password": VALID_PASSWORD,
        }
        payload[field] = value

        response = await client.post(REGISTER, json=payload)

        assert response.status_code == 422

    async def test_rejects_a_missing_field(self, client):
        response = await client.post(REGISTER, json={"email": unique_email()})

        assert response.status_code == 422


class TestLogin:
    async def test_succeeds_with_correct_credentials(self, client, db_session):
        user = await make_user(db_session, password=VALID_PASSWORD)

        response = await client.post(LOGIN, json={"email": user.email, "password": VALID_PASSWORD})

        assert response.status_code == 200
        assert "set-cookie" in response.headers

    async def test_rejects_a_wrong_password(self, client, db_session):
        user = await make_user(db_session, password=VALID_PASSWORD)

        response = await client.post(
            LOGIN, json={"email": user.email, "password": "definitely-the-wrong-one"}
        )

        assert response.status_code == 401

    async def test_rejects_an_unknown_email(self, client):
        response = await client.post(
            LOGIN, json={"email": unique_email(), "password": VALID_PASSWORD}
        )

        assert response.status_code == 401

    async def test_wrong_password_and_unknown_email_are_indistinguishable(self, client, db_session):
        """
        Differing responses let an attacker enumerate registered addresses. The status
        code and the body must match exactly.
        """
        user = await make_user(db_session, password=VALID_PASSWORD)

        wrong_password = await client.post(
            LOGIN, json={"email": user.email, "password": "not-the-password"}
        )
        unknown_email = await client.post(
            LOGIN, json={"email": unique_email(), "password": VALID_PASSWORD}
        )

        assert wrong_password.status_code == unknown_email.status_code == 401
        assert wrong_password.json() == unknown_email.json()

    async def test_is_case_sensitive_on_password(self, client, db_session):
        user = await make_user(db_session, password=VALID_PASSWORD)

        response = await client.post(
            LOGIN, json={"email": user.email, "password": VALID_PASSWORD.upper()}
        )

        assert response.status_code == 401


class TestLogout:
    async def test_clears_the_session(self, client, db_session):
        user = await make_user(db_session, password=VALID_PASSWORD)
        await client.post(LOGIN, json={"email": user.email, "password": VALID_PASSWORD})

        response = await client.post(LOGOUT)

        assert response.status_code == 200
        # The cookie is expired on the response; httpx applies it to the jar.
        assert client.cookies.get("access_token") in {None, ""}


class TestMe:
    async def test_returns_the_current_user(self, client, db_session):
        from app.core.security import create_access_token

        user = await make_user(
            db_session,
            name="Grace Hopper",
            github_id="999",
            github_access_token="gho_token",
            avatar_url="https://avatars.githubusercontent.com/u/1",
        )
        client.cookies.set("access_token", create_access_token(subject=str(user.id)))

        response = await client.get(ME)

        assert response.status_code == 200
        body = response.json()
        assert body["email"] == user.email
        assert body["name"] == "Grace Hopper"

    async def test_requires_a_session(self, client):
        response = await client.get(ME)

        assert response.status_code == 401

    async def test_token_of_a_deleted_user_is_rejected(self, client, db_session):
        """A session outliving its user must not 500 or resolve to nobody."""
        import uuid as uuid_module

        from app.core.security import create_access_token

        client.cookies.set("access_token", create_access_token(subject=str(uuid_module.uuid4())))

        response = await client.get(ME)

        assert response.status_code == 401
