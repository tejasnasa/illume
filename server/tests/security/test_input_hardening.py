"""Hostile input through the query filters and stored-data surfaces.

The bar here is deliberately low and entirely about *shape*: no probe may produce a 500,
and no stored string may be interpreted rather than returned. These are not injection
tests in the classic sense -- SQLAlchemy parameterizes everything, so a 500 is the only
injection signal available at this layer. Text that reaches a browser is the client's
responsibility to escape, but it must arrive as inert data unchanged.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from tests.factories import (
    make_chat_message,
    make_glossary_entry,
    make_ingested_repo,
    make_repo,
    make_user,
    unique_email,
)
from tests.helpers import authenticate

pytestmark = pytest.mark.security


SQLI = [
    "' OR '1'='1",
    "'; DROP TABLE glossary_entries; --",
    "1; DELETE FROM users",
    "' UNION SELECT password FROM users --",
    "admin'--",
    "\\'; SELECT pg_sleep(5); --",
    "%' OR name LIKE '%",
]

XSS = [
    "<script>alert('xss')</script>",
    "<img src=x onerror=alert(1)>",
    "javascript:alert(document.cookie)",
    '"onmouseover="alert(1)',
    "<svg/onload=alert(1)>",
]

TRAVERSAL = [
    "../../../../etc/passwd",
    "..\\..\\..\\windows\\win.ini",
    "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "/proc/self/environ",
]


@pytest.fixture
async def target(client, db_session):
    """A signed-in user with a populated repository to probe."""
    user = await make_user(db_session)
    repo, _ = await make_ingested_repo(db_session, user)
    await make_glossary_entry(db_session, repo, name="Widget", definition="A widget.")
    await authenticate(client, user)
    return user, repo


@pytest.fixture
async def raw_client(app):
    """
    An unauthenticated client that returns 500s rather than re-raising them.

    ASGITransport propagates application exceptions by default, which turns an unhandled
    driver error into a test error rather than the status code a browser would receive.
    Tests that need a session call `authenticate(raw_client, user)` themselves.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as ac:
        yield ac


class TestFiltersNeverError:
    @pytest.mark.parametrize("payload", SQLI + XSS + TRAVERSAL, ids=str)
    async def test_glossary_search_survives(self, client, target, payload):
        _, repo = target

        response = await client.get(
            f"/api/v1/repository/{repo.id}/glossary/search", params={"q": payload}
        )

        assert response.status_code == 200

    @pytest.mark.parametrize("payload", SQLI + XSS + TRAVERSAL, ids=str)
    async def test_glossary_file_filter_survives(self, client, target, payload):
        _, repo = target

        response = await client.get(
            f"/api/v1/repository/{repo.id}/glossary", params={"file_path": payload}
        )

        assert response.status_code == 200

    @pytest.mark.parametrize("payload", SQLI + XSS + TRAVERSAL, ids=str)
    async def test_ownership_file_filter_survives(self, client, target, payload):
        _, repo = target

        response = await client.get(
            f"/api/v1/repository/{repo.id}/ownership", params={"file_path": payload}
        )

        assert response.status_code == 200

    @pytest.mark.parametrize("payload", SQLI + XSS + TRAVERSAL, ids=str)
    async def test_chat_question_is_not_interpreted(
        self, client, db_session, target, monkeypatch, payload
    ):
        """
        The question reaches an LLM prompt, not SQL, so the assertion is only that it is
        accepted and forwarded verbatim.
        """
        from app.services.rag import RAGResponse

        seen: list[str] = []

        async def fake(query, repository_id, db, history=None):
            seen.append(query)
            return RAGResponse(answer="ok", sources=[])

        import app.api.v1.chat as chat_module

        monkeypatch.setattr(chat_module, "answer_question", fake)
        _, repo = target

        response = await client.post(
            f"/api/v1/repository/{repo.id}/chat", json={"question": payload}
        )

        assert response.status_code == 200
        assert seen == [payload]

    @pytest.mark.parametrize("payload", SQLI + TRAVERSAL, ids=str)
    async def test_a_hostile_path_segment_is_rejected_as_malformed(self, client, target, payload):
        """A non-UUID path segment never reaches a query; routing rejects it first."""
        _, repo = target

        response = await client.get(f"/api/v1/repository/{payload}/stats")

        assert response.status_code in {404, 422}

    @pytest.mark.parametrize(
        ("param", "value"),
        [("page", "0"), ("page_size", "-1"), ("page", "1.5"), ("page", "abc")],
    )
    async def test_out_of_range_pagination_is_rejected(self, client, target, param, value):
        """Bounds that are checked: a floor, an integer type, and a page-size ceiling."""
        _, repo = target

        response = await client.get(f"/api/v1/repository/{repo.id}/glossary?{param}={value}")

        assert response.status_code == 422


class TestStoredTextIsInert:
    @pytest.mark.parametrize("payload", XSS, ids=str)
    async def test_a_repository_name_round_trips_unchanged(self, client, db_session, payload):
        """
        The name is stored as given and returned as given. Escaping belongs at the render
        boundary; mangling it here would corrupt legitimate names containing `<`.
        """
        user = await make_user(db_session)
        await make_repo(db_session, user, name=payload)
        await authenticate(client, user)

        body = (await client.get("/api/v1/repository")).json()

        assert body[0]["name"] == payload

    @pytest.mark.parametrize("payload", XSS, ids=str)
    async def test_a_glossary_definition_round_trips_unchanged(
        self, client, db_session, target, payload
    ):
        _, repo = target
        await make_glossary_entry(db_session, repo, name="Evil", definition=payload)

        response = await client.get(
            f"/api/v1/repository/{repo.id}/glossary/search", params={"q": "Evil"}
        )

        assert response.json()["entries"][0]["definition"] == payload

    @pytest.mark.parametrize("payload", XSS, ids=str)
    async def test_a_chat_question_round_trips_unchanged(self, client, db_session, target, payload):
        user, repo = target
        await make_chat_message(db_session, repo, user, question=payload, answer="a")

        body = (await client.get(f"/api/v1/repository/{repo.id}/chat/history")).json()

        assert body[0]["question"] == payload

    async def test_html_in_an_export_appears_literally(self, client, db_session, target):
        """
        The export is plain text and embeds `repo.name` into its `@@META` block. Markup
        must be carried through as the user typed it -- HTML-escaping here would corrupt
        the payload for every consumer that is not a browser, and the file is only ever
        rendered by whatever the user opens it in.
        """
        _, repo = target
        repo.name = "<script>alert(1)</script>"
        repo.architecture_summary = "<img src=x onerror=alert(2)>"
        await db_session.flush()

        response = await client.get(f"/api/v1/repository/{repo.id}/export/illume")

        assert response.status_code == 200
        assert "repo=<script>alert(1)</script>" in response.text
        assert "onerror=alert(2)" in response.text


class TestUnicode:
    @pytest.mark.parametrize(
        "name",
        ["日本語モジュール", "módulo", "🚀-rocket", "Ω-omega", "mixed-日本語-name"],
    )
    async def test_a_unicode_repository_name_round_trips(self, client, db_session, name):
        user = await make_user(db_session)
        await make_repo(db_session, user, name=name)
        await authenticate(client, user)

        body = (await client.get("/api/v1/repository")).json()

        assert body[0]["name"] == name

    async def test_a_unicode_glossary_term_is_searchable(self, client, db_session, target):
        """Case folding and substring matching must work outside the ASCII range."""
        _, repo = target
        await make_glossary_entry(db_session, repo, name="モジュール", definition="A module.")

        body = (
            await client.get(
                f"/api/v1/repository/{repo.id}/glossary/search", params={"q": "ジュール"}
            )
        ).json()

        assert body["total"] == 1

    async def test_a_unicode_string_needing_surrogate_pairs_round_trips(self, client, db_session):
        """Emoji outside the BMP are two UTF-16 units; they must survive both directions."""
        user = await make_user(db_session)
        name = "🚀🌟-project"
        await make_repo(db_session, user, name=name)
        await authenticate(client, user)

        assert (await client.get("/api/v1/repository")).json()[0]["name"] == name


class TestPayloadLimits:
    async def test_a_very_long_query_string_is_handled(self, client, target):
        """No stated bound on `q`; the requirement is only that it does not error."""
        _, repo = target

        response = await client.get(
            f"/api/v1/repository/{repo.id}/glossary/search", params={"q": "a" * 10_000}
        )

        assert response.status_code == 200

    async def test_a_very_long_chat_question_is_accepted(self, client, target, monkeypatch):
        from app.services.rag import RAGResponse

        async def fake(query, repository_id, db, history=None):
            return RAGResponse(answer="ok", sources=[])

        import app.api.v1.chat as chat_module

        monkeypatch.setattr(chat_module, "answer_question", fake)
        _, repo = target

        response = await client.post(
            f"/api/v1/repository/{repo.id}/chat", json={"question": "x" * 100_000}
        )

        assert response.status_code == 200

    async def test_an_oversized_history_list_is_truncated_not_rejected(
        self, client, target, monkeypatch
    ):
        """The route slices to the last five, so a huge client-side history is harmless."""
        from app.services.rag import RAGResponse

        forwarded: list = []

        async def fake(query, repository_id, db, history=None):
            forwarded.append(history)
            return RAGResponse(answer="ok", sources=[])

        import app.api.v1.chat as chat_module

        monkeypatch.setattr(chat_module, "answer_question", fake)
        _, repo = target
        history = [{"role": "user", "content": "x" * 1000} for _ in range(500)]

        response = await client.post(
            f"/api/v1/repository/{repo.id}/chat", json={"question": "q", "history": history}
        )

        assert response.status_code == 200
        assert len(forwarded[0]) == 5


class TestNullByteExposure:
    """
    A NUL byte survives JSON decoding and request validation, then fails inside the
    PostgreSQL driver: `CharacterNotInRepertoireError: invalid byte sequence for UTF8:
    0x00`. It is not injection -- the value is a bound parameter -- but it is an
    unhandled 500 on trivially reachable input.

    The registration case is the serious one: that endpoint is public, so no session is
    needed to reach it.
    """

    async def test_registration_with_a_null_byte_in_the_name(self, raw_client):
        response = await raw_client.post(
            "/api/v1/auth/register",
            json={
                "email": unique_email(),
                "name": "a\x00b",
                "password": "long-enough-password",
            },
        )

        assert response.status_code == 422

    async def test_glossary_search_with_a_null_byte(self, raw_client, target):
        user, repo = target
        await authenticate(raw_client, user)

        response = await raw_client.get(
            f"/api/v1/repository/{repo.id}/glossary/search", params={"q": "a\x00b"}
        )

        assert response.status_code in {200, 422}

    async def test_ownership_filter_with_a_null_byte(self, raw_client, target):
        user, repo = target
        await authenticate(raw_client, user)

        response = await raw_client.get(
            f"/api/v1/repository/{repo.id}/ownership", params={"file_path": "a\x00b"}
        )

        assert response.status_code in {200, 422}

    async def test_login_with_a_null_byte_is_merely_unauthorized(self, raw_client, db_session):
        """
        The control, and the reason the fix belongs at the boundary rather than in the
        driver: login compares the hash in Python before any statement runs, so a NUL in
        the password is rejected as a wrong password. Nothing about the character itself
        is illegal -- only reaching a statement with it is.
        """
        user = await make_user(db_session)

        response = await raw_client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": "a\x00b"}
        )

        assert response.status_code == 401


class TestPaginationOverflow:
    """
    `page` and `page_size` are bounded below but not above. `(page - 1) * page_size`
    is computed in Python as an unbounded int, then bound as a BIGINT, where values past
    2**63 raise `DataError` inside asyncpg -- an unhandled 500.
    """

    @pytest.mark.parametrize("huge", ["999999999999999999999999", str(2**63), str(2**64)])
    async def test_a_page_far_beyond_int64_is_rejected(self, raw_client, target, huge):
        user, repo = target
        await authenticate(raw_client, user)

        response = await raw_client.get(
            f"/api/v1/repository/{repo.id}/glossary", params={"page": huge}
        )

        assert response.status_code == 422

    async def test_a_page_size_at_the_int64_boundary_is_rejected(self, raw_client, target):
        """`page_size` already has `le=100`, so it only overflows by way of `page`."""
        user, repo = target
        await authenticate(raw_client, user)

        response = await raw_client.get(
            f"/api/v1/repository/{repo.id}/ownership",
            params={"page": str(2**63), "page_size": "100"},
        )

        assert response.status_code == 422

    async def test_a_large_but_representable_offset_is_fine(self, raw_client, target):
        """
        The control: the boundary is int64, not some smaller practical limit. A page
        number inside the range yields an empty page rather than an error. Without this,
        the tests above could be passing on a 401 rather than on the overflow.
        """
        user, repo = target
        await authenticate(raw_client, user)

        response = await raw_client.get(
            f"/api/v1/repository/{repo.id}/glossary", params={"page": "1000000000"}
        )

        assert response.status_code == 200
        assert response.json()["entries"] == []
