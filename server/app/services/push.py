"""Push notifications for the native client.

The mobile app registers the Expo push token of every device it runs on, and
the server decides -- here, in one place -- which events are worth a
notification. The decision cannot live in the client: only the server knows
whether an update was one the user asked for or one the auto-update sweep
picked up on schedule, and that difference is the whole point.

A repository syncs every six hours by default, so a routine refresh that
pinged the phone would train people to turn notifications off. A scheduled
sync is therefore silent in both directions, and a failed one is left to the
settings panel: the repository keeps the last analysis it produced, which is
still valid, and ``sync_status`` is already polled there.

:func:`should_notify` is that decision, and nothing else -- no database, no
network, no clock -- so it can be checked exhaustively. The rest of the
module is delivery, which is best-effort by design: the analysis is already
committed by the time a push goes out, and losing an ingestion because a
third-party API was unreachable would be a far worse outcome than a missing
notification.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from enum import StrEnum

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_sync_db
from app.models.push_token import PushToken

logger = logging.getLogger(__name__)

EXPO_PUSH_ENDPOINT = "https://exp.host/--/api/v2/push/send"
PUSH_TIMEOUT_SECONDS = 10.0


class NotifyEvent(StrEnum):
    """Something that happened to a repository which may deserve a push.

    A ``StrEnum`` so the value serialises as a bare string in the payload
    delivered to the device, matching the progress-stream enums in
    :mod:`app.services._stages`.
    """

    INGEST_COMPLETED = "ingest_completed"
    INGEST_FAILED = "ingest_failed"
    MANUAL_SYNC_COMPLETED = "manual_sync_completed"
    MANUAL_SYNC_FAILED = "manual_sync_failed"
    SCHEDULED_SYNC_COMPLETED = "scheduled_sync_completed"
    SCHEDULED_SYNC_FAILED = "scheduled_sync_failed"


#: The events that produce a push. Everything outside this set is silent.
#:
#: A scheduled sync is not here in either of its outcomes. The routine
#: refresh is too frequent to be worth interrupting anyone for, and its
#: failure is not a broken state: the repository keeps its previous analysis
#: and the settings panel shows the error.
NOTIFYING_EVENTS = frozenset(
    {
        NotifyEvent.INGEST_COMPLETED,
        NotifyEvent.INGEST_FAILED,
        NotifyEvent.MANUAL_SYNC_COMPLETED,
        NotifyEvent.MANUAL_SYNC_FAILED,
    }
)


def should_notify(event: NotifyEvent) -> bool:
    """
    Whether an event deserves a push notification.

    Args:
        event: What happened.

    Returns:
        True when the event should produce a push, False when it should be
        silent.
    """
    return event in NOTIFYING_EVENTS


def sync_event(*, manual: bool, failed: bool) -> NotifyEvent:
    """
    The event a finished sync produced.

    Args:
        manual: Whether the user asked for this sync, as opposed to the
            auto-update sweep picking the repository up on schedule.
        failed: Whether the sync failed.

    Returns:
        The event describing the outcome.
    """
    if manual:
        return NotifyEvent.MANUAL_SYNC_FAILED if failed else NotifyEvent.MANUAL_SYNC_COMPLETED
    return NotifyEvent.SCHEDULED_SYNC_FAILED if failed else NotifyEvent.SCHEDULED_SYNC_COMPLETED


# The title and body shown for each event. The body is rendered with the
# repository's name substituted in.
_MESSAGES: dict[NotifyEvent, tuple[str, str]] = {
    NotifyEvent.INGEST_COMPLETED: (
        "Ingestion complete",
        "{name} is ready to explore.",
    ),
    NotifyEvent.INGEST_FAILED: (
        "Ingestion failed",
        "{name} could not be analysed. Open the app to try again.",
    ),
    NotifyEvent.MANUAL_SYNC_COMPLETED: (
        "Update complete",
        "{name} is up to date.",
    ),
    NotifyEvent.MANUAL_SYNC_FAILED: (
        "Update failed",
        "{name} could not be updated. The previous analysis is still available.",
    ),
    NotifyEvent.SCHEDULED_SYNC_COMPLETED: (
        "Update complete",
        "{name} is up to date.",
    ),
    NotifyEvent.SCHEDULED_SYNC_FAILED: (
        "Update failed",
        "{name} could not be updated. The previous analysis is still available.",
    ),
}


def _message_for(event: NotifyEvent, repository_name: str) -> tuple[str, str]:
    """
    The title and body shown for an event.

    Args:
        event: What happened.
        repository_name: The repository's name.

    Returns:
        A ``(title, body)`` pair.
    """
    title, template = _MESSAGES[event]
    return title, template.format(name=repository_name)


def _expo_message(token: str, *, title: str, body: str, data: dict[str, str]) -> dict:
    """
    Build one Expo push message.

    Args:
        token: The device's Expo push token.
        title: Notification title.
        body: Notification body.
        data: Extra data delivered with the notification. Expo requires
            every value to be a string.

    Returns:
        The message as Expo expects it.
    """
    return {
        "to": token,
        "title": title,
        "body": body,
        "sound": "default",
        "data": data,
    }


def _tokens_for(user_id: uuid.UUID) -> list[str]:
    """
    The Expo tokens registered for a user.

    Args:
        user_id: The user to read the tokens of.

    Returns:
        The token strings, in no particular order.
    """
    db = next(get_sync_db())
    try:
        rows = db.query(PushToken).filter(PushToken.user_id == user_id).all()
        return [row.token for row in rows]
    finally:
        db.close()


def _post_expo(messages: list[dict]) -> httpx.Response:
    """
    Post a batch of messages to Expo.

    Args:
        messages: The messages to deliver.

    Returns:
        The response, successful or not.

    Raises:
        httpx.HTTPError: If Expo could not be reached.
    """
    with httpx.Client(timeout=PUSH_TIMEOUT_SECONDS) as client:
        return client.post(
            EXPO_PUSH_ENDPOINT,
            json=messages,
            headers={"Accept": "application/json"},
        )


def _dead_tokens(response: httpx.Response, tokens: list[str]) -> list[str]:
    """
    The tokens Expo reported as no longer registered.

    Expo answers a batch send with one entry per message, in the order the
    messages were sent, so an entry's position identifies the token it is
    about. Only ``DeviceNotRegistered`` is treated as dead: the device was
    uninstalled, or the token was replaced, and no push will ever reach it
    again.

    Args:
        response: The response to the batch send.
        tokens: The tokens that were sent, in order.

    Returns:
        The tokens that should be dropped.
    """
    try:
        payload = response.json()
    except ValueError:
        return []

    entries = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return []

    dead: list[str] = []
    for index, entry in enumerate(entries):
        if index >= len(tokens) or not isinstance(entry, dict):
            continue
        if entry.get("status") != "error":
            continue
        details = entry.get("details")
        if isinstance(details, dict) and details.get("error") == "DeviceNotRegistered":
            dead.append(tokens[index])
    return dead


def _forget_tokens(user_id: uuid.UUID, tokens: list[str]) -> None:
    """
    Remove tokens Expo reported as dead.

    Leaving them behind would make the registration endpoint answer "yes,
    you are registered" for a device that can no longer be reached, and the
    client would then never re-register.

    Args:
        user_id: The owner of the tokens.
        tokens: The tokens to remove.
    """
    if not tokens:
        return
    db = next(get_sync_db())
    try:
        db.query(PushToken).filter(
            PushToken.user_id == user_id,
            PushToken.token.in_(tokens),
        ).delete(synchronize_session=False)
        db.commit()
        logger.info("Dropped %s push token(s) Expo no longer recognises", len(tokens))
    except Exception:
        db.rollback()
        logger.warning("Could not drop the dead push tokens", exc_info=True)
    finally:
        db.close()


def send_push_to_user(
    user_id: uuid.UUID,
    *,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> bool:
    """
    Send a push to every device registered for a user.

    Best-effort: a failure here is logged and swallowed, because the caller
    is a background task whose real work is already done.

    Args:
        user_id: The user to notify.
        title: Notification title.
        body: Notification body.
        data: Extra data delivered with the notification. Expo requires every
            value to be a string.

    Returns:
        True when Expo accepted at least one message, False when it accepted
        none -- including when the user has no registered device.
    """
    payload = dict(data or {})
    try:
        tokens = _tokens_for(user_id)
        if not tokens:
            return False
        messages = [_expo_message(token, title=title, body=body, data=payload) for token in tokens]
        response = _post_expo(messages)
    except Exception as exc:
        logger.warning("Could not send a push to user %s: %s", user_id, exc)
        return False

    if response.status_code >= 400:
        logger.warning(
            "Expo rejected the push with %d: %s",
            response.status_code,
            response.text[:200],
        )
        return False

    _forget_tokens(user_id, _dead_tokens(response, tokens))
    return True


def notify_user(
    user_id: uuid.UUID,
    event: NotifyEvent,
    *,
    repository_id: uuid.UUID,
    repository_number: int | None,
    repository_name: str,
) -> bool:
    """
    Tell a user about an event, if the event deserves it.

    The decision is :func:`should_notify`'s; this function only carries it
    out, so the caller states *what happened* and never has to know which
    events are quiet.

    Args:
        user_id: The user to notify.
        event: What happened.
        repository_id: The repository the event is about, for deep linking.
        repository_number: The repository's user-facing number, for deep
            linking.
        repository_name: The repository's name, for the message text.

    Returns:
        True when a push was sent, False when the event was silent or the
        delivery failed.
    """
    if not should_notify(event):
        return False

    title, body = _message_for(event, repository_name)
    data = {
        "event": event.value,
        "repository_id": str(repository_id),
        "repository_number": "" if repository_number is None else str(repository_number),
        "repository_name": repository_name,
    }
    return send_push_to_user(user_id, title=title, body=body, data=data)


async def register_push_token(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    token: str,
    platform: str,
) -> PushToken:
    """
    Register a device's push token, or refresh the one already stored.

    A device that registers twice keeps one row: the second registration
    updates the platform and the timestamp rather than adding a duplicate.

    A token that already belongs to somebody else is taken over rather than
    rejected. The token belongs to the device, not to the account, and a
    device that signed out of one account and into another has to be able to
    move its token across -- otherwise the previous account would keep
    receiving notifications for a phone that is no longer signed in to it.

    Args:
        db: Async database session.
        user_id: The user the token belongs to.
        token: The device's Expo push token.
        platform: The device's platform, ``android`` or ``ios``.

    Returns:
        The stored row.
    """
    result = await db.execute(select(PushToken).where(PushToken.token == token))
    row = result.scalar_one_or_none()

    if row is None:
        row = PushToken(user_id=user_id, token=token, platform=platform)
        db.add(row)
    else:
        row.user_id = user_id
        row.platform = platform
        row.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(row)
    return row


async def remove_push_token(db: AsyncSession, *, user_id: uuid.UUID, token: str) -> bool:
    """
    Remove one of a user's push tokens.

    Only the token named is removed, and only when it belongs to the user
    asking: a device signing out takes its own registration with it and
    leaves the user's other devices registered.

    Args:
        db: Async database session.
        user_id: The user the token must belong to.
        token: The token to remove.

    Returns:
        True when a token was removed, False when there was nothing to
        remove.
    """
    result = await db.execute(
        select(PushToken).where(PushToken.user_id == user_id, PushToken.token == token)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


async def list_push_tokens(db: AsyncSession, *, user_id: uuid.UUID) -> list[PushToken]:
    """
    The push tokens registered for a user.

    Args:
        db: Async database session.
        user_id: The user to read the tokens of.

    Returns:
        The stored rows.
    """
    result = await db.execute(select(PushToken).where(PushToken.user_id == user_id))
    return list(result.scalars().all())
