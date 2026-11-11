"""The reranker contract, the identity reranker, and the registry that builds them."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Protocol

from app.services.llm_config import LLMConfig
from app.services.retrieval.candidate import Candidate


class RerankerUnavailable(RuntimeError):
    """The requested reranker kind has no implementation or is not configured."""


class RerankError(RuntimeError):
    """A reranker call that failed or returned something unusable."""


@dataclass(frozen=True)
class RerankCall:
    """One provider request a reranker made, kept for the log.

    Attributes:
        provider: Who answered: ``cohere``, ``llm`` or ``jev``.
        model: The model that answered. For ``jev`` this is the exact snapshot
            the response reported, not the pinned id that was asked for.
        cost: The reported cost in dollars, when the provider reports one.
        detail: What the request covered, such as the window or batch number.
        response: The provider's response body as received (parsed JSON).
    """

    provider: str
    model: str | None
    cost: float | None
    detail: dict[str, Any]
    response: Any

    def to_dict(self) -> dict[str, Any]:
        """The record as a JSON-serialisable dict."""
        return {
            "provider": self.provider,
            "model": self.model,
            "cost": self.cost,
            "detail": self.detail,
            "response": self.response,
        }


class Reranker(Protocol):
    """Reorders a fused candidate pool by relevance to the question.

    Attributes:
        kind: The :class:`~app.services.retrieval.config.RerankConfig` kind.
        calls: The provider requests made by the latest :meth:`rerank`, raw
            responses included. Reset at the start of every call and filled as
            requests complete, so it is still readable after a failure.
    """

    kind: str
    calls: list[RerankCall]

    async def rerank(
        self, question: str, candidates: list[Candidate], top_n: int
    ) -> list[Candidate]:
        """Returns up to ``top_n`` candidates, most relevant first.

        Implementations set ``rerank_score`` on what they return. Any exception
        is treated by the pipeline as a reranker failure and degrades to the
        fused order, so implementations need not catch their own errors.
        """
        ...


class NoneReranker:
    """Keeps the fused order and returns the first ``top_n``."""

    kind = "none"

    def __init__(self) -> None:
        self.calls: list[RerankCall] = []

    async def rerank(
        self, question: str, candidates: list[Candidate], top_n: int
    ) -> list[Candidate]:
        """Returns ``candidates[:top_n]`` unchanged."""
        return list(candidates[:top_n])


def with_scores(ordered: list[Candidate], scores: list[float]) -> list[Candidate]:
    """Copies of ``ordered`` with ``rerank_score`` set from the parallel ``scores``."""
    return [
        replace(candidate, rerank_score=score)
        for candidate, score in zip(ordered, scores, strict=True)
    ]


def position_scores(count: int, pool: int) -> list[float]:
    """Scores that fall with final position: ``1 - position / pool`` from the top.

    The best candidate scores ``1.0`` and the last of a pool of ``pool`` scores
    ``1 / pool``, so scores from rerankers that only produce an order stay
    comparable to each other and strictly decreasing.
    """
    return [1.0 - position / pool for position in range(count)]


def get_reranker(kind: str, *, llm: LLMConfig | None = None) -> Reranker:
    """The reranker for ``kind``.

    Each additional kind registers here with its own branch, so the pipeline
    never needs to know which ones exist. Implementations are imported inside
    the branch because they import this module.

    Args:
        kind: A :attr:`RerankConfig.kind <app.services.retrieval.config.RerankConfig.kind>`.
        llm: The caller's generation credential, for kinds that call a model.
            ``llm`` kind falls back to the server's free-tier credential.

    Raises:
        RerankerUnavailable: When the kind has no implementation, or its key
            is not configured.
    """
    if kind == "none":
        return NoneReranker()
    if kind == "cohere":
        from app.services.retrieval.rerank.cohere import CohereReranker

        return CohereReranker()
    if kind == "llm":
        from app.services.retrieval.rerank.llm import LLMReranker

        resolved = llm if llm is not None else LLMConfig.server_default()
        if resolved is None:
            raise RerankerUnavailable("reranker 'llm' is not available: no model credential")
        return LLMReranker(resolved)
    if kind == "jev":
        from app.services.retrieval.rerank.jev import JevReranker

        return JevReranker()
    raise RerankerUnavailable(f"reranker {kind!r} is not available")
