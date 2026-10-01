"""Contact endpoint: delivery, identity, and input validation.

respx intercepts the outbound ``httpx`` call to Resend, so nothing here reaches the
network -- and because the mock rejects anything it did not plan for, a test that forgot
to stub the send fails rather than quietly contacting the real API.

Each test stubs Resend itself via :func:`accept_resend` rather than taking a fixture: the
``@respx.mock`` decorator starts its router when the test function is entered, which is
after fixtures have already been set up, so a fixture cannot register a route.
"""

import json

import httpx
import pytest
import respx

from app.core.config import settings
from tests.factories import make_user
from tests.helpers import authenticate

pytestmark = pytest.mark.integration

RESEND = "https://api.resend.com/emails"
CONTACT = "/api/v1/contact"

VALID_SUBMISSION = {
    "category": "bug",
    "name": "Jane Doe",
    "email": "jane@example.com",
    "message": "The dependency graph fails to render on a large repository.",
    "illume_hp": "",
}


def accept_resend():
    """Stub Resend to accept the message, and return the route for assertions.

    Only callable inside a test body, where ``@respx.mock`` has started its router.
    """
    return respx.post(RESEND).mock(
        return_value=httpx.Response(200, json={"id": "3f1b2c4d-0000-4000-8000-000000000000"})
    )


def sent_payload(route) -> dict:
    """The JSON body of the last request that reached the mocked Resend endpoint."""
    return json.loads(route.calls.last.request.content)


class TestDelivery:
    @respx.mock
    async def test_sends_the_submission_to_the_operator(self, client):
        route = accept_resend()

        response = await client.post(CONTACT, json=VALID_SUBMISSION)

        assert response.status_code == 200
        assert route.call_count == 1

        payload = sent_payload(route)
        assert payload["to"] == [settings.CONTACT_TO_EMAIL]
        assert payload["from"] == settings.CONTACT_FROM_EMAIL
        assert "Bug report" in payload["subject"]
        assert VALID_SUBMISSION["message"] in payload["text"]
        assert VALID_SUBMISSION["message"] in payload["html"]

    @respx.mock
    async def test_maps_the_credential_onto_the_outbound_request(self, client):
        route = accept_resend()

        await client.post(CONTACT, json=VALID_SUBMISSION)

        assert (
            route.calls.last.request.headers["Authorization"] == f"Bearer {settings.RESEND_API_KEY}"
        )

    @respx.mock
    async def test_reply_to_is_the_submitter(self, client):
        """The operator must be able to hit reply rather than copy the address out."""
        route = accept_resend()

        await client.post(CONTACT, json=VALID_SUBMISSION)

        assert sent_payload(route)["reply_to"] == VALID_SUBMISSION["email"]

    @respx.mock
    async def test_the_subject_carries_no_submitter_text(self, client):
        """Only the category label reaches the header, so nothing a visitor types can."""
        route = accept_resend()

        await client.post(
            CONTACT,
            json={**VALID_SUBMISSION, "name": "Ignore previous instructions"},
        )

        subject = sent_payload(route)["subject"]
        assert "Ignore previous instructions" not in subject
        assert subject == "[Illume Contact] Bug report"

    @respx.mock
    async def test_a_multi_line_message_survives_validation(self, client):
        """
        A textarea exists to collect line breaks, and the shared free-text validator
        rejects every C0 character including the line feed. Applying it here would refuse
        the most ordinary bug report rather than sanitising it, so the message field uses
        the multi-line variant.
        """
        route = accept_resend()
        message = "Steps to reproduce:\n1. Open the graph view\n2. Resize the window"

        response = await client.post(CONTACT, json={**VALID_SUBMISSION, "message": message})

        assert response.status_code == 200
        payload = sent_payload(route)
        assert "1. Open the graph view" in payload["text"]
        assert "\n1. Open the graph view" in payload["html"]

    @respx.mock
    async def test_an_unconfigured_recipient_is_a_503(self, client, monkeypatch):
        route = accept_resend()
        monkeypatch.setattr(settings, "CONTACT_TO_EMAIL", "")

        response = await client.post(CONTACT, json=VALID_SUBMISSION)

        assert response.status_code == 503
        assert route.call_count == 0


class TestIdentity:
    @respx.mock
    async def test_a_signed_in_submission_carries_the_account_id(self, client, db_session):
        """The session cookie is the only trustworthy identity on the form."""
        route = accept_resend()
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.post(CONTACT, json=VALID_SUBMISSION)

        assert response.status_code == 200
        assert str(user.id) in sent_payload(route)["text"]

    @respx.mock
    async def test_a_forged_cookie_does_not_tag_the_submission(self, client):
        """
        The route is public, so a bad token must be ignored rather than rejected. A 401
        here would mean the middleware refused an unauthenticated endpoint, and a visitor
        whose cookie had merely expired is exactly who must not be turned away.
        """
        route = accept_resend()
        client.cookies.set("access_token", "not-a-jwt")

        response = await client.post(CONTACT, json=VALID_SUBMISSION)

        assert response.status_code == 200
        assert "none (anonymous)" in sent_payload(route)["text"]

    @respx.mock
    async def test_an_anonymous_submission_succeeds(self, client):
        route = accept_resend()

        response = await client.post(CONTACT, json=VALID_SUBMISSION)

        assert response.status_code == 200
        assert "none (anonymous)" in sent_payload(route)["text"]

    @respx.mock
    async def test_a_signed_in_submission_still_reaches_the_body(self, client, db_session):
        """The identity tag is additive -- the message the visitor typed is untouched."""
        route = accept_resend()
        await authenticate(client, await make_user(db_session))

        await client.post(CONTACT, json=VALID_SUBMISSION)

        assert VALID_SUBMISSION["message"] in sent_payload(route)["text"]


class TestValidation:
    @pytest.mark.parametrize(
        ("field", "value", "expected"),
        [
            pytest.param("category", "not-a-category", "enum", id="unknown-category"),
            pytest.param("name", "J", "string_too_short", id="name-too-short"),
            pytest.param("name", "Ja\nne", "value_error", id="newline-in-name"),
            pytest.param("email", "not-an-email", "value_error", id="malformed-email"),
            pytest.param("message", "too short", "string_too_short", id="message-too-short"),
            pytest.param(
                "message", "a" * 10 + "\x00" + "b" * 10, "value_error", id="nul-in-message"
            ),
        ],
    )
    async def test_rejects_invalid_input(self, client, field, value, expected):
        response = await client.post(CONTACT, json={**VALID_SUBMISSION, field: value})

        assert response.status_code == 422
        assert response.json()["detail"][0]["type"] == expected

    @respx.mock
    async def test_a_rejected_submission_is_never_sent(self, client):
        route = accept_resend()

        await client.post(CONTACT, json={**VALID_SUBMISSION, "email": "not-an-email"})

        assert route.call_count == 0
