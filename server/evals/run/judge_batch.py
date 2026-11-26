"""Judging through OpenRouter's batch API: half price, answered later, replayed in rounds.

A batch request is answered minutes or hours after it is sent, but a DeepEval metric is a chain
of calls where each prompt is built from the previous reply (claims, then verdicts, then a
reason). So a batch judge runs in rounds. Every call looks its request up in a reply store; a
call that finds its reply gets it back as an ordinary chat completion, and a call that does not
queues its request and stops that metric with :class:`BatchPending`. After a round, the queued
requests go out as batches. When they come back their replies are stored, and the next round
replays every earlier step from the store, so the same prompts are rebuilt and each metric gets
one step further. A metric whose every call is answered is recorded like any other judgment.

A request is keyed by a hash of its body, so the store also deduplicates: two generations with
the same answer to the same question ask the same questions and share the replies.

A model id ending in ``:batch`` selects this path. It keeps batch judgments in their own file,
priced at the batch rate, apart from the same model judged live.

Library code here takes nothing from ``evals.settings``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx

from evals.run.endpoint import JudgeEndpoint
from evals.run.pricing import PriceTable, UnpricedUsage
from evals.run.records import Usage

BATCH_SUFFIX = ":batch"
"""The model id suffix that selects the batch path."""
MAX_ATTEMPTS = 2
"""How many times a request that came back failed is sent before its metric is an error."""
MAX_REQUESTS_PER_BATCH = 1000
"""The most requests sent in one batch; a round with more is sent as several."""
ESTIMATED_OUTPUT_TOKENS = 3000
"""The output assumed per request when estimating a batch's cost before it is sent."""
CHARS_PER_TOKEN = 3.0
"""Characters per input token when estimating; low, so the estimate errs high."""
HTTP_TIMEOUT_SECONDS = 120.0
FINAL_STATUSES = frozenset({"completed", "failed", "expired", "cancelled"})
REPLIES = "replies.jsonl"
BATCHES = "batches.json"


class BatchPending(Exception):
    """A call's request has no reply yet; it has been queued for the next batch."""


class BatchRequestFailed(RuntimeError):
    """A request came back failed from every batch it was sent in."""


class BatchApiError(RuntimeError):
    """The batch API refused or failed a request."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def is_batch_model(model: str) -> bool:
    """Whether a judge model id selects the batch path."""
    return model.endswith(BATCH_SUFFIX)


def plain_slug(model: str) -> str:
    """The model id the batch API is called with: the id without ``:batch``."""
    return model.removesuffix(BATCH_SUFFIX)


def batch_dir(run_dir: Path, endpoint: JudgeEndpoint) -> Path:
    """Where one batch judge keeps its replies and its batches."""
    return Path(run_dir) / f"batch.{endpoint.slug}"


def request_key(body: Mapping[str, Any]) -> str:
    """A stable key of one request body."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _namespace(value: Any) -> Any:
    if isinstance(value, dict):
        return SimpleNamespace(**{str(k): _namespace(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_namespace(v) for v in value]
    return value


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --- the reply store -----------------------------------------------------------------


@dataclass(frozen=True)
class Reply:
    """What came back for one request.

    Attributes:
        key: The request's key.
        body: The chat completion, for a request that succeeded.
        error: Why it failed, for one that did not.
        attempts: How many batches the request has been sent in.
    """

    key: str
    body: dict[str, Any] | None = None
    error: str | None = None
    attempts: int = 1

    @property
    def ok(self) -> bool:
        """Whether the request succeeded."""
        return self.body is not None and self.error is None


@dataclass
class InFlight:
    """A batch that was sent and has not been collected.

    Attributes:
        id: The batch id the API gave.
        keys: The request keys it carries; each is its ``custom_id``.
        submitted_at: When it was sent, ISO 8601.
        estimate_usd: Its estimated cost, counted against the budget until it is collected.
    """

    id: str
    keys: list[str]
    submitted_at: str
    estimate_usd: float


@dataclass
class ReplyStore:
    """Replies on disk, the batches in flight and the requests waiting to be sent.

    Replies are appended to ``replies.jsonl`` (the last record per key wins) and the batches in
    flight are rewritten to ``batches.json`` on every change. Queued requests live only in memory:
    the round that queued them sends them before it ends.

    Attributes:
        directory: Where the files live.
        replies: The latest reply per key.
        in_flight: The batches sent and not collected.
        queued: Requests with no reply and not in flight, by key.
    """

    directory: Path
    replies: dict[str, Reply] = field(default_factory=dict)
    in_flight: list[InFlight] = field(default_factory=list)
    queued: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def open(cls, directory: Path) -> ReplyStore:
        """Read a store from disk; a missing directory is an empty store."""
        store = cls(Path(directory))
        replies = store.directory / REPLIES
        if replies.exists():
            for line in replies.read_text(encoding="utf-8").splitlines():
                text = line.strip()
                if not text:
                    continue
                try:
                    raw = json.loads(text)
                    store.replies[raw["key"]] = Reply(
                        key=raw["key"],
                        body=raw.get("body"),
                        error=raw.get("error"),
                        attempts=int(raw.get("attempts", 1)),
                    )
                except ValueError, KeyError, TypeError:
                    continue
        batches = store.directory / BATCHES
        if batches.exists():
            for raw in json.loads(batches.read_text(encoding="utf-8")):
                store.in_flight.append(InFlight(**raw))
        return store

    def in_flight_keys(self) -> set[str]:
        """Keys of every request in a batch that has not been collected."""
        return {key for batch in self.in_flight for key in batch.keys}

    def lookup(self, key: str) -> Reply | None:
        """The reply to use for a request, or ``None`` when it still needs one.

        A failed reply counts only once the request has been sent :data:`MAX_ATTEMPTS` times;
        before that the request is sent again.
        """
        reply = self.replies.get(key)
        if reply is None:
            return None
        if reply.ok or reply.attempts >= MAX_ATTEMPTS:
            return reply
        return None

    def queue(self, key: str, body: dict[str, Any]) -> None:
        """Queue a request for the next batch, unless it is already in flight."""
        if key not in self.in_flight_keys():
            self.queued.setdefault(key, body)

    def add(self, reply: Reply) -> None:
        """Append a reply."""
        self.directory.mkdir(parents=True, exist_ok=True)
        record = {"key": reply.key, "attempts": reply.attempts}
        if reply.body is not None:
            record["body"] = reply.body
        if reply.error is not None:
            record["error"] = reply.error
        with (self.directory / REPLIES).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.replies[reply.key] = reply

    def save_in_flight(self) -> None:
        """Rewrite ``batches.json``."""
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = [vars(batch) for batch in self.in_flight]
        target = self.directory / BATCHES
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(target)


# --- the stand-in client -------------------------------------------------------------


class BatchChatClient:
    """Stands in for ``AsyncOpenAI`` under :class:`evals.run.judge_model.MeteredJudgeModel`.

    Only ``chat.completions.create`` exists: a stored reply comes back as a chat completion, and
    a request without one is queued and raises :class:`BatchPending`.
    """

    def __init__(self, store: ReplyStore) -> None:
        """Builds the client over a store.

        Args:
            store: Where replies are looked up and requests queued.
        """
        self.store = store
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, *, model: str, messages: list[dict[str, Any]], **extra: Any) -> Any:
        body: dict[str, Any] = {"model": plain_slug(model), "messages": messages, **extra}
        key = request_key(body)
        reply = self.store.lookup(key)
        if reply is None:
            self.store.queue(key, body)
            raise BatchPending(key)
        if not reply.ok:
            raise BatchRequestFailed(f"batch request failed: {reply.error}"[:500])
        return _namespace(reply.body)


# --- cost ----------------------------------------------------------------------------


def reply_usage(reply: Reply, endpoint: JudgeEndpoint) -> Usage | None:
    """The usage a stored reply reports, attributed to the batch model."""
    usage = (reply.body or {}).get("usage")
    if not isinstance(usage, dict):
        return None
    details = usage.get("prompt_tokens_details") or {}
    cost = usage.get("cost")
    return Usage(
        provider=endpoint.host,
        model=endpoint.model,
        kind="judge",
        input_tokens=int(usage.get("prompt_tokens") or 0),
        cached_input_tokens=int(details.get("cached_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
        reported_cost_usd=float(cost) if isinstance(cost, int | float) else None,
    )


def stored_spend(store: ReplyStore, endpoint: JudgeEndpoint, table: PriceTable) -> float:
    """What the stored replies cost plus what the batches in flight are estimated to cost.

    Every reply is counted once, whether or not a judgment has used it yet, since it was paid
    for when its batch ran.
    """
    now = _utcnow()
    total = sum(batch.estimate_usd for batch in store.in_flight)
    for reply in store.replies.values():
        usage = reply_usage(reply, endpoint)
        if usage is not None:
            try:
                total += table.cost(usage, now)
            except UnpricedUsage:
                continue
    return total


def estimate_usd(
    bodies: Sequence[Mapping[str, Any]], endpoint: JudgeEndpoint, table: PriceTable
) -> float:
    """A high estimate of what sending ``bodies`` costs, at the batch model's rates."""
    now = _utcnow()
    total = 0.0
    for body in bodies:
        chars = len(json.dumps(body.get("messages", []), ensure_ascii=False))
        usage = Usage(
            provider=endpoint.host,
            model=endpoint.model,
            kind="judge",
            input_tokens=int(chars / CHARS_PER_TOKEN) + 1,
            output_tokens=ESTIMATED_OUTPUT_TOKENS,
        )
        total += table.cost(usage, now)
    return total


# --- the batch API -------------------------------------------------------------------


class BatchApi:
    """A small client for OpenRouter's ``/batches`` endpoints."""

    def __init__(self, endpoint: JudgeEndpoint, http: httpx.Client | None = None) -> None:
        """Builds the client.

        Args:
            endpoint: The judge; its base URL and key are used.
            http: The HTTP client; a new one when omitted.
        """
        self._base = (endpoint.base_url or "").rstrip("/") + "/batches"
        self._http = http or httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)
        self._headers = {
            "Authorization": f"Bearer {endpoint.require_key()}",
            "Content-Type": "application/json",
        }

    def _call(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = self._http.request(method, url, headers=self._headers, **kwargs)
        if response.status_code >= 400:
            message = response.text
            try:
                error = response.json().get("error")
                if isinstance(error, Mapping) and error.get("message"):
                    message = str(error["message"])
            except ValueError, AttributeError:
                pass
            raise BatchApiError(
                f"{method} {url}: {response.status_code} {message}"[:500], response.status_code
            )
        data: dict[str, Any] = response.json()
        return data

    def submit(
        self, model: str, requests: Sequence[tuple[str, Mapping[str, Any]]]
    ) -> dict[str, Any]:
        """Send one batch of chat completions.

        The top-level fields go before ``requests``, which the API requires.
        """
        payload = {
            "endpoint": "/v1/chat/completions",
            "model": model,
            "completion_window": "24h",
            "requests": [{"custom_id": key, "body": dict(body)} for key, body in requests],
        }
        return self._call("POST", self._base, content=json.dumps(payload).encode())

    def status(self, batch_id: str) -> dict[str, Any]:
        """One batch's current state."""
        return self._call("GET", f"{self._base}/{batch_id}")

    def results(self, batch_id: str) -> Iterator[dict[str, Any]]:
        """Every result entry of a finished batch, page by page."""
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": 1000}
            if cursor:
                params["cursor"] = cursor
            page = self._call("GET", f"{self._base}/{batch_id}/results", params=params)
            yield from page.get("data") or []
            cursor = page.get("next_cursor")
            if not page.get("has_more") or not cursor:
                return


# --- collecting and sending ----------------------------------------------------------


@dataclass
class Exchange:
    """What one collect-and-send step did.

    Attributes:
        collected: Batches collected.
        replies: Replies stored, failed ones included.
        failed: Of those, the failed ones.
        waiting: Batches still running.
        submitted: Batches sent.
        sent: Requests sent.
        sent_usd: The estimated cost of what was sent.
        held: Requests left queued, by the budget or by the API refusing more.
        held_reason: Why requests were held.
    """

    collected: int = 0
    replies: int = 0
    failed: int = 0
    waiting: int = 0
    submitted: int = 0
    sent: int = 0
    sent_usd: float = 0.0
    held: int = 0
    held_reason: str | None = None


def _entry_reply(entry: Mapping[str, Any], previous: Reply | None) -> Reply | None:
    key = entry.get("custom_id")
    if not isinstance(key, str):
        return None
    attempts = (previous.attempts + 1) if previous is not None and not previous.ok else 1
    response = entry.get("response") or {}
    body = response.get("body") if isinstance(response, Mapping) else None
    status_code = response.get("status_code") if isinstance(response, Mapping) else None
    error = entry.get("error")
    if error or not isinstance(body, dict) or (isinstance(status_code, int) and status_code >= 400):
        message = (error or {}).get("message") if isinstance(error, Mapping) else None
        return Reply(
            key=key, error=str(message or error or f"status {status_code}"), attempts=attempts
        )
    return Reply(key=key, body=body, attempts=attempts)


def collect(store: ReplyStore, api: BatchApi, exchange: Exchange) -> None:
    """Store the replies of every batch in flight that has finished."""
    still: list[InFlight] = []
    for batch in store.in_flight:
        state = api.status(batch.id)
        status = state.get("status")
        if status not in FINAL_STATUSES:
            still.append(batch)
            exchange.waiting += 1
            continue
        answered: set[str] = set()
        if status == "completed":
            for entry in api.results(batch.id):
                reply = _entry_reply(entry, store.replies.get(str(entry.get("custom_id"))))
                if reply is None or reply.key not in batch.keys:
                    continue
                store.add(reply)
                answered.add(reply.key)
                exchange.replies += 1
                exchange.failed += 0 if reply.ok else 1
        reason = (
            (state.get("error") or {}).get("message")
            if isinstance(state.get("error"), Mapping)
            else None
        ) or f"batch {status}"
        for key in batch.keys:
            if key not in answered:
                previous = store.replies.get(key)
                attempts = (
                    (previous.attempts + 1) if previous is not None and not previous.ok else 1
                )
                store.add(Reply(key=key, error=str(reason), attempts=attempts))
                exchange.replies += 1
                exchange.failed += 1
        exchange.collected += 1
    store.in_flight = still
    store.save_in_flight()


def send(
    store: ReplyStore,
    api: BatchApi,
    endpoint: JudgeEndpoint,
    table: PriceTable,
    *,
    room_usd: float,
    exchange: Exchange,
    clock: Callable[[], datetime] = _utcnow,
) -> None:
    """Send the queued requests as batches, as far as ``room_usd`` allows.

    Each batch is sent only when its estimate fits in what is left of ``room_usd``; a batch the
    API refuses (too many in flight, say) and everything after it stays queued for the next step.
    """
    pending = list(store.queued.items())
    model = plain_slug(endpoint.model)
    left = room_usd
    for start in range(0, len(pending), MAX_REQUESTS_PER_BATCH):
        chunk = pending[start : start + MAX_REQUESTS_PER_BATCH]
        estimate = estimate_usd([body for _, body in chunk], endpoint, table)
        if estimate > left:
            exchange.held += len(pending) - start
            exchange.held_reason = (
                f"the next batch is estimated at ${estimate:.4f}, over the ${max(left, 0):.4f} left"
            )
            break
        try:
            created = api.submit(model, chunk)
        except BatchApiError as refused:
            exchange.held += len(pending) - start
            exchange.held_reason = str(refused)
            break
        keys = [key for key, _ in chunk]
        store.in_flight.append(
            InFlight(
                id=str(created["id"]),
                keys=keys,
                submitted_at=clock().isoformat(),
                estimate_usd=round(estimate, 6),
            )
        )
        store.save_in_flight()
        for key in keys:
            store.queued.pop(key, None)
        left -= estimate
        exchange.submitted += 1
        exchange.sent += len(chunk)
        exchange.sent_usd += estimate


__all__ = [
    "BATCH_SUFFIX",
    "MAX_ATTEMPTS",
    "MAX_REQUESTS_PER_BATCH",
    "BatchApi",
    "BatchApiError",
    "BatchChatClient",
    "BatchPending",
    "BatchRequestFailed",
    "Exchange",
    "InFlight",
    "Reply",
    "ReplyStore",
    "batch_dir",
    "collect",
    "estimate_usd",
    "is_batch_model",
    "plain_slug",
    "request_key",
    "reply_usage",
    "send",
    "stored_spend",
]
