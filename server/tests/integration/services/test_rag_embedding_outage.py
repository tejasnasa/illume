"""An embedding outage reaches the chat route as the provider's own error.

The chat route maps OpenAI errors to a 502. If retrieval swallowed a failed
query embedding, the user would instead be told that nothing in the repository
matches, which is wrong and hides the outage.
"""

from __future__ import annotations

import httpx
import pytest
from openai import APIConnectionError

from app.services import rag
from tests.factories import make_repo, make_user

pytestmark = pytest.mark.integration


async def test_a_failed_query_embedding_raises_the_original_error(db_session, monkeypatch):
    user = await make_user(db_session)
    repo = await make_repo(db_session, user)

    async def unreachable(client, query):
        raise APIConnectionError(
            request=httpx.Request("POST", "https://api.openai.com/v1/embeddings")
        )

    monkeypatch.setattr(rag, "_embed_query", unreachable)

    with pytest.raises(APIConnectionError):
        await rag.answer_question("where is login handled?", repo.id, db_session)
