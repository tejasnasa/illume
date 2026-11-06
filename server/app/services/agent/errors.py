"""Turning a failed model call into the message and status the user sees.

The mapping is the one the chat endpoint applies to the same SDK exceptions, so
a rejected key, an unreachable provider and a provider error read the same
whichever way the question was asked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError

ErrorKind = Literal["auth", "unreachable", "provider", "internal"]


class ProviderStreamError(Exception):
    """The provider ended a streamed response with a failure."""


@dataclass(frozen=True)
class RunError:
    """Why a run failed.

    Attributes:
        kind: ``auth`` for a rejected key, ``unreachable`` for a connection or
            timeout, ``provider`` for any other provider error, ``internal``
            for a failure in this service.
        message: What to show the user.
        status: The HTTP status the chat endpoint answers the same failure with.
        exception: The exception class name, for the log.
    """

    kind: ErrorKind
    message: str
    status: int
    exception: str


def describe_error(error: BaseException) -> RunError:
    """Maps an exception raised during a run to a :class:`RunError`.

    ``AuthenticationError`` is a kind of ``APIStatusError`` and a timeout is a
    kind of connection error, so the order of the checks matters.
    """
    name = type(error).__name__
    if isinstance(error, AuthenticationError):
        return RunError("auth", f"Provider rejected the API key: {error}", 502, name)
    if isinstance(error, APIConnectionError | APITimeoutError):
        return RunError("unreachable", f"Could not reach the LLM provider: {error}", 502, name)
    if isinstance(error, APIStatusError | ProviderStreamError):
        return RunError("provider", f"Provider returned an error: {error}", 502, name)
    return RunError("internal", f"The agent failed unexpectedly ({name}).", 500, name)
