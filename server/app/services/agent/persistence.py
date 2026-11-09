"""Recording a run in the database, and reading it back.

A run leaves two kinds of rows. ``agent_runs`` holds one row per question: what
was asked, which configuration answered, how it ended. ``agent_steps`` holds the
ordered record of what happened. A step row is either an ``event`` (exactly what
the client saw, so a replay is a read of these) or a detail row for debugging and
evaluation (a model call, a tool call with its full result, a decision with its
probabilities). Both kinds share one counter, so ``seq`` orders everything.

:class:`RunRecorder` is the single object a run talks to. It is the run's event
sink and its :class:`~app.services.agent.steps.StepRecorder`, and it fans each
event out twice from one place: to a queue the streaming response drains, and
to the database. Because a streamed event and the row behind it are built from
the same record with the same ``seq`` and timestamp, a replay reproduces the
live sequence exactly.

Writes never block the run. Rows are queued and written in batches by a
background task that opens its own session, and a failed write is logged and
announced once instead of raised.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun
from app.models.agent_step import AgentStep
from app.models.chat_message import ChatMessage
from app.services.agent.events import (
    TERMINAL_TYPES,
    CitationData,
    EventTranslator,
    EventType,
    StreamEvent,
    Translated,
)
from app.services.agent.state import Evidence
from app.services.agent.steps import StepRecord
from app.services.retrieval.citations import parse_key

if TYPE_CHECKING:
    from app.services.agent.runner import RunResult

logger = logging.getLogger(__name__)

SessionOpener = Callable[[], AbstractAsyncContextManager[AsyncSession]]
"""Opens a session for one unit of work: ``async with opener() as db``."""

MAX_PAYLOAD_BYTES = 64 * 1024
"""The most one step row's payload may hold; larger payloads are truncated with a marker."""

MAX_STEPS = 400
"""Detail rows stored per run. Past it they are counted, not stored."""

MAX_EVENTS = 1500
"""Event rows stored per run, terminal events excepted. Past it they are counted, not stored."""

STALE_RUN_SECONDS = 300
"""How long a ``running`` run may be silent before it reads as interrupted."""

RETENTION_DAYS = 30
"""How long step rows are kept; the run rows stay."""

DELTA_FLUSH_CHARS = 160
DELTA_FLUSH_SECONDS = 0.1

MAX_CITATION_CHARS = 4000

EVENT_KIND = "event"

# Event types whose text arrives a token at a time and is coalesced.
_STREAMED_TEXT = frozenset({EventType.ANSWER_DELTA, EventType.THINKING})

_PREVIEW_BYTES = MAX_PAYLOAD_BYTES - 1024


def sanitize_payload(payload: Any) -> Any:
    """Makes a payload storable as JSONB and no larger than the per-row cap.

    Text that cannot be stored (NUL characters) is removed, values that are not
    JSON are stringified, and a payload over :data:`MAX_PAYLOAD_BYTES` is
    replaced by a marker holding its size and a prefix of its JSON.

    Args:
        payload: A JSON-like value.

    Returns:
        A JSON-compatible value that fits the cap.
    """
    text = json.dumps(payload, default=str, ensure_ascii=False).replace("\\u0000", "")
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_PAYLOAD_BYTES:
        return json.loads(text)
    preview = encoded[:_PREVIEW_BYTES].decode("utf-8", errors="ignore")
    return {"truncated": True, "bytes": len(encoded), "preview": preview}


def _iso(moment: datetime) -> str:
    """A timestamp as the wire carries it: UTC, microsecond precision."""
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


class RunRecorder:
    """The sink for one run's events and steps.

    Implements :class:`~app.services.agent.steps.StepRecorder`, and exposes
    :meth:`emit` as the run's event sink.

    Attributes:
        run_id: The run.
        stream: The public events in order, ending with ``None`` once
            :meth:`end_stream` is called. The streaming response drains it.
        result: How the run ended, once the agent reports it.
        write_failures: Batches that could not be written.
    """

    def __init__(
        self,
        run_id: uuid.UUID,
        sessions: SessionOpener,
        *,
        max_steps: int = MAX_STEPS,
        max_events: int = MAX_EVENTS,
    ) -> None:
        self.run_id = run_id
        self.stream: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
        self.result: RunResult | None = None
        self.write_failures = 0
        self._sessions = sessions
        self._max_steps = max_steps
        self._max_events = max_events
        self._translator = EventTranslator()
        self._seq = 0
        self._pending: list[dict[str, Any]] = []
        self._writer: asyncio.Task[None] | None = None
        self._step_rows = 0
        self._event_rows = 0
        self._steps_dropped = 0
        self._events_dropped = 0
        self._delta: list[str] = []
        self._delta_worker: str | None = None
        self._delta_type = EventType.ANSWER_DELTA
        self._delta_meta: dict[str, Any] = {}
        self._delta_since = 0.0

    @property
    def dropped(self) -> int:
        """Records past the caps that were counted but not stored."""
        return self._steps_dropped + self._events_dropped

    # --- events -------------------------------------------------------------------

    async def emit(self, name: str, payload: dict[str, Any]) -> None:
        """Receives one of the run's internal events and publishes its public form."""
        for translated in self._translator.translate(name, payload):
            self._accept(translated)

    def publish(
        self, event_type: EventType, data: dict[str, Any], worker_id: str | None = None
    ) -> StreamEvent:
        """Publishes a public event directly, after any buffered answer text."""
        self.flush_deltas()
        return self._publish(event_type, data, worker_id)

    def flush_deltas(self) -> None:
        """Publishes any buffered answer or thinking text."""
        if not self._delta:
            return
        text, worker = "".join(self._delta), self._delta_worker
        self._delta = []
        self._publish(self._delta_type, {**self._delta_meta, "text": text}, worker)

    def end_stream(self) -> None:
        """Tells the streaming response there is nothing more."""
        self.flush_deltas()
        self.stream.put_nowait(None)

    def _accept(self, translated: Translated) -> None:
        if translated.type in _STREAMED_TEXT:
            self._buffer_delta(translated)
            return
        self.flush_deltas()
        self._publish(translated.type, translated.data, translated.worker_id)

    def _buffer_delta(self, translated: Translated) -> None:
        """Coalesces streamed text so a token stream does not become a row per token."""
        meta = {key: value for key, value in translated.data.items() if key != "text"}
        if self._delta and (
            self._delta_worker != translated.worker_id
            or self._delta_type is not translated.type
            or self._delta_meta != meta
        ):
            self.flush_deltas()
        now = time.monotonic()
        if not self._delta:
            self._delta_since = now
            self._delta_worker = translated.worker_id
            self._delta_type = translated.type
            self._delta_meta = meta
        self._delta.append(str(translated.data.get("text", "")))
        if (
            sum(len(piece) for piece in self._delta) >= DELTA_FLUSH_CHARS
            or now - self._delta_since >= DELTA_FLUSH_SECONDS
        ):
            self.flush_deltas()

    def _publish(
        self, event_type: EventType, data: dict[str, Any], worker_id: str | None
    ) -> StreamEvent:
        self._seq += 1
        moment = datetime.now(UTC)
        event = StreamEvent(
            seq=self._seq,
            ts=_iso(moment),
            run_id=str(self.run_id),
            worker_id=worker_id,
            type=event_type,
            data=data,
        )
        self.stream.put_nowait(event)
        if event_type not in TERMINAL_TYPES and self._event_rows >= self._max_events:
            self._events_dropped += 1
            return event
        self._event_rows += 1
        self._enqueue(
            {
                "seq": event.seq,
                "worker_id": worker_id,
                "kind": EVENT_KIND,
                "name": event_type.value,
                "payload": sanitize_payload(data),
                "tokens_in": None,
                "tokens_out": None,
                "latency_ms": 0,
                "created_at": moment,
            }
        )
        return event

    # --- steps --------------------------------------------------------------------

    async def record(self, step: StepRecord) -> None:
        """Stores one detail step, unless the run is past its cap."""
        self._seq += 1
        if self._step_rows >= self._max_steps:
            self._steps_dropped += 1
            return
        self._step_rows += 1
        payload = {**step.payload, "step_index": step.index}
        tokens_in = payload.get("input_tokens")
        tokens_out = payload.get("output_tokens")
        self._enqueue(
            {
                "seq": self._seq,
                "worker_id": step.worker_id,
                "kind": step.kind,
                "name": step.node,
                "payload": sanitize_payload(payload),
                "tokens_in": tokens_in if isinstance(tokens_in, int) else None,
                "tokens_out": tokens_out if isinstance(tokens_out, int) else None,
                "latency_ms": int(step.duration_ms or 0),
                "created_at": datetime.now(UTC),
            }
        )

    async def finish(self, result: RunResult) -> None:
        """Keeps how the run ended; the route writes it to the run row."""
        self.result = result

    # --- writing ------------------------------------------------------------------

    def _enqueue(self, row: dict[str, Any]) -> None:
        self._pending.append({**row, "id": uuid.uuid4(), "run_id": self.run_id})
        if self._writer is None or self._writer.done():
            self._writer = asyncio.create_task(self._drain())

    async def _drain(self) -> None:
        """Writes queued rows in batches until none are left."""
        while self._pending:
            batch, self._pending = self._pending, []
            try:
                async with self._sessions() as db:
                    await db.execute(insert(AgentStep), batch)
                    await db.commit()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.write_failures += 1
                logger.warning(
                    "run %s: could not write %d step rows", self.run_id, len(batch), exc_info=True
                )
                if self.write_failures == 1:
                    self._publish(
                        EventType.DEGRADED,
                        {
                            "stage": "recording",
                            "reason": "some of this run could not be saved for replay",
                            "detail": {},
                        },
                        None,
                    )

    async def close(self, timeout: float = 10.0) -> None:
        """Waits for queued rows to be written, for at most ``timeout`` seconds."""
        self.flush_deltas()
        deadline = time.monotonic() + timeout
        while True:
            writer = self._writer
            if writer is None or writer.done():
                if not self._pending:
                    return
                self._writer = asyncio.create_task(self._drain())
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning("run %s: gave up waiting for step rows", self.run_id)
                return
            try:
                await asyncio.wait_for(asyncio.shield(writer), remaining)
            except TimeoutError:
                logger.warning("run %s: gave up waiting for step rows", self.run_id)
                return
            except Exception:
                logger.warning("run %s: the step writer failed", self.run_id, exc_info=True)


# --- the run row --------------------------------------------------------------------


async def create_run(
    sessions: SessionOpener,
    *,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    repository_id: uuid.UUID,
    question: str,
    preset: str,
    config: dict[str, Any],
    config_hash: str,
    prompt_version: str | None,
    model: str | None,
    decider: str | None,
    ingested_commit_sha: str | None,
) -> None:
    """Inserts the run row in the ``running`` state and commits it."""
    async with sessions() as db:
        db.add(
            AgentRun(
                id=run_id,
                user_id=user_id,
                repository_id=repository_id,
                question=question,
                preset=preset,
                config=sanitize_payload(config),
                config_hash=config_hash,
                prompt_version=prompt_version,
                model=model,
                decider=decider,
                ingested_commit_sha=ingested_commit_sha,
                status="running",
            )
        )
        await db.commit()


async def finalize_run(
    sessions: SessionOpener,
    run_id: uuid.UUID,
    *,
    status: str,
    only_if_running: bool = False,
    **fields: Any,
) -> None:
    """Writes how a run ended.

    Args:
        sessions: Opens the session to write with.
        run_id: The run.
        status: ``done``, ``failed`` or ``cancelled``.
        only_if_running: Leave the row alone unless it is still ``running``, so a
            fallback finalizer never overwrites the real outcome.
        **fields: Other columns of :class:`~app.models.agent_run.AgentRun`.
    """
    values = {"status": status, "finished_at": datetime.now(UTC), **fields}
    statement = update(AgentRun).where(AgentRun.id == run_id)
    if only_if_running:
        statement = statement.where(AgentRun.status == "running")
    async with sessions() as db:
        await db.execute(statement.values(**values))
        await db.commit()


async def save_turn(
    sessions: SessionOpener,
    *,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    repository_id: uuid.UUID,
    question: str,
    answer: str,
    sources: Sequence[CitationData],
) -> uuid.UUID:
    """Writes the chat turn for a finished run and links it to the run.

    The turn and the link are committed together, so history never holds a turn
    whose run does not point back at it.

    Returns:
        The new chat message's id.
    """
    serialized = [
        {
            "source_type": source.source_type,
            "chunk_text": source.chunk_text,
            "file_path": source.file_path,
            "symbol_name": source.symbol_name,
            "start_line": source.start_line,
            "end_line": source.end_line,
            "commit_hash": source.commit_hash,
            "author_name": source.author_name,
            "pr_number": source.pr_number,
            "pr_title": source.pr_title,
        }
        for source in sources
    ]
    async with sessions() as db:
        message = ChatMessage(
            id=uuid.uuid4(),
            repository_id=repository_id,
            user_id=user_id,
            question=question,
            answer=answer,
            sources=serialized,
            agent_run_id=run_id,
        )
        db.add(message)
        await db.flush()
        await db.execute(
            update(AgentRun).where(AgentRun.id == run_id).values(chat_message_id=message.id)
        )
        await db.commit()
        return message.id


# --- citations ----------------------------------------------------------------------


def citation_from_evidence(key: str, evidence: Evidence | None) -> CitationData:
    """The stored shape of one cited piece of evidence.

    Args:
        key: The citation key.
        evidence: What the run saw under that key, when it still has it.
    """
    text = (evidence.text if evidence is not None else "")[:MAX_CITATION_CHARS]
    parsed = parse_key(key)
    if parsed is None:
        return CitationData(key=key, source_type="document", chunk_text=text)
    if parsed.kind == "F":
        ranged = parsed.start is not None
        return CitationData(
            key=key,
            source_type="symbol" if ranged else "file",
            chunk_text=text,
            file_path=parsed.path,
            start_line=parsed.start,
            end_line=parsed.end,
        )
    if parsed.kind == "C":
        return CitationData(
            key=key, source_type="commit", chunk_text=text, commit_hash=parsed.commit
        )
    if parsed.kind == "PR":
        return CitationData(
            key=key, source_type="pull_request", chunk_text=text, pr_number=parsed.pr_number
        )
    return CitationData(key=key, source_type="document", chunk_text=text)


# --- reading ------------------------------------------------------------------------


def public_status(
    run: AgentRun, last_activity: datetime | None, now: datetime | None = None
) -> str:
    """The status a client should show.

    A run recorded as ``running`` whose process has gone quiet for longer than
    :data:`STALE_RUN_SECONDS` was killed (a deploy, a crash) and reads as
    ``interrupted`` instead of appearing to run forever.
    """
    if run.status != "running":
        return run.status
    moment = now or datetime.now(UTC)
    seen = last_activity or run.created_at
    if moment - seen > timedelta(seconds=STALE_RUN_SECONDS):
        return "interrupted"
    return "running"


async def last_activity(
    db: AsyncSession, run_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, datetime]:
    """When each run last wrote a step row."""
    if not run_ids:
        return {}
    rows = await db.execute(
        select(AgentStep.run_id, func.max(AgentStep.created_at))
        .where(AgentStep.run_id.in_(run_ids))
        .group_by(AgentStep.run_id)
    )
    return {run_id: moment for run_id, moment in rows.all()}


async def load_events(db: AsyncSession, run_id: uuid.UUID) -> list[StreamEvent]:
    """A run's recorded events in the shape the live stream sent them."""
    rows = (
        (
            await db.execute(
                select(AgentStep)
                .where(AgentStep.run_id == run_id, AgentStep.kind == EVENT_KIND)
                .order_by(AgentStep.seq)
            )
        )
        .scalars()
        .all()
    )
    return [
        StreamEvent(
            seq=row.seq,
            ts=_iso(row.created_at),
            run_id=str(run_id),
            worker_id=row.worker_id,
            type=EventType(row.name),
            data=row.payload,
        )
        for row in rows
    ]
