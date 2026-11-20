"""The three DeepEval metrics the judge runs, and what each is shown.

``correctness`` is a G-Eval metric with fixed evaluation steps (so there is no step-generation
call) and a 0 to 3 rubric. It sees the question, the answer and a reference answer built from the
repository's own history. ``faithfulness`` checks the answer claim by claim against the evidence it
cited, counting a claim the evidence neither supports nor contradicts as unfaithful.
``answer_relevancy`` checks that the answer addresses the question. None of them is ever shown the
arm, its configuration or the generator model.

Each metric is a :class:`MetricSpec`: its name, the settings it is built from, and how its test
case is made. The settings are the single source of truth for construction and are hashed into the
metric's cache key, so changing a metric's steps, rubric, flags or the way its inputs are rendered
grades that metric again and no other.

Library code here takes nothing from ``evals.settings``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric, GEval
from deepeval.metrics.g_eval.utils import Rubric
from deepeval.test_case import LLMTestCase, SingleTurnParams

from app.services.retrieval.citations import parse_key
from evals.gold.changeset import ANCHOR_SENTENCE
from evals.gold.schema import GoldItem
from evals.metrics.answer import scored_gold
from evals.metrics.citations import cited_keys_of, resolves, seen_keys
from evals.run.deepeval_env import deepeval_version
from evals.run.records import RUBRIC_MAX, Generation

EVIDENCE_CHAR_BUDGET = 6000
"""The most evidence text, in characters, shown to the judge for one answer."""
ANSWER_CHAR_BUDGET = 8000
UNAVAILABLE = "(evidence text unavailable)"
UNMATCHED = "(this key matches nothing the answer's retrieval found)"
NO_EVIDENCE = "(the answer cites no evidence)"

REFERENCE_FORMAT = "1"
"""The version of :func:`reference_answer`'s layout; bump it when the layout changes."""
CONTEXT_FORMAT = "1"
"""The version of :func:`evidence_pieces`'s layout; bump it when the layout changes."""

CORRECTNESS_STEPS: tuple[str, ...] = (
    "Read the Input, which is a question about a software repository, and the Expected Output, "
    "which is the reference answer drawn from the repository's own history together with the "
    "files a correct answer relies on.",
    "List the main points of the Expected Output: what changed or how the code works, and why.",
    "Check each main point against the Actual Output. A point is covered when the Actual Output "
    "says the same thing in different words; vague or generic wording does not cover it.",
    "Check that the Actual Output does not contradict the Expected Output, and that it names the "
    "required files wherever the question asks for files.",
    "Do not reward length, confidence or extra detail the Expected Output does not support. Grade "
    "only what is written, and do not guess who or what wrote the Actual Output.",
)
CORRECTNESS_RUBRIC: tuple[tuple[int, int, str], ...] = (
    (0, 0, "Wrong, off topic or empty, or contradicted by the Expected Output."),
    (
        1,
        1,
        "Partly correct: some of the main point is right, but a key part is missing, vague or "
        "wrong.",
    ),
    (
        2,
        2,
        "Mostly correct: the main point is right; a secondary point is missing or imprecise.",
    ),
    (
        3,
        3,
        "Fully correct: it covers what the Expected Output supports, contradicts nothing in it "
        "and names the required files where files are asked for.",
    ),
)
UNANSWERABLE_TAG = "unanswerable"

EvidenceText = Callable[[str], str | None]
"""Maps a citation key to the text it stands for, or ``None`` when that is not known."""


# --- what the metrics are shown ------------------------------------------------------


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "\n... (truncated)"


def question_of(item: GoldItem) -> str:
    """The question as the answering arms were asked it."""
    return item.question or item.question_seed


def reference_answer(item: GoldItem) -> str:
    """The ``expected_output`` of correctness: what a correct answer says and which files it names.

    For a change item the reference is the pull request's title and description, which the item
    keeps as its question seed (less the sentence that names the anchor file), and any reference
    notes. For any other item it is the item's ``reference_answer`` when it has one, otherwise its
    notes. The files a correct answer relies on follow in every case.

    Args:
        item: The gold item.

    Returns:
        The reference text.
    """
    lines: list[str] = []
    if item.family == "changeset":
        seed = item.question_seed
        if item.anchor_file:
            seed = seed.removesuffix("\n\n" + ANCHOR_SENTENCE.format(path=item.anchor_file))
        lines += ["The pull request that made this change:", seed.strip()]
        if item.gold_answer_notes:
            lines += ["", "Notes:"] + [f"- {note}" for note in item.gold_answer_notes]
    elif item.reference_answer.strip():
        lines += ["Reference answer:", item.reference_answer.strip()]
    else:
        lines += ["Reference notes:"]
        lines += [f"- {note}" for note in item.gold_answer_notes] or ["(none)"]
    lines += ["", "Files a correct answer relies on:"]
    lines += [f"- {path}" for path in sorted(scored_gold(item))] or ["(none)"]
    return "\n".join(lines)


def _label(raw: str) -> str:
    key = parse_key(raw)
    if key is not None and key.kind == "F" and key.path:
        return key.path if key.start is None else f"{key.path}:{key.start}-{key.end}"
    return raw.strip().strip("[]")


def evidence_pieces(
    generation: Generation, evidence_text: EvidenceText, *, budget: int = EVIDENCE_CHAR_BUDGET
) -> list[str]:
    """The evidence an answer cites, one string per piece, each led by its path and line range.

    A cited key that matches nothing the retrieval found, or whose text is not known, is not
    evidence and is left out. The character budget is shared across the keys.

    Args:
        generation: The answer.
        evidence_text: Maps a key to its text.
        budget: The most characters of evidence text to show.

    Returns:
        The pieces; empty when nothing citable could be read.
    """
    cited = cited_keys_of(generation)
    seen = [key for key in (parse_key(k) for k in seen_keys(generation)) if key is not None]
    share = max(200, budget // len(cited)) if cited else 0
    remaining = budget
    pieces: list[str] = []
    for raw in cited:
        parsed = parse_key(raw)
        if parsed is None or not resolves(parsed, seen):
            continue
        text = evidence_text(raw)
        if text is None or not text.strip():
            continue
        body = _truncate(text.strip(), max(0, min(share, remaining)))
        remaining -= len(body)
        pieces.append(f"[{_label(raw)}]\n{body}")
    return pieces


def render_evidence(
    generation: Generation, evidence_text: EvidenceText, *, budget: int = EVIDENCE_CHAR_BUDGET
) -> str:
    """The text of the evidence an answer cites, for a person to read, within a character budget.

    Unlike :func:`evidence_pieces`, a key that matches nothing the retrieval found is flagged as
    such and one whose text is not known is shown as unavailable.

    Args:
        generation: The answer.
        evidence_text: Maps a key to its text.
        budget: The most characters of evidence text to show, shared across the keys.

    Returns:
        One block per cited key, or a note that nothing is cited.
    """
    cited = cited_keys_of(generation)
    if not cited:
        return NO_EVIDENCE
    seen = [key for key in (parse_key(k) for k in seen_keys(generation)) if key is not None]
    share = max(200, budget // len(cited))
    remaining = budget
    blocks: list[str] = []
    for raw in cited:
        parsed = parse_key(raw)
        if parsed is None or not resolves(parsed, seen):
            body = UNMATCHED
        else:
            text = evidence_text(raw)
            if text is None or not text.strip():
                body = UNAVAILABLE
            else:
                body = _truncate(text.strip(), max(0, min(share, remaining)))
                remaining -= len(body)
        blocks.append(f"[{raw}]\n{body}")
    return "\n\n".join(blocks)


def answer_text(generation: Generation) -> str:
    """The answer as the metrics see it: trimmed, never empty and within a character budget."""
    return _truncate(generation.answer.strip() or "(empty)", ANSWER_CHAR_BUDGET)


# --- the metrics ---------------------------------------------------------------------


@dataclass(frozen=True)
class MetricSpec:
    """One judged metric.

    Attributes:
        name: ``correctness``, ``faithfulness`` or ``answer_relevancy``.
        settings: Everything the metric is built from and that shapes its inputs, as plain JSON
            values. Its hash is part of the metric's cache key.
        build: Makes a fresh metric from a judge model and ``settings``; metrics keep state, so
            one is built for every measurement.
        case: Makes the test case from the gold item, the generation and the evidence lookup.
    """

    name: str
    settings: Mapping[str, Any]
    build: Callable[[Any, Mapping[str, Any]], Any]
    case: Callable[[GoldItem, Generation, EvidenceText], LLMTestCase]

    @property
    def settings_hash(self) -> str:
        """A short hash of the settings, stable across processes."""
        return settings_hash(self.settings)


def settings_hash(settings: Mapping[str, Any]) -> str:
    """The first 16 hex digits of the SHA-256 of the canonical JSON of ``settings``."""
    text = json.dumps(settings, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _correctness_settings() -> dict[str, Any]:
    return {
        "metric": "GEval",
        "evaluation_params": ["input", "actual_output", "expected_output"],
        "evaluation_steps": list(CORRECTNESS_STEPS),
        "rubric": [[low, high, outcome] for low, high, outcome in CORRECTNESS_RUBRIC],
        "strict_mode": False,
        "reference_format": REFERENCE_FORMAT,
        "answer_char_budget": ANSWER_CHAR_BUDGET,
    }


def _faithfulness_settings() -> dict[str, Any]:
    return {
        "metric": "FaithfulnessMetric",
        "penalize_ambiguous_claims": True,
        "include_reason": False,
        "truths_extraction_limit": None,
        "strict_mode": False,
        "context_format": CONTEXT_FORMAT,
        "evidence_char_budget": EVIDENCE_CHAR_BUDGET,
        "answer_char_budget": ANSWER_CHAR_BUDGET,
    }


def _relevancy_settings() -> dict[str, Any]:
    return {
        "metric": "AnswerRelevancyMetric",
        "include_reason": False,
        "strict_mode": False,
        "answer_char_budget": ANSWER_CHAR_BUDGET,
    }


def _build_correctness(model: Any, settings: Mapping[str, Any]) -> GEval:
    return GEval(
        name="Correctness",
        evaluation_params=[SingleTurnParams(name) for name in settings["evaluation_params"]],
        evaluation_steps=list(settings["evaluation_steps"]),
        rubric=[
            Rubric(score_range=(low, high), expected_outcome=outcome)
            for low, high, outcome in settings["rubric"]
        ],
        model=model,
        strict_mode=settings["strict_mode"],
        async_mode=True,
        verbose_mode=False,
    )


def _build_faithfulness(model: Any, settings: Mapping[str, Any]) -> FaithfulnessMetric:
    return FaithfulnessMetric(
        model=model,
        include_reason=settings["include_reason"],
        penalize_ambiguous_claims=settings["penalize_ambiguous_claims"],
        truths_extraction_limit=settings["truths_extraction_limit"],
        strict_mode=settings["strict_mode"],
        async_mode=True,
        verbose_mode=False,
    )


def _build_relevancy(model: Any, settings: Mapping[str, Any]) -> AnswerRelevancyMetric:
    return AnswerRelevancyMetric(
        model=model,
        include_reason=settings["include_reason"],
        strict_mode=settings["strict_mode"],
        async_mode=True,
        verbose_mode=False,
    )


def _correctness_case(item: GoldItem, generation: Generation, _: EvidenceText) -> LLMTestCase:
    return LLMTestCase(
        input=question_of(item),
        actual_output=answer_text(generation),
        expected_output=reference_answer(item),
    )


def _faithfulness_case(
    item: GoldItem, generation: Generation, evidence_text: EvidenceText
) -> LLMTestCase:
    return LLMTestCase(
        input=question_of(item),
        actual_output=answer_text(generation),
        retrieval_context=evidence_pieces(generation, evidence_text) or [NO_EVIDENCE],
    )


def _relevancy_case(item: GoldItem, generation: Generation, _: EvidenceText) -> LLMTestCase:
    return LLMTestCase(input=question_of(item), actual_output=answer_text(generation))


def default_metrics() -> tuple[MetricSpec, ...]:
    """The three metrics with their shipped settings."""
    return (
        MetricSpec("correctness", _correctness_settings(), _build_correctness, _correctness_case),
        MetricSpec(
            "faithfulness", _faithfulness_settings(), _build_faithfulness, _faithfulness_case
        ),
        MetricSpec("answer_relevancy", _relevancy_settings(), _build_relevancy, _relevancy_case),
    )


def rubric_value(score: float) -> int | None:
    """The 0 to 3 rubric value a correctness score stands for, or ``None`` if it is not whole."""
    scaled = score * RUBRIC_MAX
    nearest = round(scaled)
    return nearest if abs(scaled - nearest) < 1e-6 else None


def metric_configs(metrics: tuple[MetricSpec, ...] | None = None) -> dict[str, Any]:
    """Each metric's settings and their hashes plus the DeepEval version, for the manifest."""
    chosen = metrics or default_metrics()
    return {
        "deepeval_version": deepeval_version(),
        "metrics": {
            spec.name: {"settings_hash": spec.settings_hash, "settings": dict(spec.settings)}
            for spec in chosen
        },
    }


__all__ = [
    "ANSWER_CHAR_BUDGET",
    "CONTEXT_FORMAT",
    "CORRECTNESS_RUBRIC",
    "CORRECTNESS_STEPS",
    "EVIDENCE_CHAR_BUDGET",
    "NO_EVIDENCE",
    "REFERENCE_FORMAT",
    "UNANSWERABLE_TAG",
    "UNAVAILABLE",
    "UNMATCHED",
    "EvidenceText",
    "MetricSpec",
    "answer_text",
    "default_metrics",
    "evidence_pieces",
    "metric_configs",
    "question_of",
    "reference_answer",
    "render_evidence",
    "rubric_value",
    "settings_hash",
]
