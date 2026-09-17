"""Progress-log publishing.

The function is best-effort by design: a Redis outage must not fail the analysis task
that is merely reporting on itself. That swallowing behaviour is as important to pin as
the payload shape, because "the logs stopped" should never become "the ingestion died".
"""

import json
import logging
from datetime import datetime
from unittest.mock import Mock

import fakeredis
import pytest

from app.services._publish import publish_log

pytestmark = pytest.mark.unit

REPO_ID = "3f1a8c2e-0000-4000-8000-000000000001"
CHANNEL = f"task:{REPO_ID}:logs"


@pytest.fixture
def redis():
    """
    In-process Redis, configured the way the application configures it.

    `decode_responses=True` matches `app.core.redis.get_sync_redis`. Without it the
    channel and payload come back as bytes and assertions on strings fail for reasons
    that have nothing to do with the code under test.
    """
    return fakeredis.FakeStrictRedis(decode_responses=True)


class TestChannel:
    def test_publishes_to_the_repository_channel(self, redis):
        pubsub = redis.pubsub()
        pubsub.subscribe(CHANNEL)
        pubsub.get_message(timeout=1)  # subscribe confirmation

        publish_log(redis, REPO_ID, "status_update", "hello")

        message = pubsub.get_message(timeout=1, ignore_subscribe_messages=True)
        assert message is not None
        assert message["channel"] == CHANNEL

    def test_channels_are_per_repository(self, redis):
        other_id = "3f1a8c2e-0000-4000-8000-000000000002"
        pubsub = redis.pubsub()
        pubsub.subscribe(f"task:{other_id}:logs")
        pubsub.get_message(timeout=1)

        publish_log(redis, REPO_ID, "status_update", "hello")

        assert pubsub.get_message(timeout=1, ignore_subscribe_messages=True) is None


class TestPayload:
    def test_carries_event_message_and_timestamp(self, redis):
        pubsub = redis.pubsub()
        pubsub.subscribe(CHANNEL)
        pubsub.get_message(timeout=1)

        publish_log(redis, REPO_ID, "glossary_started", "Building project glossary...")

        payload = json.loads(pubsub.get_message(timeout=1, ignore_subscribe_messages=True)["data"])
        assert payload["event"] == "glossary_started"
        assert payload["message"] == "Building project glossary..."
        assert set(payload) == {"event", "message", "timestamp"}

    def test_timestamp_is_parseable_iso8601(self, redis):
        pubsub = redis.pubsub()
        pubsub.subscribe(CHANNEL)
        pubsub.get_message(timeout=1)

        publish_log(redis, REPO_ID, "status_update", "hello")

        payload = json.loads(pubsub.get_message(timeout=1, ignore_subscribe_messages=True)["data"])
        parsed = datetime.fromisoformat(payload["timestamp"])
        assert parsed.tzinfo is not None

    def test_extra_keywords_are_merged(self, redis):
        """The ingestion task uses this to send `status` alongside the message."""
        pubsub = redis.pubsub()
        pubsub.subscribe(CHANNEL)
        pubsub.get_message(timeout=1)

        publish_log(redis, REPO_ID, "status_update", "done", status="ready")

        payload = json.loads(pubsub.get_message(timeout=1, ignore_subscribe_messages=True)["data"])
        assert payload["status"] == "ready"

    def test_payload_is_json_serializable_with_nested_values(self, redis):
        pubsub = redis.pubsub()
        pubsub.subscribe(CHANNEL)
        pubsub.get_message(timeout=1)

        publish_log(redis, REPO_ID, "status_update", "done", detail={"files": 3, "nested": [1, 2]})

        payload = json.loads(pubsub.get_message(timeout=1, ignore_subscribe_messages=True)["data"])
        assert payload["detail"] == {"files": 3, "nested": [1, 2]}


class TestFailureIsSwallowed:
    def test_a_broken_client_does_not_raise(self):
        """
        The whole point of the try/except. If this raises, a Redis blip aborts ingestion
        instead of just losing a progress line.
        """
        broken = Mock()
        broken.publish.side_effect = ConnectionError("redis is down")

        publish_log(broken, REPO_ID, "status_update", "hello")  # must not raise

    def test_a_broken_client_is_logged_as_a_warning(self, caplog):
        broken = Mock()
        broken.publish.side_effect = ConnectionError("redis is down")

        with caplog.at_level(logging.WARNING):
            publish_log(broken, REPO_ID, "status_update", "hello")

        assert any(record.levelno == logging.WARNING for record in caplog.records)
        assert CHANNEL in caplog.text

    def test_a_serialization_failure_does_not_raise(self, redis):
        """A non-serializable kwarg must degrade to a lost log, not a failed task."""
        publish_log(redis, REPO_ID, "status_update", "hello", bad=object())

    def test_success_logs_at_info(self, redis, caplog):
        with caplog.at_level(logging.INFO):
            publish_log(redis, REPO_ID, "status_update", "hello")

        assert "status_update" in caplog.text
