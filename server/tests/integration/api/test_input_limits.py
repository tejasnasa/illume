"""Input size limits on the chat and stream routes.

A question, the number of prior turns and the length of each turn are bounded for
every caller. Just over a limit is a 422 before anything runs; exactly at it is
accepted.
"""

from __future__ import annotations

import pytest

from app.api.validation import (
    MAX_HISTORY_CONTENT_CHARS,
    MAX_HISTORY_ITEMS,
    MAX_QUESTION_CHARS,
)
from app.services.rag import RAGResponse
from tests.factories import make_ingested_repo, make_user
from tests.fixtures.agent_stream import AnyModel, install, make_world, runs_of, stream_url
from tests.helpers import authenticate

pytestmark = pytest.mark.integration


def turns(count: int, content: str = "earlier") -> list[dict]:
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": content} for i in range(count)
    ]


@pytest.fixture
def no_model_backed_stages(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")


class TestChatRoute:
    @pytest.fixture
    async def chattable(self, client, db_session, monkeypatch):
        async def fake_answer(query, repository_id, db, history=None, *, llm=None):
            return RAGResponse(answer="ok", sources=[])

        import app.api.v1.chat as chat_module

        monkeypatch.setattr(chat_module, "answer_question", fake_answer)
        user = await make_user(db_session, ai_api_key="sk-test")
        repo, _ = await make_ingested_repo(db_session, user)
        await authenticate(client, user)
        return f"/api/v1/repository/{repo.id}/chat"

    async def test_a_question_at_the_limit_is_accepted(self, client, chattable):
        response = await client.post(chattable, json={"question": "x" * MAX_QUESTION_CHARS})

        assert response.status_code == 200

    async def test_a_question_over_the_limit_is_refused(self, client, chattable):
        response = await client.post(chattable, json={"question": "x" * (MAX_QUESTION_CHARS + 1)})

        assert response.status_code == 422

    async def test_history_at_the_limit_is_accepted(self, client, chattable):
        response = await client.post(
            chattable, json={"question": "q", "history": turns(MAX_HISTORY_ITEMS)}
        )

        assert response.status_code == 200

    async def test_history_over_the_limit_is_refused(self, client, chattable):
        response = await client.post(
            chattable, json={"question": "q", "history": turns(MAX_HISTORY_ITEMS + 1)}
        )

        assert response.status_code == 422

    async def test_a_history_turn_at_the_limit_is_accepted(self, client, chattable):
        history = turns(1, "y" * MAX_HISTORY_CONTENT_CHARS)

        response = await client.post(chattable, json={"question": "q", "history": history})

        assert response.status_code == 200

    async def test_a_history_turn_over_the_limit_is_refused(self, client, chattable):
        history = turns(1, "y" * (MAX_HISTORY_CONTENT_CHARS + 1))

        response = await client.post(chattable, json={"question": "q", "history": history})

        assert response.status_code == 422


class TestStreamRoute:
    @pytest.fixture
    async def world(self, client, db_session, app, no_model_backed_stages):
        world = await make_world(client, db_session)
        install(app, db_session, AnyModel())
        return world

    async def post(self, client, world, **body):
        return await client.post(
            stream_url(world.repo), json={"preset": "classic", "question": "q", **body}
        )

    async def test_a_question_at_the_limit_is_accepted(self, client, world):
        response = await self.post(client, world, question="x" * MAX_QUESTION_CHARS)

        assert response.status_code == 200

    async def test_a_question_over_the_limit_is_refused_and_no_run_starts(
        self, client, db_session, world
    ):
        response = await self.post(client, world, question="x" * (MAX_QUESTION_CHARS + 1))

        assert response.status_code == 422
        assert await runs_of(db_session, world.repo) == []

    async def test_history_at_the_limit_is_accepted(self, client, world):
        response = await self.post(client, world, history=turns(MAX_HISTORY_ITEMS))

        assert response.status_code == 200

    async def test_history_over_the_limit_is_refused(self, client, world):
        response = await self.post(client, world, history=turns(MAX_HISTORY_ITEMS + 1))

        assert response.status_code == 422

    async def test_a_history_turn_at_the_limit_is_accepted(self, client, world):
        response = await self.post(client, world, history=turns(1, "y" * MAX_HISTORY_CONTENT_CHARS))

        assert response.status_code == 200

    async def test_a_history_turn_over_the_limit_is_refused(self, client, world):
        response = await self.post(
            client, world, history=turns(1, "y" * (MAX_HISTORY_CONTENT_CHARS + 1))
        )

        assert response.status_code == 422
