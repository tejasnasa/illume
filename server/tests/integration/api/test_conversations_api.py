"""Chat conversations: the routes, and how a question joins or starts one.

``answer_question`` is stubbed for the chat route and the model is scripted for the
stream route, as in their own modules. What these tests pin is the conversation
contract: ownership, titles, ordering, cascades, and that a request refused or
failed before it has an answer leaves no conversation behind.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import AgentRun, ChatMessage, Conversation
from app.services.conversations import TITLE_LIMIT, title_from_question
from app.services.rag import RAGResponse
from tests.factories import make_chat_message, make_conversation, make_ingested_repo, make_user
from tests.fixtures.agent_stream import (
    QUESTION,
    AnyModel,
    install,
    make_world,
    of_type,
    stream,
)
from tests.fixtures.retrieval import fake_embedder
from tests.helpers import authenticate

pytestmark = pytest.mark.integration

BASE = "/api/v1/repository"


@pytest.fixture(autouse=True)
def no_model_backed_stages(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")


async def conversations_of(db, repo, user=None) -> list[Conversation]:
    query = select(Conversation).where(Conversation.repository_id == repo.id)
    if user is not None:
        query = query.where(Conversation.user_id == user.id)
    result = await db.execute(query.order_by(Conversation.created_at, Conversation.id))
    return list(result.scalars().all())


async def messages_of(db, repo) -> list[ChatMessage]:
    result = await db.execute(select(ChatMessage).where(ChatMessage.repository_id == repo.id))
    return list(result.scalars().all())


@pytest.fixture
async def mine(client, db_session):
    user = await make_user(db_session, ai_api_key="sk-test")
    repo, _ = await make_ingested_repo(db_session, user)
    await authenticate(client, user)
    return user, repo


@pytest.fixture
async def theirs(db_session):
    """Another user's repository with one conversation holding one turn."""
    stranger = await make_user(db_session, ai_api_key="sk-stranger")
    repo, _ = await make_ingested_repo(db_session, stranger)
    message = await make_chat_message(db_session, repo, stranger, question="private")
    return stranger, repo, message


class TestTitle:
    def test_whitespace_is_collapsed(self):
        assert title_from_question("  how\n does   this\twork? ") == "how does this work?"

    def test_a_question_at_the_limit_is_kept(self):
        question = "x" * TITLE_LIMIT

        assert title_from_question(question) == question

    def test_a_longer_question_is_cut_to_the_limit_with_an_ellipsis(self):
        title = title_from_question("word " * 40)

        assert len(title) <= TITLE_LIMIT
        assert title.endswith("…")
        assert "  " not in title

    def test_a_long_unbroken_question_is_exactly_the_limit(self):
        title = title_from_question("x" * 500)

        assert len(title) == TITLE_LIMIT
        assert title == "x" * (TITLE_LIMIT - 1) + "…"

    def test_a_blank_question_gets_the_placeholder(self):
        assert title_from_question("  \n ") == "New chat"


class TestList:
    async def test_it_lists_newest_activity_first_with_counts(self, client, db_session, mine):
        user, repo = mine
        older = await make_conversation(db_session, repo, user, title="older", new=True)
        newer = await make_conversation(db_session, repo, user, title="newer", new=True)
        await make_chat_message(db_session, repo, user, conversation_id=older)
        await make_chat_message(db_session, repo, user, conversation_id=older)
        await make_chat_message(db_session, repo, user, conversation_id=newer)
        await db_session.execute(
            Conversation.__table__.update()
            .where(Conversation.id == older)
            .values(updated_at=Conversation.updated_at + timedelta(hours=1))
        )
        await db_session.flush()

        response = await client.get(f"{BASE}/{repo.id}/conversations")

        assert response.status_code == 200
        rows = response.json()
        assert [(r["title"], r["message_count"]) for r in rows] == [("older", 2), ("newer", 1)]
        assert set(rows[0]) == {"id", "title", "created_at", "updated_at", "message_count"}

    async def test_an_empty_conversation_has_a_zero_count(self, client, db_session, mine):
        user, repo = mine
        await make_conversation(db_session, repo, user, title="empty", new=True)

        [row] = (await client.get(f"{BASE}/{repo.id}/conversations")).json()

        assert row["message_count"] == 0

    async def test_other_users_conversations_are_not_listed(self, client, mine, theirs):
        _, repo = mine
        _, other_repo, _ = theirs

        assert (await client.get(f"{BASE}/{repo.id}/conversations")).json() == []
        assert (await client.get(f"{BASE}/{other_repo.id}/conversations")).status_code == 404

    async def test_an_unauthenticated_caller_is_refused(self, client, mine):
        _, repo = mine
        client.cookies.clear()

        assert (await client.get(f"{BASE}/{repo.id}/conversations")).status_code == 401


class TestCreate:
    async def test_it_creates_an_empty_conversation_with_a_placeholder_title(
        self, client, db_session, mine
    ):
        user, repo = mine

        response = await client.post(f"{BASE}/{repo.id}/conversations")

        assert response.status_code == 201
        body = response.json()
        assert body["title"] == "New chat" and body["message_count"] == 0
        [stored] = await conversations_of(db_session, repo, user)
        assert str(stored.id) == body["id"]

    async def test_a_given_title_is_trimmed_and_used(self, client, mine):
        _, repo = mine

        response = await client.post(f"{BASE}/{repo.id}/conversations", json={"title": "  Auth  "})

        assert response.json()["title"] == "Auth"

    @pytest.mark.parametrize("title", ["", "   ", "x" * 121, "bad\x00title"])
    async def test_a_bad_title_is_refused(self, client, db_session, mine, title):
        user, repo = mine

        response = await client.post(f"{BASE}/{repo.id}/conversations", json={"title": title})

        assert response.status_code == 422
        assert await conversations_of(db_session, repo, user) == []

    async def test_another_users_repository_is_not_found(self, client, db_session, mine, theirs):
        _, other_repo, _ = theirs
        before = len(await conversations_of(db_session, other_repo))

        response = await client.post(f"{BASE}/{other_repo.id}/conversations")

        assert response.status_code == 404
        assert len(await conversations_of(db_session, other_repo)) == before


class TestRename:
    async def test_it_renames_and_keeps_the_order(self, client, db_session, mine):
        user, repo = mine
        cid = await make_conversation(db_session, repo, user, title="old", new=True)
        await make_chat_message(db_session, repo, user, conversation_id=cid)
        before = (await client.get(f"{BASE}/{repo.id}/conversations")).json()[0]

        response = await client.patch(
            f"{BASE}/{repo.id}/conversations/{cid}", json={"title": "x" * 120}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["title"] == "x" * 120 and body["message_count"] == 1
        assert body["updated_at"] == before["updated_at"]

    @pytest.mark.parametrize("title", ["", "  ", "x" * 121])
    async def test_a_title_outside_one_to_120_characters_is_refused(
        self, client, db_session, mine, title
    ):
        user, repo = mine
        cid = await make_conversation(db_session, repo, user, title="keep", new=True)

        response = await client.patch(
            f"{BASE}/{repo.id}/conversations/{cid}", json={"title": title}
        )

        assert response.status_code == 422
        [row] = await conversations_of(db_session, repo, user)
        assert row.title == "keep"

    async def test_another_users_conversation_is_not_found_and_unchanged(
        self, client, db_session, mine, theirs
    ):
        _, repo = mine
        stranger, other_repo, message = theirs

        for path in (
            f"{BASE}/{other_repo.id}/conversations/{message.conversation_id}",
            f"{BASE}/{repo.id}/conversations/{message.conversation_id}",
            f"{BASE}/{repo.id}/conversations/{uuid.uuid4()}",
        ):
            assert (await client.patch(path, json={"title": "mine now"})).status_code == 404

        [row] = await conversations_of(db_session, other_repo, stranger)
        assert row.title != "mine now"


class TestDelete:
    async def test_it_deletes_the_conversation_and_its_turns_only(self, client, db_session, mine):
        user, repo = mine
        doomed = await make_conversation(db_session, repo, user, title="doomed", new=True)
        kept = await make_conversation(db_session, repo, user, title="kept", new=True)
        await make_chat_message(db_session, repo, user, conversation_id=doomed)
        survivor = await make_chat_message(db_session, repo, user, conversation_id=kept)

        response = await client.delete(f"{BASE}/{repo.id}/conversations/{doomed}")

        assert response.status_code == 204
        assert [c.id for c in await conversations_of(db_session, repo, user)] == [kept]
        assert [m.id for m in await messages_of(db_session, repo)] == [survivor.id]

    async def test_another_users_conversation_is_not_found_and_kept(
        self, client, db_session, mine, theirs
    ):
        _, repo = mine
        stranger, other_repo, message = theirs

        for path in (
            f"{BASE}/{other_repo.id}/conversations/{message.conversation_id}",
            f"{BASE}/{repo.id}/conversations/{message.conversation_id}",
        ):
            assert (await client.delete(path)).status_code == 404

        assert len(await conversations_of(db_session, other_repo, stranger)) == 1
        assert len(await messages_of(db_session, other_repo)) == 1


class TestMessages:
    async def test_it_returns_the_turns_oldest_first_in_the_history_shape(
        self, client, db_session, mine
    ):
        user, repo = mine
        cid = await make_conversation(db_session, repo, user, new=True)
        other = await make_conversation(db_session, repo, user, new=True)
        first = await make_chat_message(db_session, repo, user, conversation_id=cid, question="a")
        await db_session.execute(
            ChatMessage.__table__.update()
            .where(ChatMessage.id == first.id)
            .values(created_at=ChatMessage.created_at - timedelta(hours=1))
        )
        await make_chat_message(db_session, repo, user, conversation_id=cid, question="b")
        await make_chat_message(db_session, repo, user, conversation_id=other, question="elsewhere")

        response = await client.get(f"{BASE}/{repo.id}/conversations/{cid}/messages")

        assert response.status_code == 200
        rows = response.json()
        assert [r["question"] for r in rows] == ["a", "b"]
        history = (await client.get(f"{BASE}/{repo.id}/chat/history")).json()
        assert set(rows[0]) == set(history[0])
        assert {r["conversation_id"] for r in rows} == {str(cid)}

    async def test_another_users_conversation_is_not_found(self, client, mine, theirs):
        _, repo = mine
        _, other_repo, message = theirs

        for repo_id in (repo.id, other_repo.id):
            path = f"{BASE}/{repo_id}/conversations/{message.conversation_id}/messages"
            assert (await client.get(path)).status_code == 404


class TestHistoryAndClear:
    async def test_history_can_be_limited_to_one_conversation(self, client, db_session, mine):
        user, repo = mine
        one = await make_conversation(db_session, repo, user, new=True)
        two = await make_conversation(db_session, repo, user, new=True)
        await make_chat_message(db_session, repo, user, conversation_id=one, question="in one")
        await make_chat_message(db_session, repo, user, conversation_id=two, question="in two")

        everything = (await client.get(f"{BASE}/{repo.id}/chat/history")).json()
        only_two = (await client.get(f"{BASE}/{repo.id}/chat/history?conversation_id={two}")).json()

        assert sorted(r["question"] for r in everything) == ["in one", "in two"]
        assert [r["question"] for r in only_two] == ["in two"]

    async def test_history_for_a_foreign_conversation_is_not_found(self, client, mine, theirs):
        _, repo = mine
        _, _, message = theirs

        response = await client.get(
            f"{BASE}/{repo.id}/chat/history?conversation_id={message.conversation_id}"
        )

        assert response.status_code == 404

    async def test_clearing_deletes_every_conversation_and_turn_of_the_caller_only(
        self, client, db_session, mine, theirs
    ):
        user, repo = mine
        stranger, other_repo, _ = theirs
        for _ in range(2):
            cid = await make_conversation(db_session, repo, user, new=True)
            await make_chat_message(db_session, repo, user, conversation_id=cid)
        await make_conversation(db_session, repo, user, new=True)

        response = await client.delete(f"{BASE}/{repo.id}/chat")

        assert response.status_code == 204
        assert await conversations_of(db_session, repo) == []
        assert await messages_of(db_session, repo) == []
        assert len(await conversations_of(db_session, other_repo, stranger)) == 1
        assert len(await messages_of(db_session, other_repo)) == 1


class TestChatRoute:
    @pytest.fixture
    def rag(self, monkeypatch):
        calls: list[dict] = []

        async def fake_answer(query, repository_id, db, history=None, *, llm=None):
            calls.append({"query": query})
            return RAGResponse(answer=f"Answer to: {query}", sources=[])

        import app.api.v1.chat as chat_module

        monkeypatch.setattr(chat_module, "answer_question", fake_answer)
        return calls

    async def test_a_question_without_a_conversation_starts_one_titled_from_it(
        self, client, db_session, mine, rag
    ):
        user, repo = mine

        response = await client.post(
            f"{BASE}/{repo.id}/chat", json={"question": "  What does\n the parser do?  "}
        )

        assert response.status_code == 200
        [conversation] = await conversations_of(db_session, repo, user)
        assert response.json()["conversation_id"] == str(conversation.id)
        assert conversation.title == "What does the parser do?"
        [message] = await messages_of(db_session, repo)
        assert message.conversation_id == conversation.id

    async def test_a_question_with_a_conversation_joins_it_and_moves_it_up(
        self, client, db_session, mine, rag
    ):
        user, repo = mine
        target = await make_conversation(db_session, repo, user, title="mine", new=True)
        await db_session.execute(
            Conversation.__table__.update()
            .where(Conversation.id == target)
            .values(updated_at=Conversation.updated_at - timedelta(days=1))
        )
        await db_session.flush()
        before = (await client.get(f"{BASE}/{repo.id}/conversations")).json()[0]["updated_at"]

        response = await client.post(
            f"{BASE}/{repo.id}/chat", json={"question": "again", "conversation_id": str(target)}
        )

        assert response.status_code == 200
        assert response.json()["conversation_id"] == str(target)
        [row] = (await client.get(f"{BASE}/{repo.id}/conversations")).json()
        assert row["id"] == str(target) and row["message_count"] == 1
        assert row["updated_at"] > before
        assert row["title"] == "mine"

    async def test_a_foreign_or_unknown_conversation_is_not_found_and_nothing_is_written(
        self, client, db_session, mine, theirs, rag
    ):
        user, repo = mine
        stranger, other_repo, message = theirs

        for conversation_id in (message.conversation_id, uuid.uuid4()):
            response = await client.post(
                f"{BASE}/{repo.id}/chat",
                json={"question": "q", "conversation_id": str(conversation_id)},
            )
            assert response.status_code == 404

        assert rag == []
        assert await conversations_of(db_session, repo, user) == []
        assert len(await messages_of(db_session, other_repo)) == 1

    async def test_a_conversation_of_another_repository_of_mine_is_not_found(
        self, client, db_session, mine, rag
    ):
        user, repo = mine
        second, _ = await make_ingested_repo(db_session, user)
        elsewhere = await make_conversation(db_session, second, user, new=True)

        response = await client.post(
            f"{BASE}/{repo.id}/chat", json={"question": "q", "conversation_id": str(elsewhere)}
        )

        assert response.status_code == 404

    async def test_a_refused_question_leaves_no_conversation(self, client, db_session, mine, rag):
        user, repo = mine
        too_long = "x" * 4001

        assert (
            await client.post(f"{BASE}/{repo.id}/chat", json={"question": too_long})
        ).status_code == 422
        user.ai_api_key = None
        user.free_chat_messages_used = 10_000
        await db_session.flush()
        assert (
            await client.post(f"{BASE}/{repo.id}/chat", json={"question": "q"})
        ).status_code == 402
        repo.status = "failed"
        await db_session.flush()
        assert (
            await client.post(f"{BASE}/{repo.id}/chat", json={"question": "q"})
        ).status_code == 400

        assert await conversations_of(db_session, repo, user) == []

    async def test_a_failed_answer_leaves_no_conversation(
        self, client, db_session, mine, monkeypatch
    ):
        import httpx
        from openai import APIConnectionError

        import app.api.v1.chat as chat_module

        async def broken(*args, **kwargs):
            raise APIConnectionError(request=httpx.Request("POST", "https://x"))

        monkeypatch.setattr(chat_module, "answer_question", broken)
        user, repo = mine

        response = await client.post(f"{BASE}/{repo.id}/chat", json={"question": "q"})

        assert response.status_code == 502
        assert await conversations_of(db_session, repo, user) == []


class TestStreamRoute:
    @pytest.fixture
    async def world(self, client, db_session, app):
        world = await make_world(client, db_session)
        vector = list(
            world.seeded.symbol_embeddings[("app/auth/security.py", "verify_password")].embedding
        )
        install(app, db_session, AnyModel(), embed=fake_embedder({QUESTION: vector}))
        return world

    async def test_a_question_without_a_conversation_starts_one(self, client, db_session, world):
        response, events = await stream(client, world.repo, preset="classic")

        assert response.status_code == 200
        [conversation] = await conversations_of(db_session, world.repo, world.user)
        [started] = of_type(events, "run_started")
        done = events[-1]
        assert done["type"] == "done"
        assert started["data"]["conversation_id"] == str(conversation.id)
        assert done["data"]["conversation_id"] == str(conversation.id)
        assert conversation.title == QUESTION
        [message] = await messages_of(db_session, world.repo)
        assert message.conversation_id == conversation.id
        assert done["data"]["chat_message_id"] == str(message.id)

    async def test_a_question_with_a_conversation_joins_it(self, client, db_session, world):
        target = await make_conversation(
            db_session, world.repo, world.user, title="existing", new=True
        )

        _, events = await stream(client, world.repo, preset="classic", conversation_id=str(target))

        assert events[-1]["data"]["conversation_id"] == str(target)
        [conversation] = await conversations_of(db_session, world.repo, world.user)
        assert conversation.id == target and conversation.title == "existing"
        [message] = await messages_of(db_session, world.repo)
        assert message.conversation_id == target

    async def test_a_foreign_conversation_is_not_found_and_starts_no_run(
        self, client, db_session, world
    ):
        stranger = await make_user(db_session, ai_api_key="sk-stranger")
        theirs_repo, _ = await make_ingested_repo(db_session, stranger)
        foreign = await make_conversation(db_session, theirs_repo, stranger, new=True)

        for conversation_id in (foreign, uuid.uuid4()):
            response, _ = await stream(
                client, world.repo, preset="classic", conversation_id=str(conversation_id)
            )
            assert response.status_code == 404

        runs = (
            (
                await db_session.execute(
                    select(AgentRun).where(AgentRun.repository_id == world.repo.id)
                )
            )
            .scalars()
            .all()
        )
        assert runs == []
        assert await conversations_of(db_session, world.repo, world.user) == []

    async def test_a_refused_request_leaves_no_conversation(self, client, db_session, world):
        too_long, _ = await stream(client, world.repo, "x" * 4001, preset="classic")
        unknown_preset, _ = await stream(client, world.repo, preset="nope")
        world.user.ai_api_key = None
        world.user.free_chat_messages_used = 10_000
        await db_session.flush()
        spent, _ = await stream(client, world.repo, preset="classic")

        assert [too_long.status_code, unknown_preset.status_code, spent.status_code] == [
            422,
            422,
            402,
        ]
        assert await conversations_of(db_session, world.repo, world.user) == []

    async def test_a_run_that_fails_leaves_no_conversation(self, app, client, db_session, world):
        import httpx
        from openai import APIConnectionError

        from tests.fixtures.agent_run import ScriptedModel, turn

        model = ScriptedModel(
            [turn(error=APIConnectionError(request=httpx.Request("POST", "https://x")))]
        )
        install(app, db_session, model)

        _, events = await stream(client, world.repo, preset="hybrid")

        assert events[-1]["type"] == "error"
        assert await conversations_of(db_session, world.repo, world.user) == []
        assert await messages_of(db_session, world.repo) == []
