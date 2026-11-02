"""Reranking with the Jev decision model, one ``score`` question per passage.

Jev returns, for each question, the probability-weighted position on an ordered
rubric rather than text. Here the rubric says how well a passage answers the
question, so sorting by that position is the ranking, and a position of ``3.0``
means the model is sure the passage answers it directly.

Requests over about 32,000 bytes of text run in a slower, less accurate
long-context mode, so passages are truncated and a large pool is split into
several requests, each kept under :data:`MAX_REQUEST_BYTES`. The score is an
absolute position on the same rubric, so scores from different requests compare.
"""

from __future__ import annotations

import asyncio

from app.core.config import settings
from app.services.decisions.openrouter import (
    DecisionResponse,
    ScoreAnswer,
    ScoreQuestion,
    submit,
)
from app.services.retrieval.candidate import Candidate
from app.services.retrieval.rerank.base import (
    RerankCall,
    RerankError,
    RerankerUnavailable,
    with_scores,
)

# Pinned, never the ``-latest`` alias: a silent model change would make results
# from different dates incomparable. The response reports the exact snapshot.
JEV_MODEL = "typesafe/jev-1.14"

# Text sent per request, in UTF-8 bytes; above this Jev switches to long-context mode.
MAX_REQUEST_BYTES = 32_000

MAX_PASSAGE_CHARS = 1500
MAX_QUESTION_CHARS = 1000

MAX_PARALLEL_REQUESTS = 4

LEVELS = (
    "unrelated",
    "mentions the topic",
    "partially answers",
    "directly answers",
)

_INSTRUCTIONS = (
    "Rate how well the passage below answers the question in the state. The passage "
    "comes from a code repository.\n\nPassage ({key}):\n{text}"
)


def _size(text: str) -> int:
    return len(text.encode("utf-8"))


def _truncate(text: str, limit: int) -> str:
    """Cuts to ``limit`` characters, marking the cut."""
    return text if len(text) <= limit else text[:limit] + "\n[truncated]"


class JevReranker:
    """Scores every passage against the question and sorts by score.

    The raw response of every request, with the exact model snapshot that
    answered and its cost, is kept on :attr:`calls`.

    Args:
        session_id: Groups the requests in OpenRouter's logs; sent only when given.

    Raises:
        RerankerUnavailable: At construction, when ``OPENROUTER_API_KEY`` is empty.
    """

    kind = "jev"

    def __init__(self, session_id: str | None = None) -> None:
        if not settings.OPENROUTER_API_KEY:
            raise RerankerUnavailable(
                "reranker 'jev' is not available: OPENROUTER_API_KEY is not set"
            )
        self._session_id = session_id
        self.calls: list[RerankCall] = []

    @property
    def total_cost(self) -> float:
        """The summed reported cost of the latest call's requests, in dollars."""
        return sum(call.cost or 0.0 for call in self.calls)

    async def rerank(
        self, question: str, candidates: list[Candidate], top_n: int
    ) -> list[Candidate]:
        """Returns the ``top_n`` highest-scoring candidates.

        Sorted by score, higher first; equal scores keep the fused order they
        came in. ``rerank_score`` is the returned score.

        Raises:
            DecisionError: When a request fails; the message says how.
            RerankError: When a response lacks an answer for a passage.
        """
        self.calls = []
        if not candidates:
            return []

        state = f"Question about a code repository:\n{_truncate(question, MAX_QUESTION_CHARS)}"
        batches = self._batches(state, candidates)
        gate = asyncio.Semaphore(MAX_PARALLEL_REQUESTS)

        async def send(number: int, batch: dict[str, ScoreQuestion]) -> DecisionResponse:
            async with gate:
                response = await submit(state, batch, model=JEV_MODEL, session_id=self._session_id)
            self.calls.append(
                RerankCall(
                    provider="jev",
                    model=response.model,
                    cost=response.cost,
                    detail={
                        "requested_model": JEV_MODEL,
                        "batch": number,
                        "questions": len(batch),
                    },
                    response=response.raw,
                )
            )
            return response

        responses = await asyncio.gather(*(send(n, batch) for n, batch in enumerate(batches)))

        scores: dict[int, float] = {}
        for response in responses:
            for name, answer in response.answers.items():
                if not isinstance(answer, ScoreAnswer):
                    raise RerankError(f"the answer to {name!r} was not a score")
                scores[int(name[1:])] = answer.score
        if len(scores) != len(candidates):
            raise RerankError(f"jev scored {len(scores)} of {len(candidates)} passages")

        order = sorted(range(len(candidates)), key=lambda index: (-scores[index], index))[:top_n]
        return with_scores([candidates[i] for i in order], [scores[i] for i in order])

    @staticmethod
    def _batches(state: str, candidates: list[Candidate]) -> list[dict[str, ScoreQuestion]]:
        """Packs one question per passage, in fused order, into requests under the budget.

        Questions are named ``p<position in the pool>``. A request holds the
        state and, per question, its instructions and rubric; a passage that
        would push it past :data:`MAX_REQUEST_BYTES` starts a new request.
        """
        rubric = sum(_size(level) for level in LEVELS)
        batches: list[dict[str, ScoreQuestion]] = []
        current: dict[str, ScoreQuestion] = {}
        used = _size(state)
        for index, candidate in enumerate(candidates):
            instructions = _INSTRUCTIONS.format(
                key=candidate.key, text=_truncate(candidate.text, MAX_PASSAGE_CHARS)
            )
            cost = _size(instructions) + rubric + _size(f"p{index}")
            if current and used + cost > MAX_REQUEST_BYTES:
                batches.append(current)
                current, used = {}, _size(state)
            current[f"p{index}"] = ScoreQuestion(instructions=instructions, criteria=LEVELS)
            used += cost
        if current:
            batches.append(current)
        return batches
