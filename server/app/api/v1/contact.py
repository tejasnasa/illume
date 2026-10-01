"""Public contact endpoint.

Accepts a message from anyone -- signed in or not -- and emails it to the operator's
inbox. Nothing is persisted: the email is the entire product of a request, which is why
every delivery failure is surfaced to the caller rather than logged and swallowed. A
swallowed failure would leave the visitor told their message was sent while it existed
nowhere at all.

The route is public, so the auth middleware never requires a session for it. It still
*reads* one when present, letting a submission be attributed to an account without making
the endpoint depend on the database -- a database outage is one of the things someone
would plausibly use this form to report.
"""

import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from app.api.validation import FreeText, MultiLineText, NoControlCharacters
from app.services.mailer import (
    MailerNotConfigured,
    MailerUnavailable,
    send_contact_email,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/contact", tags=["contact"])

# The response is identical whether the message was delivered or the submission was
# discarded as automated, so a spam bot gets no signal to tune against.
SUCCESS_MESSAGE = "Thanks for getting in touch. We'll reply by email."

NOT_CONFIGURED_MESSAGE = (
    "The contact form is not accepting messages right now. Please reach out by email "
    "instead."
)

TIMEOUT_MESSAGE = "The mail service did not respond in time. Please try again."
DELIVERY_FAILED_MESSAGE = "Could not deliver your message. Please try again shortly."


class ContactCategory(StrEnum):
    """What a submission is about.

    A ``StrEnum`` so the value serializes as a bare string in the request body and in the
    email subject, matching the progress-stream enums in :mod:`app.services._stages`.
    """

    BUG = "bug"
    FEATURE = "feature"
    QUESTION = "question"
    OTHER = "other"


class ContactRequest(BaseModel):
    """A contact-form submission.

    Every field carries a length ceiling because the values are interpolated into an
    email: an unbounded message is an unbounded mail body, and the caps are the only
    thing bounding the outbound size.
    """

    category: ContactCategory
    name: FreeText = Field(min_length=2, max_length=100)
    # EmailStr already rejects control characters; the validator is repeated here so the
    # value's safety does not depend on which of the two validators runs first.
    email: Annotated[EmailStr, NoControlCharacters]
    # MultiLineText rather than FreeText: a message body is prose, and FreeText rejects the
    # line feed a person types by pressing Enter.
    message: MultiLineText = Field(min_length=10, max_length=5000)
    # A decoy no visitor can see. Named meaninglessly on purpose: `website`, `company`
    # and `address` are all targets of browser autofill, and a false positive here
    # discards a real message. Left unvalidated so a filled value reaches the handler,
    # which is what makes it detectable at all -- rejecting it would both tip off a bot
    # and log a 422 for a human whose autofill tripped it.
    illume_hp: str = ""


class MessageResponse(BaseModel):
    """Generic success envelope."""

    message: str


@router.post("", response_model=MessageResponse, status_code=status.HTTP_200_OK)
async def submit_contact(
    payload: ContactRequest, request: Request
) -> MessageResponse:
    """Email one contact-form submission to the operator.

    Args:
        payload: The validated submission.
        request: Incoming request, read for the peer address and any session identity.

    Returns:
        The success envelope. Also returned for a submission the honeypot discarded, so
        the two outcomes are indistinguishable from outside.

    Raises:
        HTTPException: 503 when the mailer is unconfigured, 504 when the mail service
            timed out, 502 when it was unreachable or rejected the message.
    """
    if payload.illume_hp:
        # The only trace a discarded submission leaves, and therefore the only way to
        # investigate a "did you get my message?" report against an autofill false
        # positive. Logged, never returned -- a distinct response would teach the bot
        # which field caught it.
        logger.warning(
            "Contact honeypot tripped from %s at %s; submission discarded",
            request.client.host if request.client else "unknown",
            datetime.now(UTC).isoformat(timespec="seconds"),
        )
        return MessageResponse(message=SUCCESS_MESSAGE)

    # Set by the auth middleware only when the request carried a valid session cookie;
    # absent for an anonymous visitor, and absent-but-harmless for a forged one.
    account_id = getattr(request.state, "user_id", None)

    try:
        await send_contact_email(
            category=payload.category.value,
            name=payload.name,
            email=payload.email,
            message=payload.message,
            account_id=account_id,
        )
    except MailerNotConfigured as exc:
        logger.error(
            "Contact form submitted while the mailer is unconfigured: %s", exc
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=NOT_CONFIGURED_MESSAGE,
        ) from exc
    except MailerUnavailable as exc:
        timed_out = exc.reason == "timeout"
        raise HTTPException(
            status_code=(
                status.HTTP_504_GATEWAY_TIMEOUT if timed_out else status.HTTP_502_BAD_GATEWAY
            ),
            detail=TIMEOUT_MESSAGE if timed_out else DELIVERY_FAILED_MESSAGE,
        ) from exc

    return MessageResponse(message=SUCCESS_MESSAGE)
