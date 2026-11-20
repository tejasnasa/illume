"""The judge pass: grade recorded answers against the gold notes, resumably and on a budget.

A judge sees the question, the reference notes quoted from the repository's own history, the gold
files, the answer and the text of the evidence the answer cites. It never sees which arm, which
configuration or which model produced the answer. It returns ``{correct, faithful, abstained,
rationale}``.

Judgments are appended to a JSONL file per judge identity and are keyed by the generation, the
prompt version, the judge model and the judge host, so changing any of those grades again while
leaving ``generations.jsonl`` untouched. Output that cannot be used (not JSON, a score out of
range, a missing field) is stored as an error record with the raw text and is tried again on the
next run; it is never scored.

Two transports are supported: the Responses API with a strict JSON schema, and chat completions
asked for a JSON object.

Library code here takes nothing from ``evals.settings``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

from openai import AsyncOpenAI, BadRequestError

from app.services.retrieval.citations import parse_key
from app.services.retrieval.llm_json import ModelFailure, parse_json, text_format
from evals.gold.schema import GoldItem
from evals.metrics.answer import scored_gold
from evals.metrics.citations import cited_keys_of, resolves, seen_keys
from evals.run.budget import Budget, BudgetStop, UnpricedSpend
from evals.run.endpoint import JudgeEndpoint
from evals.run.generate import final_records
from evals.run.metering import Meter, usage_from_response
from evals.run.pricing import PriceTable
from evals.run.records import Generation, JudgeVersion, Judgment, Usage, judgment_key

JUDGE_VERSION = "1"
"""The version of the judge's prompt and output schema; bump it when either changes."""

CHANGESET_FRACTION = 0.2
EVIDENCE_CHAR_BUDGET = 6000
"""The most evidence text, in characters, shown to the judge for one answer."""
ANSWER_CHAR_BUDGET = 8000
CALL_TIMEOUT_SECONDS = 180.0
UNAVAILABLE = "(evidence text unavailable)"
UNMATCHED = "(this key matches nothing the answer's retrieval found)"
NO_EVIDENCE = "(the answer cites no evidence)"

EvidenceText = Callable[[str], str | None]
"""Maps a citation key to the text it stands for, or ``None`` when that is not known."""

ClientFactory = Callable[..., Any]

JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "correct": {"type": "integer", "enum": [0, 1, 2, 3]},
        "faithful": {"type": "integer", "enum": [0, 1, 2, 3]},
        "abstained": {"type": "boolean"},
        "rationale": {"type": "string"},
    },
    "required": ["correct", "faithful", "abstained", "rationale"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
You grade one answer to a question about a software repository. You are given the question, \
reference notes quoted from the repository's own pull requests and commits, the files a correct \
answer relies on, the answer under review, and the text of the evidence the answer cites. Grade \
only what is written. Do not guess who or what wrote the answer.

correct (0 to 3): does the answer say what the reference notes and the listed files say?
  3  fully correct: it covers what the notes support, contradicts nothing in them, and names the \
required files where files are asked for.
  2  mostly correct: the main point is right; a secondary point is missing or imprecise.
  1  partly correct: some of the main point is right, but a key part is missing, vague or wrong.
  0  wrong, off topic, empty, or contradicted by the notes.

faithful (0 to 3): is every claim in the answer supported by the evidence it cites (or, where \
nothing is cited, by the reference notes)?
  3  every claim is supported and each citation points at text that says what the answer says.
  2  nearly all claims are supported; one minor claim is unsupported or a citation is loose.
  1  several claims are unsupported, or the citations do not back them.
  0  mostly invented, or the citations point at evidence that is missing or says something else.
  An answer that cites nothing is judged against the notes alone and scores at most 2.

abstained: true when the answer declines to answer or says the repository does not contain \
what was asked; false when it commits to an answer.

Some questions cannot be answered from the repository; the question will say so. For such a \
question, abstaining is the correct answer: give correct 3 and faithful 3 to an answer that says \
the repository does not contain it and invents nothing. Give correct 0 to an answer that commits \
to an invented answer. For a question that can be answered, an answer that abstains is not \
correct: give it correct 0.

Keep the rationale to a few sentences that name the facts you relied on."""

_JSON_SUFFIX = (
    "\n\nReply with only one JSON object and no other text, with exactly these fields: "
    '"correct" (integer 0 to 3), "faithful" (integer 0 to 3), "abstained" (true or false) and '
    '"rationale" (string). The JSON schema is:\n'
)


class JudgePrompt(NamedTuple):
    """The two messages sent to the judge."""

    system: str
    user: str

    @property
    def text(self) -> str:
        """Both messages, for inspection."""
        return f"{self.system}\n\n{self.user}"


class JudgeOutputError(ValueError):
    """The judge's output is not a usable grade."""


@dataclass(frozen=True)
class JudgePair:
    """One generation to grade, with the gold item it answers.

    Attributes:
        item: The gold item.
        generation: The recorded answer.
    """

    item: GoldItem
    generation: Generation


@dataclass(frozen=True)
class Verdict:
    """A validated grade."""

    correct: int
    faithful: int
    abstained: bool
    rationale: str


# --- the prompt ----------------------------------------------------------------------


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "\n... (truncated)"


def render_evidence(
    generation: Generation, evidence_text: EvidenceText, *, budget: int = EVIDENCE_CHAR_BUDGET
) -> str:
    """The text of the evidence an answer cites, within a fixed character budget.

    A cited key that matches nothing the retrieval found is flagged as such, since the judge
    should weigh that; a key whose text is not known is shown as unavailable.

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


def judge_prompt(
    item: GoldItem, generation: Generation, *, evidence_text: EvidenceText | None = None
) -> JudgePrompt:
    """The messages that ask the judge to grade one answer.

    The prompt carries the question, the reference notes, the gold files (and the acceptable
    ones for a hand item), the answer and its cited evidence. It carries nothing that identifies
    the arm, its configuration or the generator model.

    Args:
        item: The gold item.
        generation: The answer to grade.
        evidence_text: Maps a citation key to its text; every key is unavailable when omitted.

    Returns:
        The system and user messages.
    """
    lookup: EvidenceText = evidence_text or (lambda key: None)
    unanswerable = "unanswerable" in item.tags
    required = sorted(scored_gold(item))
    lines = ["Question:", item.question or item.question_seed, ""]
    if unanswerable:
        lines += [
            "This question cannot be answered from the repository; declining to answer is "
            "the correct response.",
            "",
        ]
    if item.anchor_file:
        lines += [f"The question names this file as its starting point: {item.anchor_file}", ""]
    lines.append("Reference notes:")
    lines += [f"- {note}" for note in item.gold_answer_notes] or ["(none)"]
    lines += ["", "Files a correct answer relies on:"]
    lines += [f"- {path}" for path in required] or ["(none)"]
    if item.acceptable_files:
        lines += ["", "Other files that are also acceptable:"]
        lines += [f"- {path}" for path in item.acceptable_files]
    lines += [
        "",
        "Answer under review:",
        "<<<",
        _truncate(generation.answer.strip() or "(empty)", ANSWER_CHAR_BUDGET),
        ">>>",
        "",
        "Evidence the answer cites:",
        render_evidence(generation, lookup),
    ]
    return JudgePrompt(system=SYSTEM_PROMPT, user="\n".join(lines))


# --- selection -----------------------------------------------------------------------


def _rank(seed: int, name: str) -> str:
    return hashlib.sha256(f"{seed}:{name}".encode()).hexdigest()


def select_for_judging(
    items: Iterable[GoldItem],
    generations: Iterable[Generation],
    *,
    seed: int,
    changeset_fraction: float = CHANGESET_FRACTION,
) -> list[JudgePair]:
    """The generations to grade.

    Every rationale and hand item is graded. Of the change-set items a deterministic share is
    graded, chosen by cluster so that both variants of a pull request are in or out together;
    the clusters are drawn from the items, not the generations, so adding an arm does not change
    which questions are chosen. Structural items are scored by the file metrics and are not
    graded. Error generations are skipped, and where a key was written more than once the last
    record counts.

    Args:
        items: The slice's gold items.
        generations: Recorded generations.
        seed: The seed of the cluster sample.
        changeset_fraction: The share of change-set clusters to grade.

    Returns:
        The pairs, ordered by item, arm and repeat.
    """
    by_id = {item.id: item for item in items}
    clusters = sorted(
        {item.cluster for item in by_id.values() if item.family == "changeset" and item.cluster}
    )
    take = math.ceil(changeset_fraction * len(clusters)) if clusters else 0
    chosen = set(sorted(clusters, key=lambda c: (_rank(seed, c), c))[:take])

    pairs: list[JudgePair] = []
    for generation in final_records(generations):
        item = by_id.get(generation.item_id)
        if item is None or generation.status != "ok":
            continue
        if item.family in ("rationale", "hand") or (
            item.family == "changeset" and item.cluster in chosen
        ):
            pairs.append(JudgePair(item, generation))
    pairs.sort(key=lambda p: (p.item.id, p.generation.arm, p.generation.repeat))
    return pairs


# --- the files -----------------------------------------------------------------------


def judgments_path(run_dir: Path, endpoint: JudgeEndpoint) -> Path:
    """Where one judge's judgments live: ``judgments.<model>--<host>--<hash>.jsonl``."""
    return Path(run_dir) / f"judgments.{endpoint.slug}.jsonl"


def read_judgments(path: Path) -> list[Judgment]:
    """Every record in a judgments file, in file order; a line cut short is skipped."""
    if not Path(path).exists():
        return []
    records: list[Judgment] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            records.append(Judgment.model_validate_json(text))
        except ValueError:
            continue
    return records


def final_judgments(judgments: Iterable[Judgment]) -> list[Judgment]:
    """One record per key, the last one written, in the order each key first appeared."""
    latest: dict[str, Judgment] = {}
    for judgment in judgments:
        latest[judgment.judgment_key] = judgment
    return list(latest.values())


def all_judgments(run_dir: Path) -> list[Judgment]:
    """Every record of every judge's file in a run directory."""
    records: list[Judgment] = []
    for path in sorted(Path(run_dir).glob("judgments.*.jsonl")):
        records.extend(read_judgments(path))
    return records


def _append(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(payload + "\n")
        handle.flush()


# --- parsing and calling -------------------------------------------------------------


def parse_verdict(text: str) -> Verdict:
    """Validates the judge's output.

    Fenced JSON and JSON inside a sentence are accepted. Scores must be integers from 0 to 3,
    ``abstained`` a boolean and ``rationale`` a string; extra fields are ignored.

    Raises:
        JudgeOutputError: When the output is not JSON or breaks any of those rules.
    """
    try:
        data = parse_json(text)
    except ModelFailure as failure:
        raise JudgeOutputError(str(failure)) from None
    if not isinstance(data, dict):
        raise JudgeOutputError("the output is not a JSON object")
    missing = [name for name in JUDGE_SCHEMA["required"] if name not in data]
    if missing:
        raise JudgeOutputError(f"missing field(s): {', '.join(missing)}")
    scores: dict[str, int] = {}
    for name in ("correct", "faithful"):
        value = data[name]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 3:
            raise JudgeOutputError(f"{name} must be an integer from 0 to 3, got {value!r}")
        scores[name] = value
    if not isinstance(data["abstained"], bool):
        raise JudgeOutputError("abstained must be true or false")
    if not isinstance(data["rationale"], str):
        raise JudgeOutputError("rationale must be a string")
    return Verdict(scores["correct"], scores["faithful"], data["abstained"], data["rationale"])


def _number(value: Any) -> int:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0


def _chat_usage(response: Any, *, endpoint: JudgeEndpoint, latency_ms: float) -> Usage | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    details = getattr(usage, "prompt_tokens_details", None)
    cost = getattr(usage, "cost", None)
    return Usage(
        provider=endpoint.host,
        model=endpoint.model,
        kind="judge",
        input_tokens=_number(getattr(usage, "prompt_tokens", None)),
        cached_input_tokens=_number(getattr(details, "cached_tokens", None)),
        output_tokens=_number(getattr(usage, "completion_tokens", None)),
        reported_cost_usd=float(cost)
        if isinstance(cost, int | float) and not isinstance(cost, bool)
        else None,
        latency_ms=round(latency_ms, 2),
    )


async def _call_responses(
    client: Any, endpoint: JudgeEndpoint, prompt: JudgePrompt
) -> tuple[str, Usage | None, str | None]:
    started = time.perf_counter()
    messages = [
        {"role": "system", "content": prompt.system},
        {"role": "user", "content": prompt.user},
    ]
    try:
        async with asyncio.timeout(CALL_TIMEOUT_SECONDS):
            response = await client.responses.create(
                model=endpoint.model,
                input=messages,
                text=text_format("judgment", JUDGE_SCHEMA),
            )
    except BadRequestError:
        plain = [
            {"role": "system", "content": prompt.system + _JSON_SUFFIX + json.dumps(JUDGE_SCHEMA)},
            messages[1],
        ]
        async with asyncio.timeout(CALL_TIMEOUT_SECONDS):
            response = await client.responses.create(model=endpoint.model, input=plain)
    usage = usage_from_response(
        response,
        kind="judge",
        provider=endpoint.host,
        requested_model=endpoint.model,
        latency_ms=(time.perf_counter() - started) * 1000,
    )
    reported = usage.model if usage is not None else None
    if usage is not None:
        usage = usage.model_copy(update={"model": endpoint.model})
    return str(response.output_text or ""), usage, reported


async def _call_chat(
    client: Any, endpoint: JudgeEndpoint, prompt: JudgePrompt
) -> tuple[str, Usage | None, str | None]:
    started = time.perf_counter()
    system = prompt.system + _JSON_SUFFIX + json.dumps(JUDGE_SCHEMA)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt.user}]
    try:
        async with asyncio.timeout(CALL_TIMEOUT_SECONDS):
            response = await client.chat.completions.create(
                model=endpoint.model,
                messages=messages,
                response_format={"type": "json_object"},
            )
    except BadRequestError:
        async with asyncio.timeout(CALL_TIMEOUT_SECONDS):
            response = await client.chat.completions.create(model=endpoint.model, messages=messages)
    choices = getattr(response, "choices", None) or []
    content = choices[0].message.content if choices else ""
    reported = getattr(response, "model", None)
    usage = _chat_usage(
        response, endpoint=endpoint, latency_ms=(time.perf_counter() - started) * 1000
    )
    return str(content or ""), usage, reported if isinstance(reported, str) else None


# --- the runner ----------------------------------------------------------------------


@dataclass
class JudgeResult:
    """What a judge run did.

    Attributes:
        planned: Pairs the run was asked to grade.
        skipped: Pairs already graded.
        ok: Pairs graded this run.
        reused: Pairs given a copy of their target's grade.
        errors: Pairs whose grade could not be used; they are tried again next run.
        spent_usd: Spend so far, including what was on disk.
        stopped: Why the run stopped early, or ``None``.
        reported_models: The model names the provider reported.
    """

    planned: int = 0
    skipped: int = 0
    ok: int = 0
    reused: int = 0
    errors: int = 0
    spent_usd: float = 0.0
    stopped: str | None = None
    reported_models: set[str] = field(default_factory=set)


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def judge_all(
    pairs: Sequence[JudgePair],
    *,
    endpoint: JudgeEndpoint,
    out_path: Path,
    budget: Budget,
    table: PriceTable,
    client_factory: ClientFactory = AsyncOpenAI,
    meter: Meter | None = None,
    evidence_for: Callable[[GoldItem], EvidenceText] | None = None,
    concurrency: int = 1,
    clock: Callable[[], datetime] = _utcnow,
) -> JudgeResult:
    """Grades each pair, appending one judgment per pair to ``out_path``.

    A pair already graded ``ok`` under the same generation, prompt version, model and host is
    skipped; an error record is tried again. Generations are only read. A composed record whose
    answer is identical to its target's takes a copy of the target's grade instead of paying for
    a second one. Usage is charged to ``budget``, which the caller has restored from the
    records already on disk; the run stops cleanly before a pair once the stop is reached.

    Args:
        pairs: The generations to grade.
        endpoint: The judge.
        out_path: The judgments file of this judge.
        budget: The spend limits.
        table: The price table; it must price ``endpoint.model``.
        client_factory: Builds the client from ``AsyncOpenAI``-style keyword arguments.
        meter: Also receives the usage of every call.
        evidence_for: Gives, for an item, the lookup from a citation key to its text.
        concurrency: How many pairs are graded at once.
        clock: The wall clock.

    Returns:
        What the run did.
    """
    version = JUDGE_VERSION
    result = JudgeResult(planned=len(pairs))
    existing = {j.judgment_key: j for j in final_judgments(read_judgments(out_path))}
    client = client_factory(**endpoint.client_kwargs())
    call = _call_chat if endpoint.api_style == "chat" else _call_responses
    stop: list[BudgetStop] = []

    def key_of(pair: JudgePair) -> str:
        return judgment_key(
            generation_key=pair.generation.record_key,
            prompt_version=version,
            model=endpoint.model,
            host=endpoint.host,
        )

    def identity() -> JudgeVersion:
        return JudgeVersion(
            prompt_version=version,
            model=endpoint.model,
            host=endpoint.host,
            api_style=endpoint.api_style,
            judged_on=clock().date().isoformat(),
        )

    def record(judgment: Judgment) -> None:
        _append(out_path, judgment.model_dump_json())
        existing[judgment.judgment_key] = judgment

    async def grade(pair: JudgePair, key: str) -> None:
        item, generation = pair.item, pair.generation
        lookup = evidence_for(item) if evidence_for is not None else None
        prompt = judge_prompt(item, generation, evidence_text=lookup)
        common: dict[str, Any] = {
            "judgment_key": key,
            "generation_key": generation.record_key,
            "item_id": item.id,
            "family": item.family,
            "arm": generation.arm,
            "repeat": generation.repeat,
            "judge": identity(),
        }
        usage: Usage | None = None
        reported: str | None = None
        raw: str | None = None
        failure: str | None = None
        verdict: Verdict | None = None
        try:
            raw, usage, reported = await call(client, endpoint, prompt)
            verdict = parse_verdict(raw)
        except JudgeOutputError as problem:
            failure = f"judge output unusable: {problem}"
        except Exception as problem:
            failure = f"{type(problem).__name__}: {problem}"[:500]
        usages = [usage] if usage is not None else []
        cost = 0.0
        if usages:
            if meter is not None:
                meter.extend(usages)
            try:
                cost = budget.charge(usages, table, clock())
            except UnpricedSpend as unpriced:
                cost = unpriced.cost_usd
                if not stop:
                    stop.append(
                        BudgetStop(f"no price for {', '.join(unpriced.models)}", budget.spent_usd)
                    )
        elif meter is not None and failure is None:
            meter.note_unmetered("response_without_usage:judge")
        if reported:
            result.reported_models.add(reported)
        if verdict is not None:
            record(
                Judgment(
                    **common,
                    correct=verdict.correct,
                    faithful=verdict.faithful,
                    abstained=verdict.abstained,
                    rationale=verdict.rationale,
                    reported_model=reported,
                    usages=usages,
                    cost_usd=cost,
                )
            )
            result.ok += 1
        else:
            record(
                Judgment(
                    **common,
                    status="error",
                    error=failure,
                    raw=raw,
                    reported_model=reported,
                    usages=usages,
                    cost_usd=cost,
                )
            )
            result.errors += 1

    async def worker(queue: Iterable[tuple[JudgePair, str]]) -> None:
        for pair, key in queue:
            if stop:
                return
            try:
                budget.check_before_next()
            except BudgetStop as reached:
                stop.append(reached)
                return
            await grade(pair, key)

    async def drain(queue: list[tuple[JudgePair, str]]) -> None:
        iterator = iter(queue)
        workers = max(1, min(concurrency, len(queue)))
        await asyncio.gather(*(worker(iterator) for _ in range(workers)))

    # Non-composed records are graded first so composed ones can reuse their grades.
    direct: list[tuple[JudgePair, str]] = []
    composed: list[tuple[JudgePair, str]] = []
    for pair in pairs:
        key = key_of(pair)
        found = existing.get(key)
        if found is not None and found.status == "ok":
            result.skipped += 1
        elif pair.generation.composed_from is None:
            direct.append((pair, key))
        else:
            composed.append((pair, key))
    await drain(direct)

    target_of = {(p.item.id, p.generation.arm, p.generation.repeat): p for p in pairs}
    leftover: list[tuple[JudgePair, str]] = []
    for pair, key in composed:
        generation = pair.generation
        target = target_of.get((pair.item.id, generation.composed_from or "", 0))
        grade_of = existing.get(key_of(target)) if target is not None else None
        if (
            target is not None
            and grade_of is not None
            and grade_of.status == "ok"
            and target.generation.answer == generation.answer
        ):
            record(
                grade_of.model_copy(
                    update={
                        "judgment_key": key,
                        "generation_key": generation.record_key,
                        "arm": generation.arm,
                        "repeat": generation.repeat,
                        "judge": identity(),
                        "usages": [],
                        "cost_usd": 0.0,
                        "reused_from": grade_of.judgment_key,
                    }
                )
            )
            result.reused += 1
        else:
            leftover.append((pair, key))
    await drain(leftover)

    result.spent_usd = budget.spent_usd
    if stop:
        result.stopped = stop[0].reason
    return result


def judged_by_family(
    pairs: Iterable[JudgePair], judgments: Iterable[Judgment]
) -> dict[str, list[Judgment]]:
    """The ``ok`` judgments of the given pairs' generations, grouped by family."""
    wanted = {p.generation.record_key for p in pairs}
    grouped: dict[str, list[Judgment]] = defaultdict(list)
    for judgment in final_judgments(judgments):
        if judgment.status == "ok" and judgment.generation_key in wanted:
            grouped[judgment.family].append(judgment)
    return dict(grouped)


__all__ = [
    "ANSWER_CHAR_BUDGET",
    "CHANGESET_FRACTION",
    "EVIDENCE_CHAR_BUDGET",
    "JUDGE_SCHEMA",
    "JUDGE_VERSION",
    "NO_EVIDENCE",
    "SYSTEM_PROMPT",
    "UNAVAILABLE",
    "UNMATCHED",
    "EvidenceText",
    "JudgeOutputError",
    "JudgePair",
    "JudgePrompt",
    "JudgeResult",
    "Verdict",
    "all_judgments",
    "final_judgments",
    "judge_all",
    "judge_prompt",
    "judged_by_family",
    "judgments_path",
    "parse_verdict",
    "read_judgments",
    "render_evidence",
    "select_for_judging",
]
