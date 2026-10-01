"""Contact endpoint: what it refuses, and what it must not leak.

The endpoint is unauthenticated by design, so the interesting cases are the ones where
someone is not a legitimate visitor -- or where the mail service is the thing that failed.
Kept separate from the happy paths in ``tests/integration/api/test_contact_api.py`` for the
same reason the GitHub proxy's abuse matrix is separate from its happy paths.
"""

import json

import httpx
import pytest
import respx

from app.core.config import settings

pytestmark = pytest.mark.security

RESEND = "https://api.resend.com/emails"
CONTACT = "/api/v1/contact"

VALID_SUBMISSION = {
    "category": "question",
    "name": "Jane Doe",
    "email": "jane@example.com",
    "message": "How does the reading order pick its starting point?",
    "illume_hp": "",
}


def accept_resend():
    """Stub Resend to accept the message, and return the route for assertions."""
    return respx.post(RESEND).mock(return_value=httpx.Response(200, json={"id": "abc"}))


def sent_payload(route) -> dict:
    """The JSON body of the last request that reached the mocked Resend endpoint."""
    return json.loads(route.calls.last.request.content)


class TestReachability:
    @respx.mock
    async def test_the_endpoint_answers_without_a_session(self, client):
        """No cookie, no account, still delivered -- this endpoint is deliberately open."""
        route = accept_resend()

        response = await client.post(CONTACT, json=VALID_SUBMISSION)

        assert response.status_code == 200
        assert route.call_count == 1


class TestHoneypot:
    @respx.mock
    async def test_a_filled_honeypot_sends_nothing(self, client):
        """
        The decoy field is invisible to a person, so anything in it came from something
        submitting every input it parsed.
        """
        route = accept_resend()

        response = await client.post(
            CONTACT, json={**VALID_SUBMISSION, "illume_hp": "https://spam.example"}
        )

        assert route.call_count == 0
        assert response.status_code == 200

    @respx.mock
    async def test_a_filled_honeypot_is_indistinguishable_from_success(self, client):
        """
        The response must be byte-identical to a real success. A distinct body would tell
        the sender which field caught it, and the next run would leave that field alone.
        """
        accepted = accept_resend()
        genuine = await client.post(CONTACT, json=VALID_SUBMISSION)
        assert accepted.call_count == 1

        tripped = await client.post(
            CONTACT, json={**VALID_SUBMISSION, "illume_hp": "https://spam.example"}
        )

        assert tripped.content == genuine.content
        assert tripped.status_code == genuine.status_code
        assert accepted.call_count == 1

    @respx.mock
    async def test_an_empty_honeypot_is_a_normal_submission(self, client):
        """The guard must not cost a real visitor their message."""
        route = accept_resend()

        response = await client.post(CONTACT, json={**VALID_SUBMISSION, "illume_hp": ""})

        assert response.status_code == 200
        assert route.call_count == 1

    @respx.mock
    async def test_an_absent_honeypot_key_is_a_normal_submission(self, client):
        """A client that never learned about the field must still be able to submit."""
        route = accept_resend()
        payload = {k: v for k, v in VALID_SUBMISSION.items() if k != "illume_hp"}

        response = await client.post(CONTACT, json=payload)

        assert response.status_code == 200
        assert route.call_count == 1


class TestEscaping:
    @respx.mock
    async def test_markup_in_the_name_is_escaped_in_html_but_raw_in_text(self, client):
        """
        The two bodies are escaped differently on purpose.

        Escaping the text body too would turn a pasted stack trace into a wall of
        ``&lt;``, so the asymmetry is the contract -- not an oversight to be tidied up.
        """
        route = accept_resend()
        hostile = "<script>alert(1)</script>"

        await client.post(CONTACT, json={**VALID_SUBMISSION, "name": hostile})

        payload = sent_payload(route)
        assert "<script>" not in payload["html"]
        assert "&lt;script&gt;" in payload["html"]
        assert hostile in payload["text"]

    @respx.mock
    async def test_ampersands_in_the_message_are_escaped_in_html(self, client):
        """An unescaped ampersand mangles the layout of the message being reported."""
        route = accept_resend()

        await client.post(CONTACT, json={**VALID_SUBMISSION, "message": "A & B crash when x < y"})

        html = sent_payload(route)["html"]
        assert "&amp;" in html
        assert "&lt; y" in html

    @respx.mock
    async def test_a_link_in_the_message_does_not_become_an_anchor(self, client):
        """
        The mail is DKIM-signed by this domain, so an injected link inherits that
        legitimacy. Escaped text cannot be rendered as one.
        """
        route = accept_resend()

        await client.post(
            CONTACT,
            json={
                **VALID_SUBMISSION,
                "message": 'Please log in at <a href="https://evil.example">illume</a> now.',
            },
        )

        assert "<a href" not in sent_payload(route)["html"]


class TestDeliveryFailures:
    @respx.mock
    async def test_an_unset_api_key_is_a_503(self, client, monkeypatch):
        route = accept_resend()
        monkeypatch.setattr(settings, "RESEND_API_KEY", "")

        response = await client.post(CONTACT, json=VALID_SUBMISSION)

        assert response.status_code == 503
        assert route.call_count == 0

    @respx.mock
    async def test_a_resend_rejection_is_a_502(self, client):
        """
        A swallowed failure here would tell the visitor their message was sent while it
        existed nowhere -- nothing is persisted, so there is no row to retry from.
        """
        respx.post(RESEND).mock(return_value=httpx.Response(422, json={"message": "invalid from"}))

        response = await client.post(CONTACT, json=VALID_SUBMISSION)

        assert response.status_code == 502

    @respx.mock
    async def test_a_resend_timeout_is_a_504(self, client):
        respx.post(RESEND).mock(side_effect=httpx.ConnectTimeout("timed out"))

        response = await client.post(CONTACT, json=VALID_SUBMISSION)

        assert response.status_code == 504

    @respx.mock
    async def test_a_transport_failure_is_a_502(self, client):
        respx.post(RESEND).mock(side_effect=httpx.ConnectError("no route"))

        response = await client.post(CONTACT, json=VALID_SUBMISSION)

        assert response.status_code == 502

    @respx.mock
    async def test_a_failure_does_not_leak_the_credential(self, client):
        """The upstream body is logged, never returned to an unauthenticated caller."""
        respx.post(RESEND).mock(
            return_value=httpx.Response(401, json={"message": "invalid api key"})
        )

        response = await client.post(CONTACT, json=VALID_SUBMISSION)

        assert response.status_code == 502
        assert settings.RESEND_API_KEY not in response.text
        assert "api key" not in response.text.lower()
