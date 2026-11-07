"""Checking a finished answer's citations against the evidence it gathered.

Every sentence that makes a claim is split out, its keys are matched against the
evidence the run actually retrieved, and every (claim, key) pair is put to the
decision model in one batched request. A key the run never retrieved never
reaches the model: it is ``unresolved_key`` by construction, whatever a decider
would have said.

The judgement per claim follows a fixed precedence:

* any cited evidence contradicts the claim: ``contradicted``;
* any cited evidence supports the claim: ``supported``;
* otherwise any cited evidence partially supports it: ``partially_supported``;
* otherwise the evidence was retrieved but does not establish it: ``unsupported``;
* no cited key was retrieved at all: ``unresolved_key``.

A decision failure is not a reason to trust the answer. When the batched request
raises, or a result is a placeholder for unusable output, the claim is judged
unsupported, so the failure can only add repair work, never hide a bad citation.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.agent.claims import ClaimSpan, mark_answer, mark_for, split_claims
from app.services.agent.state import (
    ClaimCheck,
    ClaimVerdict,
    Evidence,
    VerificationReport,
    match_evidence,
)
from app.services.decisions import (
    ChoiceResult,
    CitationVerdict,
    Decider,
    Question,
    RecordDecision,
    Result,
    record_decision,
)
from app.services.decisions.points import citation_question, citation_state, citation_verdict
from app.services.retrieval.citations import parse_key

if TYPE_CHECKING:
    from app.services.agent.deps import AgentDeps

logger = logging.getLogger(__name__)

_BATCH_STATE = "Citation support for the claims in one answer about a code repository."

_CITATION_VERDICTS: dict[CitationVerdict, ClaimVerdict] = {
    CitationVerdict.SUPPORTS: ClaimVerdict.SUPPORTED,
    CitationVerdict.PARTIALLY_SUPPORTS: ClaimVerdict.PARTIALLY_SUPPORTED,
    CitationVerdict.DOES_NOT_SUPPORT: ClaimVerdict.UNSUPPORTED,
    CitationVerdict.CONTRADICTS: ClaimVerdict.CONTRADICTED,
}


@dataclass(frozen=True)
class _Pair:
    """One (claim, key) pair and the question asked about it."""

    span: ClaimSpan
    key: str
    evidence_key: str
    question: str


def _verdict(result: Result | None) -> ClaimVerdict:
    """The claim verdict for one decider answer, failing safe on anything unusable."""
    if not isinstance(result, ChoiceResult):
        return ClaimVerdict.UNSUPPORTED
    return _CITATION_VERDICTS[citation_verdict(result)]


def _probability(result: Result | None, verdict: ClaimVerdict) -> float | None:
    """The reported probability of the winning verdict, when there is one."""
    if not isinstance(result, ChoiceResult):
        return None
    option = next(
        (item.value for item, claimed in _CITATION_VERDICTS.items() if claimed is verdict), None
    )
    if option is None:
        return None
    return result.probabilities.get(option)


def _claim_verdict(verdicts: list[ClaimVerdict]) -> ClaimVerdict:
    """One verdict for a claim from the verdicts on its keys."""
    if ClaimVerdict.CONTRADICTED in verdicts:
        return ClaimVerdict.CONTRADICTED
    if ClaimVerdict.SUPPORTED in verdicts:
        return ClaimVerdict.SUPPORTED
    if ClaimVerdict.PARTIALLY_SUPPORTED in verdicts:
        return ClaimVerdict.PARTIALLY_SUPPORTED
    return ClaimVerdict.UNSUPPORTED


async def verify_answer(
    answer: str,
    evidence: Mapping[str, Evidence],
    decider: Decider,
    *,
    record: RecordDecision | None = None,
) -> VerificationReport:
    """Judges every claim in ``answer`` against the evidence the run retrieved.

    One batched decision request covers every (claim, key) pair whose key was
    retrieved. A key that matches nothing is unresolved without asking anyone.
    A failed or unusable decision marks the claim unsupported rather than
    dropping it.

    Args:
        answer: The finished answer.
        evidence: Everything the run retrieved, by citation key.
        decider: Who judges citation support.
        record: Where decision records go, when the caller keeps them.

    Returns:
        The per-claim verdicts, the uncited factual sentences, and whether the
        decision model's answers had to be defaulted.
    """
    spans = split_claims(answer)
    if not spans:
        return VerificationReport()

    pairs: list[_Pair] = []
    questions: dict[str, Question] = {}
    for span in spans:
        if span.uncited:
            continue
        for raw in span.keys:
            parsed = parse_key(raw)
            matched = match_evidence(parsed, evidence) if parsed is not None else None
            if matched is None:
                continue
            name = f"claim{span.index}_key{len(questions)}"
            pairs.append(_Pair(span=span, key=raw, evidence_key=matched, question=name))
            questions[name] = citation_question(span.text, matched, evidence[matched].text)

    answers: Mapping[str, Result] = {}
    defaulted = False
    if questions:
        try:
            answers = await decider.batch(_BATCH_STATE, questions)
        except Exception as error:  # a decision outage must not trust the answer
            defaulted = True
            reason = f"{type(error).__name__}: {error}"[:300]
            logger.warning("citation verification fell back to unsupported: %s", reason)

    for pair in pairs:
        result = answers.get(pair.question)
        if result is not None and record is not None:
            await record_decision(
                record,
                "citation_support",
                citation_state(pair.span.text, pair.evidence_key, evidence[pair.evidence_key].text),
                result,
            )
        if result is not None and result.defaulted:
            defaulted = True

    by_span: dict[int, list[tuple[_Pair, ClaimVerdict]]] = {span.index: [] for span in spans}
    unresolved_by_span: dict[int, list[str]] = {span.index: [] for span in spans}
    for span in spans:
        if span.uncited:
            continue
        for raw in span.keys:
            parsed = parse_key(raw)
            if parsed is None or match_evidence(parsed, evidence) is None:
                unresolved_by_span[span.index].append(raw)
    for pair in pairs:
        by_span[pair.span.index].append((pair, _verdict(answers.get(pair.question))))

    checks: list[ClaimCheck] = []
    for span in spans:
        if span.uncited:
            continue
        judged = by_span[span.index]
        if not judged:
            checks.append(
                ClaimCheck(
                    index=span.index,
                    claim=span.text,
                    keys=(),
                    unresolved=tuple(unresolved_by_span[span.index]),
                    verdict=ClaimVerdict.UNRESOLVED_KEY,
                )
            )
            continue
        verdict = _claim_verdict([claim_verdict for _, claim_verdict in judged])
        winner = next((pair for pair, judged_verdict in judged if judged_verdict is verdict), None)
        checks.append(
            ClaimCheck(
                index=span.index,
                claim=span.text,
                keys=tuple(dict.fromkeys(pair.evidence_key for pair, _ in judged)),
                unresolved=tuple(unresolved_by_span[span.index]),
                verdict=verdict,
                probability=(
                    _probability(answers.get(winner.question), verdict)
                    if winner is not None
                    else None
                ),
            )
        )

    return VerificationReport(
        claims=tuple(checks),
        uncited=tuple(span.text for span in spans if span.uncited),
        defaulted=defaulted,
    )


def finalize_answer(answer: str, report: VerificationReport) -> str:
    """The answer with every claim's verdict marked, and nothing removed.

    Args:
        answer: The answer that was verified.
        report: What the verifier found.
    """
    verdicts = {claim.index: claim.verdict for claim in report.claims}
    uncited = set(report.uncited)
    marks: dict[int, str] = {}
    for span in split_claims(answer):
        if span.index in verdicts:
            marks[span.index] = mark_for(verdicts[span.index])
        elif span.uncited and span.text in uncited:
            marks[span.index] = mark_for(None)
    if not marks:
        return answer
    return mark_answer(answer, split_claims(answer), marks)


def build_verifier(deps: AgentDeps):
    """The run's citation verifier, bound to its decider and step log."""
    decider = deps.decider
    record = deps.decision_sink("verify")

    async def verifier(state):
        if decider is None or not state["answer"]:
            return None
        return await verify_answer(state["answer"], state["evidence"], decider, record=record)

    return verifier
