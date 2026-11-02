"""Reranking with Cohere's rerank endpoint."""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.services.retrieval.candidate import Candidate
from app.services.retrieval.rerank.base import (
    RerankCall,
    RerankError,
    RerankerUnavailable,
    with_scores,
)

COHERE_RERANK_URL = "https://api.cohere.com/v2/rerank"
COHERE_MODEL = "rerank-v3.5"

# Longer documents are cut, not skipped: the start of a chunk carries its path
# and name, which is most of what the reranker needs.
MAX_DOCUMENT_CHARS = 4000

REQUEST_TIMEOUT_SECONDS = 30.0


class CohereReranker:
    """Scores every candidate against the question with ``rerank-v3.5``.

    The raw response of the request is kept on :attr:`calls`.

    Raises:
        RerankerUnavailable: At construction, when ``COHERE_API_KEY`` is empty.
    """

    kind = "cohere"

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key if api_key is not None else settings.COHERE_API_KEY
        if not key:
            raise RerankerUnavailable(
                "reranker 'cohere' is not available: COHERE_API_KEY is not set"
            )
        self._api_key = key
        self.calls: list[RerankCall] = []

    async def rerank(
        self, question: str, candidates: list[Candidate], top_n: int
    ) -> list[Candidate]:
        """Returns the ``top_n`` candidates Cohere rates most relevant.

        Raises:
            RerankError: On a non-success status, a timeout, or a response
                whose results are not usable.
        """
        self.calls = []
        if not candidates:
            return []

        wanted = min(top_n, len(candidates))
        body = {
            "model": COHERE_MODEL,
            "query": question,
            "documents": [candidate.text[:MAX_DOCUMENT_CHARS] for candidate in candidates],
            "top_n": wanted,
        }
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    COHERE_RERANK_URL,
                    json=body,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
        except httpx.TimeoutException:
            raise RerankError(
                f"cohere rerank timed out after {REQUEST_TIMEOUT_SECONDS:g} seconds"
            ) from None
        except httpx.HTTPError as error:
            raise RerankError(
                f"cohere rerank failed: {type(error).__name__}: {error}"[:300]
            ) from None

        if response.status_code >= 400:
            raise RerankError(
                f"cohere rerank failed with status {response.status_code}: "
                f"{response.text[:200].strip()}"
            )
        try:
            payload = response.json()
        except ValueError:
            raise RerankError("cohere rerank returned a body that was not JSON") from None
        self.calls.append(
            RerankCall(
                provider="cohere",
                model=COHERE_MODEL,
                cost=None,
                detail={"documents": len(candidates), "top_n": wanted},
                response=payload,
            )
        )

        ordered, scores = self._parse(payload, candidates)
        return with_scores(ordered[:wanted], scores[:wanted])

    @staticmethod
    def _parse(payload: Any, candidates: list[Candidate]) -> tuple[list[Candidate], list[float]]:
        """Candidates and scores in the response's order, highest score first.

        An index outside the pool or repeated is ignored. The sort is stable, so
        equal scores keep the order the provider returned them in.

        Raises:
            RerankError: When the body has no usable ``results``.
        """
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise RerankError("cohere rerank returned no 'results' list")

        seen: set[int] = set()
        rows: list[tuple[int, float]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            index, score = item.get("index"), item.get("relevance_score")
            if isinstance(index, bool) or not isinstance(index, int):
                continue
            if isinstance(score, bool) or not isinstance(score, int | float):
                continue
            if not 0 <= index < len(candidates) or index in seen:
                continue
            seen.add(index)
            rows.append((index, float(score)))
        if not rows:
            raise RerankError("cohere rerank returned no usable results")

        rows.sort(key=lambda row: -row[1])
        return [candidates[index] for index, _ in rows], [score for _, score in rows]
