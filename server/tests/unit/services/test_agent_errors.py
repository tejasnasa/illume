"""Provider failures map to the messages and status the chat endpoint gives them."""

from __future__ import annotations

import httpx
import pytest
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
)

from app.services.agent.errors import ProviderStreamError, describe_error

pytestmark = pytest.mark.unit

REQUEST = httpx.Request("POST", "https://api.example.com/v1/responses")


def response(status: int) -> httpx.Response:
    return httpx.Response(status, request=REQUEST)


@pytest.mark.parametrize(
    ("error", "kind", "prefix"),
    [
        (AuthenticationError("no", response=response(401), body=None), "auth", "Provider rejected"),
        (APIConnectionError(request=REQUEST), "unreachable", "Could not reach the LLM provider"),
        (APITimeoutError(request=REQUEST), "unreachable", "Could not reach the LLM provider"),
        (
            RateLimitError("slow", response=response(429), body=None),
            "provider",
            "Provider returned an error",
        ),
        (
            InternalServerError("oops", response=response(500), body=None),
            "provider",
            "Provider returned an error",
        ),
        (
            NotFoundError("model", response=response(404), body=None),
            "provider",
            "Provider returned an error",
        ),
        (ProviderStreamError("overloaded"), "provider", "Provider returned an error: overloaded"),
    ],
)
def test_provider_failures(error, kind, prefix):
    described = describe_error(error)

    assert described.kind == kind
    assert described.message.startswith(prefix)
    assert described.status == 502
    assert described.exception == type(error).__name__


def test_an_authentication_error_is_not_mistaken_for_a_generic_status_error():
    error = AuthenticationError("no", response=response(401), body=None)

    assert describe_error(error).kind == "auth"


def test_a_bug_is_internal_and_does_not_leak_its_message():
    described = describe_error(KeyError("secret detail"))

    assert described.kind == "internal"
    assert described.status == 500
    assert "secret detail" not in described.message
    assert "KeyError" in described.message
