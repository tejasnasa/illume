"""The reranker registry: the identity reranker, and the seam later kinds plug into."""

from __future__ import annotations

import pytest

from app.services.retrieval.candidate import Candidate
from app.services.retrieval.rerank import NoneReranker, RerankerUnavailable, get_reranker
from app.services.retrieval.resolve import SourceReference

pytestmark = pytest.mark.unit


def _candidates(count: int) -> list[Candidate]:
    return [
        Candidate(
            key=f"k{i}",
            reference=SourceReference(source_type="file", chunk_text=str(i), file_path=f"f{i}"),
            text=str(i),
        )
        for i in range(count)
    ]


async def test_none_keeps_the_order_and_cuts_to_top_n():
    candidates = _candidates(5)
    kept = await NoneReranker().rerank("q", candidates, 3)
    assert kept == candidates[:3]


async def test_none_returns_everything_when_top_n_is_larger():
    candidates = _candidates(2)
    assert await get_reranker("none").rerank("q", candidates, 10) == candidates


@pytest.mark.parametrize("kind", ["cohere", "llm", "jev", "nonsense"])
def test_kinds_without_an_implementation_are_unavailable(kind):
    with pytest.raises(RerankerUnavailable, match="not available"):
        get_reranker(kind)
