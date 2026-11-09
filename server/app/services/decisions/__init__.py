"""The decision layer: one typed interface, a decision model and an LLM stand-in.

``base`` holds the contract and the fallback between implementations, ``jev``
asks OpenRouter's Decisions API, ``llm`` asks the caller's model for its own
probability, and ``points`` holds the six decisions the pipeline makes together
with the wording and thresholds each uses.
"""

from __future__ import annotations

from app.services.decisions.base import (
    NOUL_FALSE,
    NOUL_TRUE,
    ChoiceResult,
    Decider,
    DeciderUnavailable,
    DecisionRecord,
    DecisionResult,
    FallbackDecider,
    NoulResult,
    RecordDecision,
    Result,
    ScoreResult,
    get_decider,
    make_record,
    record_decision,
    state_bytes,
    state_hash,
)
from app.services.decisions.jev import JevDecider
from app.services.decisions.llm import LlmDecider
from app.services.decisions.openrouter import (
    DECISIONS_URL,
    JEV_MODEL,
    MAX_REQUEST_BYTES,
    Answer,
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionError,
    DecisionResponse,
    DecisionUnavailable,
    NoulAnswer,
    NoulQuestion,
    Question,
    ScoreAnswer,
    ScoreQuestion,
    submit,
)
from app.services.decisions.points import (
    RELEVANCE_LEVELS,
    ROUTE_CONFIDENCE,
    ROUTE_OPTIONS,
    PlanDecision,
    RelevanceDecision,
    Route,
    RouteDecision,
    decide_plan,
    decide_relevance,
    decide_route,
)

__all__ = [
    "DECISIONS_URL",
    "JEV_MODEL",
    "MAX_REQUEST_BYTES",
    "NOUL_FALSE",
    "NOUL_TRUE",
    "RELEVANCE_LEVELS",
    "ROUTE_CONFIDENCE",
    "ROUTE_OPTIONS",
    "Answer",
    "ChoiceAnswer",
    "ChoiceQuestion",
    "ChoiceResult",
    "Decider",
    "DeciderUnavailable",
    "DecisionError",
    "DecisionRecord",
    "DecisionResponse",
    "DecisionResult",
    "DecisionUnavailable",
    "FallbackDecider",
    "JevDecider",
    "LlmDecider",
    "NoulAnswer",
    "NoulQuestion",
    "NoulResult",
    "PlanDecision",
    "Question",
    "RecordDecision",
    "RelevanceDecision",
    "Result",
    "Route",
    "RouteDecision",
    "ScoreAnswer",
    "ScoreQuestion",
    "ScoreResult",
    "decide_plan",
    "decide_relevance",
    "decide_route",
    "get_decider",
    "make_record",
    "record_decision",
    "state_bytes",
    "state_hash",
    "submit",
]
