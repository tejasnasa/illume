"""Helpers for driving the streaming endpoint end to end.

The route is exercised through the real application, with only the seams a
deployment leaves at their defaults replaced: the sessions a run writes with
join the test's open transaction, the model is scripted, and the decider is a
list of answers. The database and Redis are real.
"""

from __future__ import annotations

import asyncio
import copy
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.agent import get_run_kit, get_run_sessions
from app.models import AgentRun, AgentStep, ChatMessage, Repository, User
from app.services.agent.session import RunKit
from app.services.agent.slots import slot_key
from tests.factories import make_user
from tests.fixtures.agent_run import (
    RoutedModel,
    ScriptedModel,
    build_response,
    call,
    finish,
    plan_reply,
    say,
    serialized,
    turn,
)
from tests.fixtures.agent_tools import SECURITY, session_factory_for
from tests.fixtures.retrieval import RETRIEVAL_FIXTURE, SeededRepo, fake_embedder, seed_repo
from tests.helpers import authenticate

QUESTION = "Where is `verify_password` defined?"
USERS = "app/users/service.py"


class AnyModel(ScriptedModel):
    """A model that answers every call with the same text, whatever it is asked.

    Used where a test counts calls (the query rewrite, the reranker and the
    answer all reach the same client) rather than scripting each one.
    """

    def __init__(self, text: str = "An answer about the code.") -> None:
        super().__init__()
        self._text = text

    async def create(self, **kwargs: Any) -> Any:
        self.requests.append(copy.deepcopy(kwargs))
        reply = say(self._text)
        if kwargs.get("stream"):
            return self._events(reply)
        return build_response(reply)


def parse_sse(body: str) -> list[dict[str, Any]]:
    """The frames of an event-stream body, comments (keep-alives) dropped.

    Each frame is ``{"event", "id", "data"}`` with ``data`` decoded from JSON.
    """
    frames: list[dict[str, Any]] = []
    for block in re.split(r"\r?\n\r?\n", body.strip()):
        frame: dict[str, Any] = {"event": None, "id": None}
        data: list[str] = []
        for line in block.splitlines():
            if not line or line.startswith(":"):
                continue
            name, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if name == "data":
                data.append(value)
            elif name in ("event", "id"):
                frame[name] = value
        if data:
            frame["data"] = json.loads("\n".join(data))
            frames.append(frame)
    return frames


def types_of(events: list[dict[str, Any]]) -> list[str]:
    """The event types of a list of envelopes."""
    return [event["type"] for event in events]


def of_type(events: list[dict[str, Any]], event_type: str) -> list[dict[str, Any]]:
    """The envelopes of one type, in order."""
    return [event for event in events if event["type"] == event_type]


def stream_url(repo: Repository) -> str:
    return f"/api/v1/repository/{repo.id}/chat/stream"


def runs_url(repo: Repository) -> str:
    return f"/api/v1/repository/{repo.id}/agent-runs"


def install(
    app: Any,
    db_session: AsyncSession | None,
    model: ScriptedModel | None = None,
    *,
    sessions: Any = None,
    **kit: Any,
) -> Any:
    """Points the route's seams at the test transaction and the scripted model.

    Returns:
        The session opener the run will write with.
    """
    if sessions is None:
        assert db_session is not None
        sessions = serialized(session_factory_for(db_session.bind))
    opener = sessions
    kit.setdefault("embed", fake_embedder())
    if model is not None:
        kit.setdefault("client_factory", model.factory)
    run_kit = RunKit(**kit)
    app.dependency_overrides[get_run_sessions] = lambda: opener
    app.dependency_overrides[get_run_kit] = lambda: run_kit
    return opener


async def stream(
    client: Any, repo: Repository, question: str = QUESTION, **body: Any
) -> tuple[Any, list[dict[str, Any]]]:
    """Posts to the stream route and returns the response and its decoded events."""
    response = await client.post(stream_url(repo), json={"question": question, **body})
    if response.status_code != 200:
        return response, []
    return response, [frame["data"] for frame in parse_sse(response.text)]


@dataclass
class World:
    """A signed-in user with a seeded repository.

    Attributes:
        user: The signed-in user; a BYOK user holds a key and a tool-capable model.
        seeded: The repository the tests ask about.
    """

    user: User
    seeded: SeededRepo

    @property
    def repo(self) -> Repository:
        return self.seeded.repo

    @property
    def symbol_key(self) -> str:
        symbol = self.seeded.symbols[(SECURITY, "verify_password")]
        return f"F:{SECURITY}:{symbol.start_line}-{symbol.end_line}"

    @property
    def user_key(self) -> str:
        symbol = self.seeded.symbols[(USERS, "create_user")]
        return f"F:{USERS}:{symbol.start_line}-{symbol.end_line}"


async def make_world(
    client: Any, db: AsyncSession, *, byok: bool = True, **user_fields: Any
) -> World:
    """Seeds a user and a repository and signs the user in.

    Args:
        client: The test client to sign in.
        db: The test session.
        byok: Give the user a key of their own; ``False`` leaves them on the free tier.
        **user_fields: Extra columns of the user.
    """
    user = await make_user(db, ai_api_key="sk-user-secret" if byok else None)
    user.ai_supports_tools = True if byok else None
    for name, value in user_fields.items():
        setattr(user, name, value)
    seeded = await seed_repo(db, user, RETRIEVAL_FIXTURE, name="stream-mine")
    await db.flush()
    await authenticate(client, user)
    return World(user=user, seeded=seeded)


async def make_stranger_repo(db: AsyncSession) -> tuple[User, SeededRepo]:
    """Another user's repository with the same paths as the fixture."""
    stranger = await make_user(db, ai_api_key="sk-stranger-secret")
    return stranger, await seed_repo(db, stranger, RETRIEVAL_FIXTURE, name="stream-theirs")


def planner_model(world: World, *, hold: Any = None) -> RoutedModel:
    """A model for a parallel run: two workers, then a merge.

    Args:
        world: The seeded repository.
        hold: Awaited before the second worker's first model call, to keep a run open.
    """
    auth_question = "Where is `verify_password` defined?"
    user_question = "Where is `create_user` defined?"
    return RoutedModel(
        planner=plan_reply(
            [
                {"id": "auth", "question": auth_question, "focus": "code"},
                {"id": "users", "question": user_question, "focus": "code"},
            ],
            hint="Name each function and the file it lives in.",
        ),
        workers={
            auth_question: [
                turn(call("search_symbols", {"name": "verify_password"})),
                turn(finish(f"`verify_password` is in {SECURITY} [{world.symbol_key}].")),
            ],
            user_question: [
                turn(call("search_symbols", {"name": "create_user"}), before=hold),
                turn(finish(f"`create_user` is in {USERS} [{world.user_key}].")),
            ],
        },
        merge=say(
            f"Passwords are checked in {SECURITY} [{world.symbol_key}] and users are created "
            f"in {USERS} [{world.user_key}]."
        ),
        fallback=[turn(finish("A single agent answered."))],
    )


class Hold:
    """Holds a model call open until released, and says when it was reached."""

    def __init__(self) -> None:
        self.reached = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self) -> None:
        self.reached.set()
        await self.release.wait()


class RawRequest:
    """Drives the application below the HTTP client so a test can hang up mid-stream.

    ``httpx``'s in-process transport only returns once the response has ended;
    this speaks the ASGI protocol directly and sends ``http.disconnect`` on demand.
    """

    def __init__(self, app: Any, client: Any, path: str, body: dict[str, Any]) -> None:
        self._app = app
        encoded = json.dumps(body).encode()
        cookie = client.cookies.get("access_token")
        self._scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 50000),
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(encoded)).encode()),
                (b"cookie", f"access_token={cookie}".encode()),
            ],
        }
        self._body = encoded
        self._sent_body = False
        self._hang_up = asyncio.Event()
        self.messages: list[dict[str, Any]] = []
        self.task: asyncio.Task[None] | None = None

    async def _receive(self) -> dict[str, Any]:
        if not self._sent_body:
            self._sent_body = True
            return {"type": "http.request", "body": self._body, "more_body": False}
        await self._hang_up.wait()
        return {"type": "http.disconnect"}

    async def _send(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    def start(self) -> None:
        self.task = asyncio.create_task(self._app(self._scope, self._receive, self._send))

    async def hang_up(self) -> None:
        """Disconnects, then waits for the application to finish handling it."""
        self._hang_up.set()
        assert self.task is not None
        await asyncio.wait_for(self.task, 20)

    @property
    def status(self) -> int | None:
        for message in self.messages:
            if message["type"] == "http.response.start":
                return message["status"]
        return None

    @property
    def text(self) -> str:
        return b"".join(m.get("body", b"") for m in self.messages).decode()


# --- reading back ---------------------------------------------------------------------


async def runs_of(db: AsyncSession, repo: Repository) -> list[AgentRun]:
    result = await db.execute(select(AgentRun).where(AgentRun.repository_id == repo.id))
    return list(result.scalars().all())


async def only_run(db: AsyncSession, repo: Repository) -> AgentRun:
    [run] = await runs_of(db, repo)
    await db.refresh(run)
    return run


async def step_rows(db: AsyncSession, run_id: uuid.UUID) -> list[AgentStep]:
    result = await db.execute(
        select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.seq)
    )
    return list(result.scalars().all())


async def turns_of(db: AsyncSession, repo: Repository) -> list[ChatMessage]:
    result = await db.execute(select(ChatMessage).where(ChatMessage.repository_id == repo.id))
    return list(result.scalars().all())


async def slot_count(redis: Any, user: User) -> int:
    return int(await redis.zcard(slot_key(user.id)))


async def wait_until(condition: Any, timeout: float = 10.0) -> None:
    """Polls an async or sync condition until it holds."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        outcome = condition()
        if asyncio.iscoroutine(outcome):
            outcome = await outcome
        if outcome:
            return
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("the condition did not hold in time")
        await asyncio.sleep(0.02)


# --- committed data, for tests that need real concurrency -------------------------------


class Committed:
    """Rows committed to the test database, for tests whose requests must not share a connection.

    Everything else runs inside a transaction that is rolled back, on one connection.
    Two requests in flight at once need a connection each, so their rows must be
    visible to both, which means committing them and deleting them afterwards.
    """

    def __init__(self, engine: Any) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        self.maker = async_sessionmaker(engine, expire_on_commit=False)
        self.users: list[User] = []

    async def user_with_repo(
        self, *, byok: bool, used: int = 0, question_vector: list[float] | None = None
    ) -> tuple[User, Repository]:
        """A user and a ready repository with one embedded README section."""
        from tests.factories import fake_vector, make_embedding, make_ingested_repo

        async with self.maker() as db:
            user = await make_user(db, ai_api_key="sk-live-secret" if byok else None)
            user.ai_supports_tools = True if byok else None
            user.free_chat_messages_used = used
            repo, _ = await make_ingested_repo(db, user)
            await make_embedding(
                db,
                repo,
                source_type="document",
                chunk_text="## Overview\nThe service verifies passwords.",
                vector=question_vector or fake_vector(0.5),
            )
            await db.commit()
        self.users.append(user)
        return user, repo

    async def used(self, user: User) -> int:
        """The user's free-tier counter as committed."""
        async with self.maker() as db:
            row = await db.execute(select(User.free_chat_messages_used).where(User.id == user.id))
            return int(row.scalar_one())

    async def drop(self) -> None:
        """Deletes everything created, through the users' cascades."""
        from sqlalchemy import delete

        async with self.maker() as db:
            for user in self.users:
                await db.execute(delete(User).where(User.id == user.id))
            await db.commit()
