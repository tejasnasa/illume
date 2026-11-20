"""The independent check of hand-written reference answers.

A model other than the one that wrote an item reads the item's question, its reference answer
and the text of the files it names, as they are at the base commit, and says whether the files
support the answer: ``supported``, ``partly_supported`` or ``unsupported``, with the claim at
fault. The check is cached like every other model stage. Each result is one line of an
append-only JSONL file keyed by the item's content, the prompt version, the checker model and
its host; a line that succeeded is skipped on the next run, a failed one is tried again and the
last line for a key wins. A failure is stored as an error record and never as a verdict.

``unsupported`` items are dropped from a gold build; ``partly_supported`` ones are kept and
listed so someone fixes them. Every call goes through the metered judge model, so spend reaches
the budget and the meter.

Library code here takes nothing from ``evals.settings``.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Self

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field, model_validator

from evals.gold.schema import GoldItem, canonical_json
from evals.run.budget import Budget, BudgetStop, UnpricedSpend
from evals.run.endpoint import JudgeEndpoint
from evals.run.judge_model import JudgeOutputError, MeteredJudgeModel
from evals.run.metering import Meter
from evals.run.pricing import PriceTable
from evals.run.records import Usage

CHECKER_PROMPT_VERSION = "1"
"""The version of the checker prompt and of how the files are shown; bump it when either changes."""
FILE_CHAR_BUDGET = 24000
"""The most file text, in characters, shown to the checker for one item, shared across its files."""
MIN_FILE_SHARE = 400
CHECK_TIMEOUT_SECONDS = 300.0
MISSING_FILE = "(this file is not present at the base commit)"
EMPTY_FILE = "(this file is empty)"

VerdictName = Literal["supported", "partly_supported", "unsupported"]
SEVERITY: dict[str, int] = {"supported": 0, "partly_supported": 1, "unsupported": 2}

PROMPT = """You are checking a reference answer written for a question about a software \
repository. You are not the author of the answer and must judge it only from the file contents \
below, which are the repository's files at one fixed commit.

Question:
{question}

Reference answer:
{reference}

Files the answer relies on (required files first, then acceptable ones):
{files}

Decide whether the files support the reference answer.
- supported: every claim in the reference answer is supported by the files.
- partly_supported: the answer is broadly right, but at least one claim is wrong in a detail, \
is not supported by the files shown, or cannot be verified from them.
- unsupported: a central claim is contradicted by the files or has no support in them.

Reply with a JSON object with these fields:
- verdict: one of supported, partly_supported, unsupported.
- faulty_claim: the specific claim that is wrong or unsupported, quoted or paraphrased; an empty \
string when the verdict is supported.
- explanation: one to three sentences saying what in the files decides it."""


class CheckVerdict(BaseModel):
    """What the checker is asked to return.

    Attributes:
        verdict: Whether the files support the reference answer.
        faulty_claim: The claim at fault; empty when the verdict is ``supported``.
        explanation: Why, in a few sentences.
    """

    verdict: VerdictName
    faulty_claim: str
    explanation: str


class CheckRecord(BaseModel):
    """One item's check, or the record that checking it failed.

    Attributes:
        check_key: A hash of the item's content, the prompt version, the model and the host.
        item_id: The gold item.
        content_hash: A hash of what the check read; see :func:`item_content_hash`.
        repo: The item's repository.
        status: ``ok``, or ``error`` when the call failed or returned nothing usable.
        verdict: The verdict; only on an ``ok`` record.
        faulty_claim: The claim at fault, when there is one.
        explanation: The checker's reason.
        error: Why the record is an error record.
        model: The checker model asked for.
        host: The checker's host.
        prompt_version: The checker prompt version.
        reported_model: The model the provider reported answering.
        usages: Every metered call the check made.
        cost_usd: What the check cost.
    """

    model_config = ConfigDict(extra="forbid")

    check_key: str
    item_id: str
    content_hash: str
    repo: str
    status: Literal["ok", "error"] = "ok"
    verdict: VerdictName | None = None
    faulty_claim: str = ""
    explanation: str = ""
    error: str | None = None
    model: str
    host: str
    prompt_version: str
    reported_model: str | None = None
    usages: list[Usage] = Field(default_factory=list)
    cost_usd: float | None = None

    @model_validator(mode="after")
    def _status_matches_payload(self) -> Self:
        if self.status == "ok" and self.verdict is None:
            raise ValueError("an ok check needs a verdict")
        if self.status == "error" and (self.verdict is not None or not self.error):
            raise ValueError("an error check carries an error and no verdict")
        return self


def item_content_hash(item: GoldItem) -> str:
    """A hash of everything a check reads from an item.

    The question, the reference answer, the required and acceptable files and the base commit.
    Editing any of them gives a new hash, so an old verdict is never applied to changed text.

    Args:
        item: The gold item.

    Returns:
        The first 16 hex digits of the SHA-256 of the canonical JSON.
    """
    payload = {
        "base_commit": item.base_commit,
        "question": item.question or item.question_seed,
        "reference_answer": item.reference_answer,
        "required_files": sorted(item.gold_files),
        "acceptable_files": sorted(item.acceptable_files),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:16]


def check_key(item: GoldItem, endpoint: JudgeEndpoint) -> str:
    """The cache key of one item's check under one checker."""
    payload = {
        "content": item_content_hash(item),
        "prompt_version": CHECKER_PROMPT_VERSION,
        "file_char_budget": FILE_CHAR_BUDGET,
        "model": endpoint.model,
        "host": endpoint.host,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:16]


def checks_path(directory: Path, endpoint: JudgeEndpoint) -> Path:
    """Where one checker's records live: ``checks.<model>--<host>--<hash>.jsonl``."""
    return Path(directory) / f"checks.{endpoint.slug}.jsonl"


# --- what the checker is shown --------------------------------------------------------


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "\n... (truncated)"


def render_files(
    item: GoldItem,
    read_file: Callable[[GoldItem, str], str | None],
    *,
    budget: int = FILE_CHAR_BUDGET,
) -> str:
    """The text of an item's files, each led by its path, within a character budget.

    Required files come first, then acceptable ones. The budget is shared across the files; a
    file that is short leaves its unused share to the ones after it.

    Args:
        item: The gold item.
        read_file: Gives a file's text at the base commit for an item, or ``None`` when the
            file is not there.
        budget: The most characters of file text to show.

    Returns:
        One block per file.
    """
    paths = list(dict.fromkeys([*sorted(item.gold_files), *sorted(item.acceptable_files)]))
    remaining = budget
    blocks: list[str] = []
    for position, path in enumerate(paths):
        text = read_file(item, path)
        if text is None:
            body = MISSING_FILE
        elif not text.strip():
            body = EMPTY_FILE
        else:
            share = max(MIN_FILE_SHARE, remaining // (len(paths) - position))
            body = _truncate(text.strip("\n"), min(share, max(0, remaining)))
            remaining -= len(body)
        blocks.append(f"=== {path} ===\n{body}")
    return "\n\n".join(blocks)


def build_prompt(item: GoldItem, files: str) -> str:
    """The checker prompt for one item."""
    return PROMPT.format(
        question=(item.question or item.question_seed).strip(),
        reference=item.reference_answer.strip() or "(none)",
        files=files,
    )


# --- records -------------------------------------------------------------------------


def read_checks(path: Path) -> list[CheckRecord]:
    """Every record in a checks file, in file order; a line cut short is skipped."""
    if not Path(path).exists():
        return []
    records: list[CheckRecord] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            records.append(CheckRecord.model_validate_json(text))
        except ValueError:
            continue
    return records


def final_checks(records: Iterable[CheckRecord]) -> list[CheckRecord]:
    """One record per key, the last one written, in the order each key first appeared."""
    latest: dict[str, CheckRecord] = {}
    for record in records:
        latest[record.check_key] = record
    return list(latest.values())


def all_checks(directory: Path) -> list[CheckRecord]:
    """Every record of every checker's file in a gold directory."""
    records: list[CheckRecord] = []
    for path in sorted(Path(directory).glob("checks.*.jsonl")):
        records.extend(read_checks(path))
    return records


def _append(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(payload + "\n")
        handle.flush()


def spent_on_disk(records: Iterable[CheckRecord]) -> float:
    """The total cost recorded on check records, superseded ones included."""
    return sum(record.cost_usd or 0.0 for record in records)


# --- the runner ----------------------------------------------------------------------


@dataclass
class CheckResult:
    """What a check run did.

    Attributes:
        planned: Items the run was asked to check.
        skipped: Items already checked.
        ok: Items checked this run.
        errors: Items whose check failed; they are tried again next run.
        spent_usd: Spend so far, including what was on disk.
        stopped: Why the run stopped early, or ``None``.
        reported_models: The model names the provider reported.
    """

    planned: int = 0
    skipped: int = 0
    ok: int = 0
    errors: int = 0
    spent_usd: float = 0.0
    stopped: str | None = None
    reported_models: set[str] = field(default_factory=set)


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def check_items(
    items: Sequence[GoldItem],
    *,
    endpoint: JudgeEndpoint,
    out_path: Path,
    budget: Budget,
    table: PriceTable,
    read_file: Callable[[GoldItem, str], str | None],
    client_factory: Callable[..., Any] = AsyncOpenAI,
    meter: Meter | None = None,
    concurrency: int = 1,
    clock: Callable[[], datetime] = _utcnow,
    timeout: float = CHECK_TIMEOUT_SECONDS,
) -> CheckResult:
    """Check each item, appending one record per item to ``out_path``.

    An item already checked ``ok`` under the same content, prompt version, model and host is
    skipped; an error record is tried again. Every call is metered and charged to ``budget``,
    and the run stops cleanly before an item once the stop is reached.

    Args:
        items: The items to check; only their reference answers and files matter.
        endpoint: The checker.
        out_path: The checks file of this checker.
        budget: The spend limits, already restored from the records on disk.
        table: The price table; it must price ``endpoint.model``.
        read_file: Gives an item's file text at the base commit, or ``None`` when absent.
        client_factory: Builds the client from ``AsyncOpenAI``-style keyword arguments.
        meter: Also receives the usage of every call.
        concurrency: How many items are checked at once.
        clock: The wall clock.
        timeout: The longest one item may take, in seconds.

    Returns:
        What the run did.
    """
    result = CheckResult(planned=len(items))
    existing = {r.check_key: r for r in final_checks(read_checks(out_path))}
    client = client_factory(**endpoint.client_kwargs())
    stop: list[BudgetStop] = []

    def charge(usages: list[Usage]) -> float:
        if not usages:
            return 0.0
        if meter is not None:
            meter.extend(usages)
        try:
            return budget.charge(usages, table, clock())
        except UnpricedSpend as unpriced:
            if not stop:
                stop.append(
                    BudgetStop(f"no price for {', '.join(unpriced.models)}", budget.spent_usd)
                )
            return unpriced.cost_usd

    async def check(item: GoldItem, key: str) -> None:
        model = MeteredJudgeModel(client, endpoint)
        verdict: CheckVerdict | None = None
        failure: str | None = None
        try:
            prompt = build_prompt(item, render_files(item, read_file))
            async with asyncio.timeout(timeout):
                reply = await model.a_generate(prompt, schema=CheckVerdict)
            if not isinstance(reply, CheckVerdict):
                raise JudgeOutputError("the checker returned no structured verdict")
            verdict = reply
        except JudgeOutputError as problem:
            failure = str(problem)
        except TimeoutError:
            failure = f"the check did not finish within {timeout:.0f} seconds"
        except Exception as problem:
            failure = f"{type(problem).__name__}: {problem}"[:500]
        cost = charge(model.usages)
        if meter is not None:
            for _ in range(model.unmetered):
                meter.note_unmetered("response_without_usage:judge")
        result.reported_models |= model.reported_models
        common: dict[str, Any] = {
            "check_key": key,
            "item_id": item.id,
            "content_hash": item_content_hash(item),
            "repo": item.repo,
            "model": endpoint.model,
            "host": endpoint.host,
            "prompt_version": CHECKER_PROMPT_VERSION,
            "reported_model": ",".join(sorted(model.reported_models)) or None,
            "usages": list(model.usages),
            "cost_usd": cost,
        }
        if verdict is not None and failure is None:
            record = CheckRecord(
                **common,
                verdict=verdict.verdict,
                faulty_claim=verdict.faulty_claim.strip(),
                explanation=verdict.explanation.strip(),
            )
            result.ok += 1
        else:
            record = CheckRecord(
                **common, status="error", error=failure or "the checker returned no verdict"
            )
            result.errors += 1
        _append(out_path, record.model_dump_json())
        existing[key] = record

    async def worker(queue: Iterable[tuple[GoldItem, str]]) -> None:
        for item, key in queue:
            if stop:
                return
            try:
                budget.check_before_next()
            except BudgetStop as reached:
                stop.append(reached)
                return
            await check(item, key)

    pending: list[tuple[GoldItem, str]] = []
    for item in items:
        key = check_key(item, endpoint)
        found = existing.get(key)
        if found is not None and found.status == "ok":
            result.skipped += 1
        else:
            pending.append((item, key))
    if pending:
        iterator = iter(pending)
        workers = max(1, min(concurrency, len(pending)))
        await asyncio.gather(*(worker(iterator) for _ in range(workers)))

    result.spent_usd = budget.spent_usd
    if stop:
        result.stopped = stop[0].reason
    return result


# --- using the verdicts --------------------------------------------------------------


@dataclass(frozen=True)
class CheckOutcome:
    """Items sorted by what their checks said.

    Attributes:
        kept: Items to keep: supported, partly supported and not yet checked.
        unsupported: Items dropped for an ``unsupported`` verdict.
        partly_supported: Items kept but flagged to be fixed, each with its record.
        unchecked: Items with no usable record for their current content.
    """

    kept: tuple[GoldItem, ...]
    unsupported: tuple[GoldItem, ...]
    partly_supported: tuple[tuple[GoldItem, CheckRecord], ...]
    unchecked: tuple[GoldItem, ...]


def apply_checks(items: Iterable[GoldItem], records: Iterable[CheckRecord]) -> CheckOutcome:
    """Drop the unsupported items and flag the partly supported ones.

    A record applies to an item only when its content hash matches the item as it is now, so an
    item edited after it was checked counts as unchecked. When several checkers have judged an
    item the most severe verdict counts. Error records never decide anything.

    Args:
        items: The items to filter.
        records: Check records, from any number of checkers.

    Returns:
        The items sorted by outcome; ``kept`` includes the partly supported ones.
    """
    by_hash: dict[str, list[CheckRecord]] = {}
    for record in final_checks(records):
        if record.status == "ok" and record.verdict is not None:
            by_hash.setdefault(record.content_hash, []).append(record)
    kept: list[GoldItem] = []
    unsupported: list[GoldItem] = []
    partly: list[tuple[GoldItem, CheckRecord]] = []
    unchecked: list[GoldItem] = []
    for item in items:
        found = by_hash.get(item_content_hash(item))
        if not found:
            unchecked.append(item)
            kept.append(item)
            continue
        worst = max(found, key=lambda r: SEVERITY[r.verdict or "supported"])
        if worst.verdict == "unsupported":
            unsupported.append(item)
            continue
        kept.append(item)
        if worst.verdict == "partly_supported":
            partly.append((item, worst))
    return CheckOutcome(tuple(kept), tuple(unsupported), tuple(partly), tuple(unchecked))


__all__ = [
    "CHECKER_PROMPT_VERSION",
    "FILE_CHAR_BUDGET",
    "CheckOutcome",
    "CheckRecord",
    "CheckResult",
    "CheckVerdict",
    "all_checks",
    "apply_checks",
    "build_prompt",
    "check_items",
    "check_key",
    "checks_path",
    "final_checks",
    "item_content_hash",
    "read_checks",
    "render_files",
    "spent_on_disk",
]
