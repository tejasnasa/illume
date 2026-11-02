"""``RetrievalContext`` embeds each distinct text once, in one batch."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.retrieval.channels.base import RetrievalContext

pytestmark = pytest.mark.unit


class _CountingEmbedder:
    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    async def __call__(self, texts):
        self.batches.append(list(texts))
        return [[float(len(text))] for text in texts]


def _context(embedder) -> RetrievalContext:
    # The session is never touched by the embedding cache.
    return RetrievalContext(repository_id=uuid4(), db=None, embed=embedder)  # type: ignore[arg-type]


async def test_prefetch_batches_distinct_texts_once():
    embedder = _CountingEmbedder()
    ctx = _context(embedder)

    await ctx.prefetch_embeddings(["a", "bb", "a"])
    await ctx.prefetch_embeddings(["bb", "ccc"])

    assert embedder.batches == [["a", "bb"], ["ccc"]]
    assert await ctx.embedding("bb") == [2.0]
    assert embedder.batches == [["a", "bb"], ["ccc"]]


async def test_embedding_on_first_use():
    embedder = _CountingEmbedder()
    ctx = _context(embedder)

    assert await ctx.embedding("four") == [4.0]
    assert await ctx.embedding("four") == [4.0]
    assert embedder.batches == [["four"]]


async def test_a_short_answer_from_the_embedder_is_an_error():
    async def short(texts):
        return []

    with pytest.raises(ValueError, match="0 vectors for 1 texts"):
        await _context(short).prefetch_embeddings(["x"])
