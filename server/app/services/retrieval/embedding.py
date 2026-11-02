"""The production query embedder.

Query vectors must come from the same model as the stored chunk vectors, so this
uses ``text-embedding-3-small`` on the operator's key, exactly as indexing does.
The client is built without ``base_url``: the SDK then reads ``OPENAI_BASE_URL``
from the environment, which is how the end-to-end suite reaches its stub.
"""

from __future__ import annotations

from collections.abc import Sequence

from openai import AsyncOpenAI

from app.core.config import settings

EMBEDDING_MODEL = "text-embedding-3-small"


async def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """Embeds a batch of query texts in one request, preserving input order."""
    if not texts:
        return []
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    response = await client.embeddings.create(model=EMBEDDING_MODEL, input=list(texts))
    ordered = sorted(response.data, key=lambda item: item.index)
    return [item.embedding for item in ordered]
