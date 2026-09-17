"""Repository chat: asking, history, and deletion.

`answer_question` is stubbed throughout. It embeds the query and calls OpenAI, so
exercising it here would test the RAG pipeline rather than the route -- and would need a
live API key. What these tests pin is the route's own contract: ownership, the
ready gate, history capping, and how sources are persisted and read back.
"""

import pytest

from app.services.rag import RAGResponse, SourceReference
from tests.factories import make_chat_message, make_ingested_repo, make_repo, make_user
from tests.helpers import authenticate, random_uuid

pytestmark = pytest.mark.integration


def chat_url(repo) -> str:
    return f"/api/v1/repository/{repo.id}/chat"


def history_url(repo) -> str:
    return f"/api/v1/repository/{repo.id}/chat/history"


def symbol_source() -> SourceReference:
    return SourceReference(
        source_type="symbol",
        chunk_text="def f(): pass",
        file_path="src/module_0.py",
        symbol_name="func_0",
        start_line=1,
        end_line=10,
    )


def commit_source() -> SourceReference:
    return SourceReference(
        source_type="commit",
        chunk_text="abc123 | Ada | add feature",
        commit_hash="abc1234",
        author_name="Ada Lovelace",
    )


@pytest.fixture
def rag(monkeypatch):
    """
    Replace `answer_question` with a recorder.

    Patched on the chat module rather than on `app.services.rag`, because the route bound
    the name at import time -- patching the source module would leave the route calling
    the original.
    """
    calls: list[dict] = []

    async def fake_answer_question(query, repository_id, db, history=None):
        calls.append({"query": query, "repository_id": repository_id, "history": history})
        return RAGResponse(
            answer=f"Answer to: {query}",
            sources=[symbol_source(), commit_source()],
        )

    import app.api.v1.chat as chat_module

    monkeypatch.setattr(chat_module, "answer_question", fake_answer_question)
    return calls


@pytest.fixture
async def chattable(client, db_session):
    """A signed-in user with a ready repository."""
    user = await make_user(db_session)
    repo, _ = await make_ingested_repo(db_session, user)
    await authenticate(client, user)
    return user, repo


class TestAsk:
    async def test_returns_the_answer(self, client, chattable, rag):
        _, repo = chattable

        response = await client.post(chat_url(repo), json={"question": "What is this?"})

        assert response.status_code == 200
        assert response.json()["answer"] == "Answer to: What is this?"

    async def test_returns_citations(self, client, chattable, rag):
        _, repo = chattable

        sources = (await client.post(chat_url(repo), json={"question": "q"})).json()["sources"]

        assert [s["source_type"] for s in sources] == ["symbol", "commit"]

    async def test_a_symbol_citation_carries_its_location(self, client, chattable, rag):
        _, repo = chattable

        source = (await client.post(chat_url(repo), json={"question": "q"})).json()["sources"][0]

        assert source["file_path"] == "src/module_0.py"
        assert source["symbol_name"] == "func_0"
        assert source["start_line"] == 1

    async def test_a_commit_citation_carries_hash_and_author(self, client, chattable, rag):
        _, repo = chattable

        source = (await client.post(chat_url(repo), json={"question": "q"})).json()["sources"][1]

        assert source["commit_hash"] == "abc1234"
        assert source["author_name"] == "Ada Lovelace"

    async def test_persists_the_turn(self, client, db_session, chattable, rag):
        from sqlalchemy import select

        from app.models.chat_message import ChatMessage

        user, repo = chattable

        await client.post(chat_url(repo), json={"question": "What is this?"})

        result = await db_session.execute(
            select(ChatMessage).where(ChatMessage.repository_id == repo.id)
        )
        stored = result.scalar_one()
        assert stored.question == "What is this?"
        assert stored.answer == "Answer to: What is this?"
        assert stored.user_id == user.id

    async def test_returns_the_persisted_rows_id(self, client, db_session, chattable, rag):
        """The client keys its optimistic bubble on this id, so it must be the real one."""
        from sqlalchemy import select

        from app.models.chat_message import ChatMessage

        _, repo = chattable

        returned = (await client.post(chat_url(repo), json={"question": "q"})).json()["id"]

        result = await db_session.execute(
            select(ChatMessage).where(ChatMessage.repository_id == repo.id)
        )
        assert str(result.scalar_one().id) == returned

    async def test_sources_survive_a_reload_with_citations_intact(self, client, chattable, rag):
        """
        Sources are stored as JSONB, which is why history reloads with citations. A
        serialization gap here would silently produce citation cards with no text.
        """
        _, repo = chattable
        await client.post(chat_url(repo), json={"question": "q"})

        entry = (await client.get(history_url(repo))).json()[0]

        assert entry["sources"][0]["symbol_name"] == "func_0"
        assert entry["sources"][0]["chunk_text"] == "def f(): pass"


class TestHistoryCapping:
    async def test_forwards_only_the_last_five_messages(self, client, chattable, rag):
        """
        History is capped at 5 *messages*, not 5 exchanges -- so a long session keeps
        roughly two and a half turns. Pinned because the cap is easy to misread.
        """
        _, repo = chattable
        history = [{"role": "user", "content": f"message {i}"} for i in range(8)]

        await client.post(chat_url(repo), json={"question": "latest", "history": history})

        forwarded = rag[0]["history"]
        assert len(forwarded) == 5
        assert [m.content for m in forwarded] == [f"message {i}" for i in range(3, 8)]

    async def test_forwards_nothing_when_no_history_is_sent(self, client, chattable, rag):
        _, repo = chattable

        await client.post(chat_url(repo), json={"question": "q"})

        assert rag[0]["history"] == []

    async def test_passes_the_repository_id(self, client, chattable, rag):
        _, repo = chattable

        await client.post(chat_url(repo), json={"question": "q"})

        assert rag[0]["repository_id"] == repo.id


class TestAskGuards:
    async def test_refuses_a_repository_that_is_not_ready(self, client, db_session, rag):
        """
        400 rather than 409 here -- the chat route and the graph route disagree on the
        code for "not ready", and the client's error handling follows each one.
        """
        user = await make_user(db_session)
        repo = await make_repo(db_session, user, status="parsing")
        await authenticate(client, user)

        response = await client.post(chat_url(repo), json={"question": "q"})

        assert response.status_code == 400
        assert "parsing" in response.json()["detail"]
        assert rag == []

    async def test_another_users_repository_is_not_found(self, client, db_session, rag):
        mine = await make_user(db_session)
        theirs = await make_user(db_session)
        their_repo, _ = await make_ingested_repo(db_session, theirs)
        await authenticate(client, mine)

        response = await client.post(chat_url(their_repo), json={"question": "q"})

        assert response.status_code == 404
        assert rag == []

    async def test_an_unknown_id_is_not_found(self, client, db_session, rag):
        await authenticate(client, await make_user(db_session))

        response = await client.post(
            f"/api/v1/repository/{random_uuid()}/chat", json={"question": "q"}
        )

        assert response.status_code == 404

    async def test_rejects_a_missing_question(self, client, chattable, rag):
        _, repo = chattable

        assert (await client.post(chat_url(repo), json={})).status_code == 422

    async def test_rejects_an_unknown_role_in_history(self, client, chattable, rag):
        _, repo = chattable

        response = await client.post(
            chat_url(repo), json={"question": "q", "history": [{"role": "system", "content": "x"}]}
        )

        assert response.status_code == 422

    async def test_requires_authentication(self, client, chattable, rag):
        _, repo = chattable
        client.cookies.clear()

        assert (await client.post(chat_url(repo), json={"question": "q"})).status_code == 401


class TestHistory:
    async def test_returns_turns_in_chronological_order(self, client, db_session, chattable):
        user, repo = chattable
        for index in range(3):
            await make_chat_message(db_session, repo, user, question=f"question {index}")

        body = (await client.get(history_url(repo))).json()

        assert [m["question"] for m in body] == ["question 0", "question 1", "question 2"]

    async def test_is_empty_for_a_new_repository(self, client, chattable):
        _, repo = chattable

        assert (await client.get(history_url(repo))).json() == []

    async def test_scopes_to_the_calling_user(self, client, db_session, chattable):
        """
        History filters on `user_id` as well as `repository_id`. A second user with rows
        on the same repo (only reachable by direct insert, since the routes scope by
        owner) must not see them.
        """
        user, repo = chattable
        other = await make_user(db_session)
        await make_chat_message(db_session, repo, user, question="mine")
        await make_chat_message(db_session, repo, other, question="theirs")

        body = (await client.get(history_url(repo))).json()

        assert [m["question"] for m in body] == ["mine"]

    async def test_another_users_repository_is_not_found(self, client, db_session):
        mine = await make_user(db_session)
        theirs = await make_user(db_session)
        their_repo, _ = await make_ingested_repo(db_session, theirs)
        await authenticate(client, mine)

        assert (await client.get(history_url(their_repo))).status_code == 404

    async def test_requires_authentication(self, client, chattable):
        _, repo = chattable
        client.cookies.clear()

        assert (await client.get(history_url(repo))).status_code == 401


class TestDeleteMessage:
    async def test_removes_the_turn(self, client, db_session, chattable):
        user, repo = chattable
        message = await make_chat_message(db_session, repo, user)

        response = await client.delete(f"{chat_url(repo)}/{message.id}")

        assert response.status_code == 204
        assert (await client.get(history_url(repo))).json() == []

    async def test_an_unknown_message_is_not_found(self, client, chattable):
        _, repo = chattable

        assert (await client.delete(f"{chat_url(repo)}/{random_uuid()}")).status_code == 404

    async def test_a_message_from_another_repository_is_not_found(
        self, client, db_session, chattable
    ):
        """The message id alone is not enough; it must belong to the repo in the path."""
        user, repo = chattable
        other_repo, _ = await make_ingested_repo(db_session, user, name="other")
        message = await make_chat_message(db_session, other_repo, user)

        response = await client.delete(f"{chat_url(repo)}/{message.id}")

        assert response.status_code == 404

    async def test_another_users_message_is_not_found(self, client, db_session, chattable):
        user, repo = chattable
        other = await make_user(db_session)
        message = await make_chat_message(db_session, repo, other, question="theirs")

        response = await client.delete(f"{chat_url(repo)}/{message.id}")

        assert response.status_code == 404

    async def test_requires_authentication(self, client, chattable):
        _, repo = chattable
        client.cookies.clear()

        assert (await client.delete(f"{chat_url(repo)}/{random_uuid()}")).status_code == 401


class TestClearHistory:
    async def test_removes_every_turn(self, client, db_session, chattable):
        user, repo = chattable
        for index in range(3):
            await make_chat_message(db_session, repo, user, question=f"q{index}")

        response = await client.delete(chat_url(repo))

        assert response.status_code == 204
        assert (await client.get(history_url(repo))).json() == []

    async def test_leaves_other_repositories_alone(self, client, db_session, chattable):
        user, repo = chattable
        other_repo, _ = await make_ingested_repo(db_session, user, name="other")
        await make_chat_message(db_session, repo, user, question="here")
        await make_chat_message(db_session, other_repo, user, question="there")

        await client.delete(chat_url(repo))

        remaining = (await client.get(history_url(other_repo))).json()
        assert [m["question"] for m in remaining] == ["there"]

    async def test_clearing_an_empty_history_is_still_204(self, client, chattable):
        """Idempotent: the client calls this without checking whether anything exists."""
        _, repo = chattable

        assert (await client.delete(chat_url(repo))).status_code == 204

    async def test_is_scoped_to_the_calling_user(self, client, db_session, chattable):
        user, repo = chattable
        other = await make_user(db_session)
        await make_chat_message(db_session, repo, other, question="theirs")

        await client.delete(chat_url(repo))

        from sqlalchemy import select

        from app.models.chat_message import ChatMessage

        result = await db_session.execute(
            select(ChatMessage).where(ChatMessage.repository_id == repo.id)
        )
        assert result.scalars().all() != []  # the other user's row survived

    async def test_requires_authentication(self, client, chattable):
        _, repo = chattable
        client.cookies.clear()

        assert (await client.delete(chat_url(repo))).status_code == 401
