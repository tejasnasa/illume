"""The push-notification decision, and the delivery that follows it.

The decision is the part worth pinning: it decides whether a phone is
interrupted, and it is a pure function of what happened. The client cannot
make it -- only the server knows whether an update was one the user asked
for or one the auto-update sweep picked up -- so the rules live here and are
checked exhaustively, one case per event.

The delivery is best-effort by design, and that is worth pinning too: a push
that cannot be sent must not fail the ingestion that produced it.
"""

import json
import uuid

import httpx
import pytest
import respx

from app.services import push
from app.services.push import (
    EXPO_PUSH_ENDPOINT,
    NotifyEvent,
    should_notify,
    sync_event,
)

pytestmark = pytest.mark.unit

TOKEN = "ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]"


@pytest.fixture
def registered(monkeypatch):
    """A user with one registered device, and no database behind it."""

    def _register(user_id):
        return [TOKEN]

    monkeypatch.setattr(push, "_tokens_for", _register)
    return _register


class TestShouldNotify:
    """Which events are worth interrupting somebody for."""

    def test_a_completed_ingest_notifies(self):
        assert should_notify(NotifyEvent.INGEST_COMPLETED) is True

    def test_a_failed_ingest_notifies(self):
        assert should_notify(NotifyEvent.INGEST_FAILED) is True

    def test_a_completed_manual_sync_notifies(self):
        assert should_notify(NotifyEvent.MANUAL_SYNC_COMPLETED) is True

    def test_a_failed_manual_sync_notifies(self):
        assert should_notify(NotifyEvent.MANUAL_SYNC_FAILED) is True

    def test_a_completed_scheduled_sync_is_silent(self):
        """
        A repository syncs every six hours by default. Pinging the phone for
        each of those would train people to turn notifications off.
        """
        assert should_notify(NotifyEvent.SCHEDULED_SYNC_COMPLETED) is False

    def test_a_failed_scheduled_sync_is_silent(self):
        """
        A failed scheduled sync is not a broken state: the repository keeps
        the analysis it already had, and the settings panel polls
        ``sync_status`` for the outcome.
        """
        assert should_notify(NotifyEvent.SCHEDULED_SYNC_FAILED) is False

    def test_the_notifying_events_are_exactly_these(self):
        """
        The whole rule, in one assertion.

        A new event has to be given a decision rather than inherit one by
        accident, so the set of notifying events is pinned exactly: adding
        an event to the enum without deciding about it fails here.
        """
        notifying = {event for event in NotifyEvent if should_notify(event)}

        assert notifying == {
            NotifyEvent.INGEST_COMPLETED,
            NotifyEvent.INGEST_FAILED,
            NotifyEvent.MANUAL_SYNC_COMPLETED,
            NotifyEvent.MANUAL_SYNC_FAILED,
        }

    def test_the_decision_does_nothing(self, monkeypatch):
        """
        The decision is pure: no database, no network, no clock.

        That is what makes it checkable -- and it is also what keeps it from
        being able to fail a task it is only supposed to advise.
        """

        def explode(*args, **kwargs):
            raise AssertionError("should_notify must not do any work")

        monkeypatch.setattr(push, "_tokens_for", explode)
        monkeypatch.setattr(push, "_post_expo", explode)

        assert should_notify(NotifyEvent.INGEST_COMPLETED) is True
        assert should_notify(NotifyEvent.SCHEDULED_SYNC_COMPLETED) is False


class TestSyncEvent:
    """The event a finished sync produced, given who asked for it."""

    def test_a_manual_sync_that_succeeded(self):
        assert sync_event(manual=True, failed=False) is NotifyEvent.MANUAL_SYNC_COMPLETED

    def test_a_manual_sync_that_failed(self):
        assert sync_event(manual=True, failed=True) is NotifyEvent.MANUAL_SYNC_FAILED

    def test_a_scheduled_sync_that_succeeded(self):
        assert sync_event(manual=False, failed=False) is NotifyEvent.SCHEDULED_SYNC_COMPLETED

    def test_a_scheduled_sync_that_failed(self):
        assert sync_event(manual=False, failed=True) is NotifyEvent.SCHEDULED_SYNC_FAILED

    def test_only_a_manual_sync_notifies(self):
        """The combination the rules are about, in one place."""
        notifying = {
            sync_event(manual=manual, failed=failed)
            for manual in (True, False)
            for failed in (True, False)
            if should_notify(sync_event(manual=manual, failed=failed))
        }

        assert notifying == {
            NotifyEvent.MANUAL_SYNC_COMPLETED,
            NotifyEvent.MANUAL_SYNC_FAILED,
        }


class TestWhichSyncsNotify:
    """How the sync task tells a requested sync from a scheduled one.

    The task is dispatched by two callers with different shapes: the route
    the user hits, and the auto-update sweep. The sweep hands the task the
    owner's GitHub token because it has to clone with it; the route has the
    user's session and passes nothing. The row the user asked to sync is
    also marked ``queued``, which the sweep never does.
    """

    def test_the_route_dispatches_without_the_owner_token(self):
        from app.tasks.sync import _requested_by_user

        assert _requested_by_user(("repo-id",), {}, "idle") is True

    def test_the_sweep_dispatches_with_the_owner_token(self):
        from app.tasks.sync import _requested_by_user

        assert _requested_by_user(("repo-id", "gh-token"), {}, "idle") is False

    def test_a_queued_row_means_the_user_asked(self):
        from app.tasks.sync import _requested_by_user

        assert _requested_by_user(("repo-id", "gh-token"), {}, "queued") is True

    def test_a_keyword_argument_means_the_token_was_supplied(self):
        from app.tasks.sync import _requested_by_user

        assert _requested_by_user(("repo-id",), {"access_token": "gh"}, "idle") is False


class TestDelivery:
    """Sending a push, and what happens when it cannot be sent."""

    @respx.mock
    def test_a_successful_send_reaches_expo(self, registered):
        route = respx.post(EXPO_PUSH_ENDPOINT).mock(
            return_value=httpx.Response(200, json={"data": [{"status": "ok", "id": "1"}]})
        )
        user_id = uuid.uuid4()

        sent = push.send_push_to_user(user_id, title="Ingestion complete", body="Ready.")

        assert sent is True
        assert route.call_count == 1
        assert json.loads(route.calls.last.request.content)[0]["to"] == TOKEN

    @respx.mock
    def test_a_transport_failure_does_not_raise(self, registered):
        """
        The headline robustness property: the caller is a background task
        whose analysis is already committed, and a push that cannot be
        delivered must not fail it.
        """
        respx.post(EXPO_PUSH_ENDPOINT).mock(side_effect=httpx.ConnectError("expo is down"))
        user_id = uuid.uuid4()

        assert push.send_push_to_user(user_id, title="t", body="b") is False

    @respx.mock
    def test_a_rejected_push_does_not_raise(self, registered):
        respx.post(EXPO_PUSH_ENDPOINT).mock(return_value=httpx.Response(500, text="nope"))
        user_id = uuid.uuid4()

        assert push.send_push_to_user(user_id, title="t", body="b") is False

    @respx.mock
    def test_a_malformed_response_does_not_raise(self, registered):
        respx.post(EXPO_PUSH_ENDPOINT).mock(return_value=httpx.Response(200, text="not json"))
        user_id = uuid.uuid4()

        assert push.send_push_to_user(user_id, title="t", body="b") is True

    @respx.mock
    def test_a_user_without_a_device_is_not_sent_to(self, monkeypatch):
        monkeypatch.setattr(push, "_tokens_for", lambda user_id: [])
        route = respx.post(EXPO_PUSH_ENDPOINT).mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        assert push.send_push_to_user(uuid.uuid4(), title="t", body="b") is False
        assert route.call_count == 0

    @respx.mock
    def test_the_payload_carries_the_repository_identity(self, registered):
        """
        The client deep-links to the repository from the notification, so the
        payload has to name it -- by both id and number, because the routes
        are keyed on one and the other.
        """
        route = respx.post(EXPO_PUSH_ENDPOINT).mock(
            return_value=httpx.Response(200, json={"data": [{"status": "ok", "id": "1"}]})
        )
        repository_id = uuid.uuid4()

        push.notify_user(
            uuid.uuid4(),
            NotifyEvent.INGEST_COMPLETED,
            repository_id=repository_id,
            repository_number=42,
            repository_name="demo-repo",
        )

        message = json.loads(route.calls.last.request.content)[0]
        assert message["data"]["repository_id"] == str(repository_id)
        assert message["data"]["repository_number"] == "42"
        assert message["data"]["repository_name"] == "demo-repo"
        assert message["data"]["event"] == "ingest_completed"
        assert message["title"] == "Ingestion complete"
        assert "demo-repo" in message["body"]

    @respx.mock
    def test_a_silent_event_sends_nothing(self, monkeypatch):
        """The scheduled events never reach Expo, not even to be dropped."""
        route = respx.post(EXPO_PUSH_ENDPOINT).mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        for event in (NotifyEvent.SCHEDULED_SYNC_COMPLETED, NotifyEvent.SCHEDULED_SYNC_FAILED):
            sent = push.notify_user(
                uuid.uuid4(),
                event,
                repository_id=uuid.uuid4(),
                repository_number=1,
                repository_name="demo-repo",
            )
            assert sent is False

        assert route.call_count == 0
