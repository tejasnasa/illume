"""Contact-form delivery through the Resend HTTP API.

Uses raw ``httpx`` rather than the Resend SDK: ``httpx`` reaches the tree through
``fastapi[standard]`` and is already imported directly in :mod:`app.api.v1.github_proxy`,
so this adds no dependency and needs no lockfile regeneration. The image is built with
``uv sync --frozen --no-dev``, which makes a new dependency a build change rather than a
one-line edit.

No ``fastapi`` import here on purpose. The status-code mapping belongs to the router, and
:class:`MailerUnavailable` carries the reason for it to map.

**This module fails loudly, which is the opposite of what a best-effort notifier usually
does.** A swallowed send in a request whose only product *is* the email means the operator
never learns the visitor wrote, while the visitor is told the message was sent -- and
because nothing is persisted, there is no row to replay it from. So every failure raises,
and the router turns it into a 5xx the visitor can see and act on.
"""

import html
import logging
from datetime import UTC, datetime

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"
TIMEOUT = 15.0

# Human-readable names for the category slugs the endpoint accepts. A slug with no entry
# falls back to itself rather than raising: a category added to the request model and not
# here should still deliver, just with the raw value in the subject.
_CATEGORY_LABELS = {
    "bug": "Bug report",
    "feature": "Feature request",
    "question": "Question",
    "other": "Other",
}

_PAGE_BACKGROUND = "#17131a"
_CARD_BACKGROUND = "#211b26"
_BORDER = "rgba(255,255,255,0.08)"
_ACCENT = "#a3004c"
_FOREGROUND = "#f8f8f8"
_MUTED = "#a89aa8"
_FAINT = "#6f6572"
_FONT_STACK = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"

# Named rather than inlined at each use. A mail client only honours styles declared on the
# element itself, so every rule has to be repeated inline -- and inlining them made the
# markup one 216-character line whose actual content was hard to find.
_PAGE_STYLE = f"background-color: {_PAGE_BACKGROUND}; padding: 40px 16px;"
_BODY_STYLE = (
    f"margin: 0; padding: 0; background-color: {_PAGE_BACKGROUND}; "
    f"font-family: {_FONT_STACK};"
)
_KICKER_STYLE = (
    f"font-size: 13px; letter-spacing: 1.5px; text-transform: uppercase; color: {_FAINT};"
)
_CARD_STYLE = (
    f"background-color: {_CARD_BACKGROUND}; border-radius: 14px; "
    f"border: 1px solid {_BORDER}; padding: 32px;"
)
_CHIP_STYLE = (
    "display: inline-block; padding: 5px 12px; border-radius: 999px; "
    f"background-color: {_ACCENT}; color: #ffffff; font-size: 12px; "
    "font-weight: 600; letter-spacing: 0.3px;"
)
_NAME_STYLE = (
    f"margin: 24px 0 4px; font-size: 19px; font-weight: 700; color: {_FOREGROUND}; "
    "letter-spacing: -0.2px;"
)
_EMAIL_STYLE = f"margin: 0 0 24px; font-size: 14px; color: {_MUTED};"
_RULE_STYLE = f"border-top: 1px solid {_BORDER}; height: 1px; font-size: 0;"
_MESSAGE_STYLE = (
    f"font-size: 15px; line-height: 1.65; color: {_FOREGROUND}; "
    "white-space: pre-wrap; word-break: break-word;"
)
_NOTE_STYLE = f"margin: 0 0 3px; font-size: 12px; color: {_FAINT};"
_NOTE_LAST_STYLE = f"margin: 0; font-size: 12px; color: {_FAINT};"


class MailerNotConfigured(RuntimeError):
    """Raised when the Resend credential or the recipient address is unset."""


class MailerUnavailable(RuntimeError):
    """Raised when Resend cannot be reached, or refuses the message.

    Args:
        reason: One of ``timeout``, ``transport`` or ``upstream``. Carried as an
            attribute so the router can distinguish a timeout from a rejection without
            parsing the message.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _build_bodies(
    *,
    category: str,
    name: str,
    email: str,
    message: str,
    account_id: str | None,
    submitted_at: str,
) -> tuple[str, str]:
    """Render the plain-text and HTML bodies for a submission.

    The two bodies are built from the same values but are **not** escaped alike, and that
    asymmetry is deliberate. The HTML body escapes every interpolated value at the point
    of interpolation; the text body carries them raw. Escaping the text body as well would
    replace a literal ``<`` in a pasted stack trace with ``&lt;``, turning the fallback
    rendering into the confusing one.

    Escaping the HTML is a correctness fix before it is a security one. A bug report
    routinely contains ``<`` and ``>`` -- stack traces, generic types, markup being
    discussed -- and an unescaped one mangles the layout of the very message reporting a
    problem. It is also the difference between a submission that can merely look wrong and
    one that can carry a link rendered under this domain's DKIM signature.

    Args:
        category: Category slug, used only in the heading.
        name: Submitter's name, as typed.
        email: Submitter's address, as typed.
        message: The free-text body, as typed.
        account_id: UUID of the signed-in submitter, or None when anonymous.
        submitted_at: ISO-8601 UTC timestamp of receipt.

    Returns:
        A ``(html, text)`` pair.
    """
    label = _CATEGORY_LABELS.get(category, category)
    account = account_id or "none (anonymous)"

    text = (
        f"New contact form submission\n"
        f"\n"
        f"Category: {label}\n"
        f"Name: {name}\n"
        f"Email: {email}\n"
        f"Authenticated account: {account}\n"
        f"Submitted: {submitted_at}\n"
        f"\n"
        f"---\n"
        f"\n"
        f"{message}\n"
    )

    # Escaped once here so every interpolation below is safe by construction, rather than
    # relying on each of the six call sites remembering to escape.
    safe_label = html.escape(label, quote=True)
    safe_name = html.escape(name, quote=True)
    safe_email = html.escape(email, quote=True)
    safe_message = html.escape(message, quote=True)
    safe_account = html.escape(account, quote=True)
    safe_submitted = html.escape(submitted_at, quote=True)

    # `white-space: pre-wrap` renders the message's newlines without string surgery. The
    # alternative -- escaping and then replacing "\n" with "<br>" -- depends on the two
    # happening in that order, which is exactly the kind of ordering a later edit inverts.
    body = f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  </head>
  <body style="{_BODY_STYLE}">
    <table width="100%" cellpadding="0" cellspacing="0" style="{_PAGE_STYLE}">
      <tr>
        <td align="center">
          <table width="600" cellpadding="0" cellspacing="0" style="max-width: 600px; width: 100%;">
            <tr>
              <td style="padding-bottom: 20px;">
                <span style="{_KICKER_STYLE}">Illume contact</span>
              </td>
            </tr>
            <tr>
              <td style="{_CARD_STYLE}">
                <span style="{_CHIP_STYLE}">{safe_label}</span>
                <p style="{_NAME_STYLE}">{safe_name}</p>
                <p style="{_EMAIL_STYLE}">{safe_email}</p>
                <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 24px;">
                  <tr>
                    <td style="{_RULE_STYLE}">&nbsp;</td>
                  </tr>
                </table>
                <div style="{_MESSAGE_STYLE}">{safe_message}</div>
              </td>
            </tr>
            <tr>
              <td style="padding-top: 18px;">
                <p style="{_NOTE_STYLE}">Authenticated account: {safe_account}</p>
                <p style="{_NOTE_LAST_STYLE}">Received {safe_submitted} &middot; reply to answer</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""

    return body, text


async def send_contact_email(
    *,
    category: str,
    name: str,
    email: str,
    message: str,
    account_id: str | None = None,
) -> None:
    """Deliver one contact-form submission to the operator's inbox.

    Args:
        category: Category slug from the request model.
        name: Submitter's name, as typed. Untrusted.
        email: Submitter's address, as typed. Untrusted, and used verbatim as
            ``Reply-To`` so the operator can answer without copying an address out.
        message: The free-text body. Untrusted, and the most likely carrier of stray
            markup.
        account_id: UUID of the signed-in submitter, taken from the verified session
            token, or None when the visitor was anonymous. Unlike ``email`` this value
            cannot be forged by the submitter.

    Raises:
        MailerNotConfigured: The credential or recipient address is unset.
        MailerUnavailable: Resend timed out, was unreachable, or rejected the message.
    """
    # Read through the settings singleton at call time rather than binding defaults in the
    # signature: `settings` is imported once at module load, so a default argument would
    # freeze the value at import and silently ignore both a restart-free override and a
    # test's monkeypatch.
    api_key = settings.RESEND_API_KEY
    recipient = settings.CONTACT_TO_EMAIL

    if not api_key or not recipient:
        raise MailerNotConfigured(
            "RESEND_API_KEY and CONTACT_TO_EMAIL must both be set to deliver submissions"
        )

    html_body, text_body = _build_bodies(
        category=category,
        name=name,
        email=email,
        message=message,
        account_id=account_id,
        submitted_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )

    payload = {
        "from": settings.CONTACT_FROM_EMAIL,
        "to": [recipient],
        "subject": f"[Illume Contact] {_CATEGORY_LABELS.get(category, category)}",
        "html": html_body,
        "text": text_body,
        "reply_to": email,
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(RESEND_ENDPOINT, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        logger.warning("Resend did not respond within %ss", TIMEOUT)
        raise MailerUnavailable("timeout") from exc
    except httpx.HTTPError as exc:
        # A transport failure produces no response at all, so without this the exception
        # would escape as an opaque 500 -- indistinguishable, to the visitor, from a bug
        # in this application.
        logger.warning("Resend request failed: %s", exc)
        raise MailerUnavailable("transport") from exc

    # Any 2xx counts as delivered. The documented success code is not pinned down, and
    # testing for exactly 200 would reject a 202 that had in fact queued the message.
    if response.status_code >= 400:
        logger.warning(
            "Resend rejected the submission with %d: %s",
            response.status_code,
            response.text[:200],
        )
        raise MailerUnavailable("upstream")
