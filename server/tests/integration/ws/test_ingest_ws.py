"""The ingestion log WebSocket.

Two styles of test, deliberately:

* **Through the ASGI stack** (`TestClient.websocket_connect`) for the handshake and the
  rejection paths that never reach the database. This proves the route is mounted at
  `/api/v1/ws/ingest/{repo_id}` with the close codes clients rely on.
* **By driving the handler directly** for everything past the ownership check. Those paths
  need the request's database session, and `TestClient` runs the app on its own event loop
  while the test session is bound to pytest-asyncio's -- so an ASGI-level test there would
  fail on a cross-loop connection rather than on anything the route does.

The relay is exercised against the **real** Redis from `docker-compose.test.yml`: pub/sub
has no faithful in-process stand-in, and the property under test is that a message
published on the channel reaches the socket.
"""

import asyncio
import json
import uuid
from typing import Any, cast

import pytest
from starlette.testclient import TestClient

from app.core.security import create_access_token
from tests.factories import make_ingested_repo, make_user

pytestmark = pytest.mark.integration


def channel_for(repo_id) -> str:
    return f"task:{repo_id}:logs"


def log_frame(message: str = "working", event: str = "log") -> str:
    """A frame in the shape the ingestion task actually publishes."""
    import json

    return json.dumps(
        {
            "event": event,
            "message": message,
            "timestamp": "2026-01-01T00:00:00+00:00",
        }
    )


def done_frame() -> str:
    """The completion marker, exactly as `ingest.py` emits it."""
    return log_frame("DONE", event="done")


def error_frame() -> str:
    return log_frame("ERROR", event="error")


class FakeWebSocket:
    """
    A WebSocket that records what the handler did to it.

    Starlette's own test socket drives a full ASGI exchange, which is more than is needed
    here and brings the event-loop problem described in the module docstring. What the
    handler actually touches is `accept`, `close`, `send_text`, and two attribute reads.
    """

    def __init__(self, *, cookies=None, query_params=None):
        self.cookies = cookies or {}
        self.query_params = query_params or {}
        self.accepted = False
        self.sent: list[str] = []
        self.close_code: int | None = None
        self.close_reason: str | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.close_code = code
        self.close_reason = reason

    async def send_text(self, data: str) -> None:
        self.sent.append(data)


async def wait_for_subscribers(redis_client, channel: str, *, timeout: float = 5.0) -> None:
    """
    Block until the handler has actually subscribed.

    Redis pub/sub does not buffer: a message published before the subscription exists is
    lost outright. Sleeping would be flaky in both directions, so this polls the server's
    own subscriber count instead.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        counts = await redis_client.pubsub_numsub(channel)
        if counts and counts[0][1] > 0:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"nothing subscribed to {channel!r} within {timeout}s")


async def subscriber_count(redis_client, channel: str) -> int:
    counts = await redis_client.pubsub_numsub(channel)
    return counts[0][1] if counts else 0


async def reject(repo_id, *, cookies=None, query_params=None, db) -> FakeWebSocket:
    """
    Drive the handler on a path that returns early.

    Safe to await directly: every rejection happens before the relay loop is entered, so
    nothing blocks on an empty channel.
    """
    from app.api.v1.ws import ingest_ws

    socket = FakeWebSocket(cookies=cookies, query_params=query_params)
    # `FakeWebSocket` implements the handful of members the handler touches rather than
    # subclassing FastAPI's `WebSocket`, so it is cast at the one boundary where the real
    # type is required. See the class docstring for what it deliberately does not model.
    await asyncio.wait_for(ingest_ws(cast(Any, socket), repo_id, db), timeout=10)
    return socket


async def wait_for_frames(socket, count: int, *, timeout: float = 5.0) -> None:
    """
    Block until the socket has forwarded `count` frames.

    The handler runs concurrently, so the alternative is a sleep -- which is either flaky
    or wasteful, and says nothing about what it was actually waiting for.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if len(socket.sent) >= count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"wanted {count} frames, saw {len(socket.sent)}: {socket.sent!r}")


async def wait_for_no_subscribers(redis_client, channel: str, *, timeout: float = 5.0) -> None:
    """
    Block until the channel has no subscribers left.

    Polled rather than asserted once, because Redis updates its subscriber registry
    asynchronously: a single check immediately after an `UNSUBSCRIBE` can still read the
    old count, which would look like a leak that is not there.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if await subscriber_count(redis_client, channel) == 0:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"{channel!r} still has subscribers after {timeout}s")


async def relay(user, repo_id, db, redis_client, messages):
    """
    Authenticate, let the handler subscribe, publish `messages`, and return the socket.

    Run as a task because the handler blocks on `pubsub.listen()` -- publishing has to
    happen while it is listening, and the subscription is awaited rather than slept on.

    The task is cancelled once the frames have arrived. Waiting for it to finish instead
    would not work: the handler compares frames against a bare `DONE`, which nothing ever
    publishes, and `wait_for` cannot bound it either -- the handler absorbs the
    cancellation, so it would sit for the whole timeout and then return as though it had
    completed. `ended_by_itself` below is the helper that actually tests whether the
    stream closes.
    """
    from app.api.v1.ws import ingest_ws

    socket = FakeWebSocket(cookies={"access_token": create_access_token(subject=str(user.id))})
    task = asyncio.create_task(ingest_ws(cast(Any, socket), repo_id, db))
    try:
        await wait_for_subscribers(redis_client, channel_for(repo_id))
        for message in messages:
            await redis_client.publish(channel_for(repo_id), message)
        await wait_for_frames(socket, len(messages))
    finally:
        await _cancel(task)
        # The handler unsubscribes in its `finally`; let that land before the next test.
        await wait_for_no_subscribers(redis_client, channel_for(repo_id))

    return socket


async def _cancel(task) -> None:
    """Stop a task, tolerating that this handler may absorb the cancellation."""
    if task.done():
        return
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=5)
    except TimeoutError, asyncio.CancelledError:
        pass


async def ended_by_itself(user, repo_id, db, redis_client, messages, *, grace: float = 2.0):
    """
    Publish `messages` and report whether the handler stopped on its own.

    Returns `(socket, closed)`. `closed` is decided by whether the task finished within a
    short grace period -- deliberately *not* by awaiting it to completion, because the
    handler swallows `CancelledError`, so `wait_for` returns normally after its full
    timeout whether or not anything closed the stream. Awaiting it would make every
    "does the marker end the stream?" test pass for the wrong reason.
    """
    from app.api.v1.ws import ingest_ws

    socket = FakeWebSocket(cookies={"access_token": create_access_token(subject=str(user.id))})
    task = asyncio.create_task(ingest_ws(cast(Any, socket), repo_id, db))
    try:
        await wait_for_subscribers(redis_client, channel_for(repo_id))
        for message in messages:
            await redis_client.publish(channel_for(repo_id), message)

        done, _ = await asyncio.wait({task}, timeout=grace)
        closed = task in done
        if not closed:
            await wait_for_frames(socket, len(messages))
    finally:
        await _cancel(task)
        await wait_for_no_subscribers(redis_client, channel_for(repo_id))

    return socket, closed


@pytest.fixture(autouse=True)
async def clean_redis(redis_client):
    """Drop leftover state so one test's messages cannot be read as another's."""
    await redis_client.flushdb()
    yield
    await redis_client.flushdb()


class TestHandshakeThroughAsgi:
    """The route is reachable and rejects before touching the database."""

    def test_the_socket_is_mounted(self, app):
        with TestClient(app).websocket_connect(f"/api/v1/ws/ingest/{uuid.uuid4()}") as socket:
            # The handler accepts first and rejects second, so the close arrives as a
            # frame rather than as a refused handshake.
            assert socket.receive()["type"] == "websocket.close"

    def test_no_token_closes_with_1008(self, app):
        with TestClient(app).websocket_connect(f"/api/v1/ws/ingest/{uuid.uuid4()}") as socket:
            frame = socket.receive()

        assert frame["type"] == "websocket.close"
        assert frame["code"] == 1008

    def test_a_garbage_token_closes_with_1008(self, app):
        with TestClient(app).websocket_connect(
            f"/api/v1/ws/ingest/{uuid.uuid4()}?token=not-a-jwt"
        ) as socket:
            frame = socket.receive()

        assert frame["type"] == "websocket.close"
        assert frame["code"] == 1008

    def test_a_token_signed_with_another_key_closes_with_1008(self, app):
        from jose import jwt

        forged = jwt.encode({"sub": str(uuid.uuid4())}, "the-wrong-key", algorithm="HS256")

        with TestClient(app).websocket_connect(
            f"/api/v1/ws/ingest/{uuid.uuid4()}?token={forged}"
        ) as socket:
            frame = socket.receive()

        assert frame["code"] == 1008

    def test_an_expired_token_closes_with_1008(self, app):
        from datetime import timedelta

        expired = create_access_token(
            subject=str(uuid.uuid4()), expires_delta=timedelta(seconds=-60)
        )

        with TestClient(app).websocket_connect(
            f"/api/v1/ws/ingest/{uuid.uuid4()}?token={expired}"
        ) as socket:
            frame = socket.receive()

        assert frame["code"] == 1008

    def test_a_malformed_repo_id_is_rejected(self, app):
        """`repo_id: uuid.UUID` is validated by the router, before the handler runs."""
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as caught:
            with TestClient(app).websocket_connect("/api/v1/ws/ingest/not-a-uuid"):
                pass

        assert caught.value.code == 1008


class TestAuthenticationDirect:
    """The rejection paths past the handshake, which need the test's database session."""

    async def test_no_token_at_all(self, db_session):
        socket = await reject(uuid.uuid4(), db=db_session)

        assert socket.accepted is True  # accepted first, then closed
        assert socket.close_code == 1008
        assert socket.close_reason == "Not authenticated"

    async def test_an_invalid_token(self, db_session):
        socket = await reject(uuid.uuid4(), cookies={"access_token": "not-a-jwt"}, db=db_session)

        assert socket.close_code == 1008
        assert socket.close_reason == "Invalid token"

    async def test_another_users_repository(self, db_session):
        mine = await make_user(db_session)
        theirs = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, theirs)

        socket = await reject(
            repo.id,
            cookies={"access_token": create_access_token(subject=str(mine.id))},
            db=db_session,
        )

        assert socket.close_code == 1008
        assert "access denied" in socket.close_reason.lower()

    async def test_an_unknown_repository(self, db_session):
        user = await make_user(db_session)

        socket = await reject(
            uuid.uuid4(),
            cookies={"access_token": create_access_token(subject=str(user.id))},
            db=db_session,
        )

        assert socket.close_code == 1008

    async def test_a_token_for_a_deleted_user(self, db_session):
        """A token outliving its account must be refused, not resolve to a stale owner."""
        socket = await reject(
            uuid.uuid4(),
            cookies={"access_token": create_access_token(subject=str(uuid.uuid4()))},
            db=db_session,
        )

        assert socket.close_code == 1008

    async def test_no_rejection_logs_the_token(self, db_session, caplog):
        """
        The failed-auth path must not write the credential anywhere. It used to log the
        full JWT on a path an attacker can trigger repeatedly.
        """
        secret = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.distinctive-payload.signature"

        with caplog.at_level("DEBUG"):
            await reject(uuid.uuid4(), cookies={"access_token": secret}, db=db_session)

        assert secret not in caplog.text


class TestQueryParamFallback:
    """
    The `?token=` route is live behaviour, covered because it exists rather than because
    it is desirable -- a JWT in a URL leaks into every access log along the path.
    """

    async def test_a_query_param_token_authenticates(self, db_session, redis_client):
        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)
        token = create_access_token(subject=str(user.id))

        from app.api.v1.ws import ingest_ws

        socket = FakeWebSocket(query_params={"token": token})
        task = asyncio.create_task(ingest_ws(socket, repo.id, db_session))
        try:
            await wait_for_subscribers(redis_client, channel_for(repo.id))
            await redis_client.publish(channel_for(repo.id), "DONE")
            await asyncio.wait_for(task, timeout=10)
        finally:
            if not task.done():
                task.cancel()

        assert socket.close_code is None
        assert socket.sent == ["DONE"]

    async def test_the_cookie_wins_over_the_query_param(self, db_session, redis_client):
        """
        A valid cookie takes precedence, so a stale `?token=` in a bookmarked or shared
        URL cannot override the current session.
        """
        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)

        from app.api.v1.ws import ingest_ws

        socket = FakeWebSocket(
            cookies={"access_token": create_access_token(subject=str(user.id))},
            query_params={"token": "garbage"},
        )
        task = asyncio.create_task(ingest_ws(socket, repo.id, db_session))
        try:
            await wait_for_subscribers(redis_client, channel_for(repo.id))
            await redis_client.publish(channel_for(repo.id), "DONE")
            await asyncio.wait_for(task, timeout=10)
        finally:
            if not task.done():
                task.cancel()

        assert socket.close_code is None


class TestRelay:
    async def test_relays_every_message_in_order(self, db_session, redis_client):
        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)
        frames = [log_frame(f"step {i}") for i in range(3)]

        socket = await relay(user, repo.id, db_session, redis_client, frames)

        assert socket.sent == frames

    async def test_a_completion_frame_is_relayed(self, db_session, redis_client):
        """
        The completion event is forwarded like any other -- the socket does not filter it.
        Whether it *ends* the stream is a separate question, and one the socket currently
        gets wrong; see `TestTerminalMarker`.
        """
        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)

        socket = await relay(
            user, repo.id, db_session, redis_client, [log_frame("working"), done_frame()]
        )

        assert socket.sent[-1] == done_frame()

    async def test_payloads_are_relayed_verbatim(self, db_session, redis_client):
        """Frames are passed through as raw text, not parsed and re-encoded."""
        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)
        payload = json.dumps({"event": "progress", "message": "finished", "pct": 100})

        socket = await relay(user, repo.id, db_session, redis_client, [payload])

        assert socket.sent[0] == payload

    async def test_it_listens_only_to_its_own_channel(self, db_session, redis_client):
        """Two concurrent ingests must not cross-talk."""
        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)
        other, _ = await make_ingested_repo(db_session, user, name="other")
        assert other.id != repo.id

        await redis_client.publish(channel_for(other.id), log_frame("belongs to the other repo"))

        socket = await relay(user, repo.id, db_session, redis_client, [log_frame("mine")])

        assert socket.sent == [log_frame("mine")]

    async def test_a_malformed_payload_is_forwarded_unchanged(self, db_session, redis_client):
        """The relay does not parse frames, so it cannot reject one."""
        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)

        socket = await relay(user, repo.id, db_session, redis_client, ["{not json"])

        assert socket.sent == ["{not json"]

    async def test_a_bare_string_marker_does_end_the_stream(self, db_session, redis_client):
        """
        The counterpart to `TestTerminalMarker`, and the reason the mismatch is invisible
        from this side: the break condition itself works. `ws.py` matches a bare `DONE`,
        so if one were ever published the stream would close. Nothing ever publishes one.

        This also demonstrates that `ended_by_itself` can detect a closed stream, so its
        failures above are about the marker's shape rather than about the detector.
        """
        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)

        socket, closed = await ended_by_itself(user, repo.id, db_session, redis_client, ["DONE"])

        assert socket.sent == ["DONE"]
        assert closed


class TestTerminalMarker:
    """
    The publisher and the consumer disagree on the shape of the completion marker.

    `ingest.py` publishes through a helper that JSON-encodes every event, so the frame is
    `{"event": "done", "message": "DONE", ...}`. `ws.py` compares the whole frame against
    the bare string `"DONE"`, which can never be true. The client makes the same
    comparison on the same value.
    """

    async def test_the_task_publishes_a_json_frame_not_a_bare_marker(self):
        """
        Pins the wire shape at the source, so the disagreement between the two ends stays
        visible from the test suite rather than only from reading both files.
        """
        import app.services._publish as publish_module

        recorded = []

        class Recorder:
            def publish(self, channel, payload):
                recorded.append(payload)

        publish_module.publish_log(Recorder(), "repo-id", "done", "DONE")

        assert recorded[0].startswith("{")
        assert json.loads(recorded[0])["message"] == "DONE"

    async def test_a_real_done_frame_ends_the_stream(self, db_session, redis_client):
        """Asserting the intended behaviour: the marker the publisher emits ends the relay."""
        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)

        socket, closed = await ended_by_itself(
            user, repo.id, db_session, redis_client, [done_frame()]
        )

        assert socket.sent == [done_frame()]
        assert closed, "the stream did not end on the completion frame"

    async def test_a_real_error_frame_ends_the_stream(self, db_session, redis_client):
        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)

        socket, closed = await ended_by_itself(
            user, repo.id, db_session, redis_client, [error_frame()]
        )

        assert socket.sent == [error_frame()]
        assert closed

    async def test_nothing_after_the_marker_is_relayed(self, db_session, redis_client):
        """
        Once the marker is recognised the loop breaks, so a late write -- a retried task
        reporting after the first one finished -- must not reach the client.
        """
        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)

        socket, closed = await ended_by_itself(
            user, repo.id, db_session, redis_client, [done_frame(), log_frame("late")]
        )

        assert closed
        assert socket.sent == [done_frame()]


class TestDisconnect:
    async def test_a_disconnect_mid_stream_cleans_up(self, db_session, redis_client):
        """
        `WebSocketDisconnect` is caught, and the `finally` block still unsubscribes and
        closes the Redis client. A client going away must not leave the subscription
        behind, and must not surface as an unhandled error.
        """
        from starlette.websockets import WebSocketDisconnect

        from app.api.v1.ws import ingest_ws

        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)

        class DisconnectingSocket(FakeWebSocket):
            async def send_text(self, data: str) -> None:
                raise WebSocketDisconnect(code=1001)

        socket = DisconnectingSocket(
            cookies={"access_token": create_access_token(subject=str(user.id))}
        )
        task = asyncio.create_task(ingest_ws(socket, repo.id, db_session))
        try:
            await wait_for_subscribers(redis_client, channel_for(repo.id))
            await redis_client.publish(channel_for(repo.id), json.dumps({"event": "log"}))
            await asyncio.wait_for(task, timeout=10)  # must not raise
        finally:
            if not task.done():
                task.cancel()

        await wait_for_no_subscribers(redis_client, channel_for(repo.id))

    async def test_cancellation_cleans_up_and_propagates(self, db_session, redis_client):
        """
        Cancelling the task stops it, releases the subscription, and surfaces to whoever
        awaited it.

        Both halves are pinned deliberately. The cleanup is what keeps Redis from
        accumulating a subscription per cancelled socket, and the propagation is what lets
        `asyncio.wait_for` impose a deadline on this handler at all -- absorbing the
        cancellation made the task report a clean finish while the socket stayed
        subscribed, so a timeout fired and nothing noticed.
        """
        from app.api.v1.ws import ingest_ws

        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)

        socket = FakeWebSocket(cookies={"access_token": create_access_token(subject=str(user.id))})
        task = asyncio.create_task(ingest_ws(socket, repo.id, db_session))

        await wait_for_subscribers(redis_client, channel_for(repo.id))
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=10)

        assert task.cancelled() is True
        await wait_for_no_subscribers(redis_client, channel_for(repo.id))

    async def test_a_timeout_can_bound_the_handler(self, db_session, redis_client):
        """
        The consequence of the above, stated as its own case.

        `asyncio.wait_for` bounds a coroutine by cancelling it and expecting the
        cancellation to propagate. Because this handler absorbs `CancelledError` and
        returns normally, the timeout does not fire: `wait_for` reports a clean finish
        instead of raising `TimeoutError`, and the caller is left believing the work
        completed on its own.

        Practical effect: there is no way to cap how long a socket whose client never
        disconnects stays subscribed. The handler only leaves its loop on `DONE`/`ERROR`,
        a disconnect, or an exception -- none of which a supervisor can supply.
        """
        from app.api.v1.ws import ingest_ws

        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)

        socket = FakeWebSocket(cookies={"access_token": create_access_token(subject=str(user.id))})
        task = asyncio.create_task(ingest_ws(socket, repo.id, db_session))
        await wait_for_subscribers(redis_client, channel_for(repo.id))

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=0.2)

    async def test_the_eventual_cleanup_is_correct(self, db_session, redis_client):
        """
        The cleanup half on its own: the `finally` block runs whether the cancellation
        propagates or not, so the subscription and the Redis connection are both released.

        The defect was always about the signal rather than about cleanup leaking anything,
        which is why it is low severity -- but a handler that cannot be timed out is the
        kind of thing a supervisor is added for later and would then silently not work.
        """
        from app.api.v1.ws import ingest_ws

        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)

        socket = FakeWebSocket(cookies={"access_token": create_access_token(subject=str(user.id))})
        task = asyncio.create_task(ingest_ws(socket, repo.id, db_session))
        await wait_for_subscribers(redis_client, channel_for(repo.id))

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=10)

        await wait_for_no_subscribers(redis_client, channel_for(repo.id))
