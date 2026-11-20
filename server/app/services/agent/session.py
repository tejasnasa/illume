"""One streamed run, from the first event to the last.

:class:`RunSession` owns everything a streaming request needs after its checks
have passed: the task that does the work, the queue of events the response
drains, the database writes, the free-tier charge, the chat turn and the
concurrency slot. The route builds one and returns its frames; nothing else in
the request touches the database again, so no request-scoped session is held
open for the length of the stream.

**How a run ends**, and what each ending leaves behind:

* *done* -- the answer is saved as a chat turn linked to the run, a ``done``
  event carries it, and the run row is finalised.
* *failed* -- the ``error`` event has been sent; no chat turn, no charge.
* *cancelled* -- the client went away. The task is cancelled, the steps taken so
  far are written, the run is marked cancelled, and no turn is saved. A free-tier
  answer is charged only if the model had already started writing it.

**The free-tier charge** is claimed *before* the answer is generated, atomically,
so a client cannot get an answer for free by hanging up just before the end, and
two concurrent requests cannot both spend the last message. The claim is given
back when no answer was delivered: the run failed, it was cancelled before the
first piece of the answer streamed, or it found nothing to answer from.

In every case the concurrency slot is released in a ``finally``; its TTL is only
the safety net for a process that dies.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import anyio
from sse_starlette import ServerSentEvent

from app.services.agent.auto import AutoRoute
from app.services.agent.errors import describe_error
from app.services.agent.events import (
    CitationData,
    DoneData,
    EventType,
    UsageData,
)
from app.services.agent.persistence import (
    RunRecorder,
    SessionOpener,
    citation_from_evidence,
    finalize_run,
    save_turn,
)
from app.services.agent.runner import RunResult, run_agent
from app.services.agent.slots import RunSlots
from app.services.agent.steps import StepRecord
from app.services.agent.tools.context import RepoSnapshot
from app.services.decisions import Decider
from app.services.entitlements import aclaim_free_chat_message, arefund_free_chat_message
from app.services.llm_config import LLMConfig
from app.services.rag import ChatMessage
from app.services.retrieval.channels.base import Embedder, RetrievalContext
from app.services.retrieval.config import PipelineConfig
from app.services.retrieval.embedding import embed_texts
from app.services.retrieval.resolve import SourceReference
from app.services.retrieval.single_shot import SingleShotAnswer, answer
from app.services.tracing import add_trace_metadata, traced

logger = logging.getLogger(__name__)

CLEANUP_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class RunKit:
    """Collaborators a deployment leaves at their defaults and a test replaces.

    Every field defaults to ``None``, which means the production behaviour: the
    OpenAI client, the operator's embedding call, a decider built from the
    configuration.

    Attributes:
        client_factory: Builds the generation client from ``AsyncOpenAI``-style
            keyword arguments.
        embed: Embeds query text.
        decider: Makes the run's decisions.
    """

    client_factory: Any = None
    embed: Embedder | None = None
    decider: Decider | None = None


@dataclass(frozen=True)
class RunRequest:
    """Everything resolved about a run before it starts.

    Attributes:
        run_id: The run's id, already inserted as a ``running`` row.
        user_id: The asking user.
        repository: The repository, copied out of its row.
        question: The question as typed.
        history: Earlier turns, oldest first, already bounded.
        preset: The preset the run uses; for an ``auto`` request, the one it
            resolved to.
        config: The effective configuration, overrides applied.
        llm: The generation credential.
        model_label: ``provider:model`` for the run's record.
        github_token: The owner's GitHub token, for reading whole files.
        context_window: The input window one model call may carry, or ``None``
            for the configuration's.
        on_free_tier: Whether a generated answer is charged to the free tier.
        auto: How an ``auto`` request was resolved, or ``None`` for any other preset.
        save_history: Whether a finished answer is saved as a turn of the
            repository's chat. A run asked from outside the chat page leaves it
            out; the run row is finalised either way.
        conversation_id: The conversation a saved turn joins; ``None`` when the
            turn is not saved.
        new_conversation: Whether that conversation is created when the turn is
            saved, rather than already existing.
    """

    run_id: uuid.UUID
    user_id: uuid.UUID
    repository: RepoSnapshot
    question: str
    history: Sequence[ChatMessage]
    preset: str
    config: PipelineConfig
    llm: LLMConfig
    model_label: str
    github_token: str | None
    context_window: int | None
    on_free_tier: bool
    auto: AutoRoute | None = None
    save_history: bool = True
    conversation_id: uuid.UUID | None = None
    new_conversation: bool = False


@dataclass
class Outcome:
    """How a run that was not cancelled ended.

    Attributes:
        status: ``done`` or ``failed``.
        answer: The answer; empty when the run failed.
        stop_reason: Why the run stopped.
        citations: The evidence the answer cites.
        unresolved: Cited keys that match nothing the run saw.
        standalone_question: The question the channels searched with.
        usage: What the run spent.
        limits_reached: The limits the run hit, in order.
        error: Why it failed, when it did.
    """

    status: str
    answer: str = ""
    stop_reason: str = ""
    citations: list[CitationData] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    standalone_question: str | None = None
    usage: UsageData = field(default_factory=UsageData)
    limits_reached: list[str] = field(default_factory=list)
    error: str | None = None


def _reference_citation(reference: SourceReference, key: str | None) -> CitationData:
    return CitationData(
        key=key,
        source_type=reference.source_type,
        chunk_text=reference.chunk_text,
        file_path=reference.file_path,
        symbol_name=reference.symbol_name,
        start_line=reference.start_line,
        end_line=reference.end_line,
        commit_hash=reference.commit_hash,
        author_name=reference.author_name,
        pr_number=reference.pr_number,
        pr_title=reference.pr_title,
    )


class RunSession:
    """Runs one question and streams what happens.

    Args:
        request: The resolved run.
        sessions: Opens a database session for one unit of work.
        slots: The per-user concurrency cap, already holding this run's slot.
        kit: Collaborators a test replaces.
    """

    def __init__(
        self,
        request: RunRequest,
        sessions: SessionOpener,
        slots: RunSlots,
        kit: RunKit | None = None,
    ) -> None:
        self.request = request
        self.recorder = RunRecorder(request.run_id, sessions)
        self.task: asyncio.Task[None] | None = None
        self._sessions = sessions
        self._slots = slots
        self._kit = kit or RunKit()
        self._released = False
        self._cleaned = False
        self._started = time.monotonic()
        self._charged = False
        self._answer_started = False

    # --- the response ------------------------------------------------------------

    def start(self) -> None:
        """Starts the run in its own task, so the response can disconnect without ending it."""
        self.task = asyncio.create_task(self._drive())

    async def frames(self) -> AsyncIterator[ServerSentEvent]:
        """The run's events as server-sent frames, until the run ends.

        If the consumer goes away, the ``finally`` cancels the run.
        """
        try:
            while True:
                event = await self.recorder.stream.get()
                if event is None:
                    break
                yield ServerSentEvent(
                    data=event.model_dump_json(), event=event.type.value, id=str(event.seq)
                )
        finally:
            await self.cleanup()

    async def cleanup(self) -> None:
        """Stops the run if it is still going and gives back its slot.

        Idempotent, and shielded from the cancellation that a client disconnect
        delivers to the response, so the steps and the slot are always settled.
        """
        if self._cleaned:
            return
        self._cleaned = True
        with anyio.CancelScope(shield=True):
            task = self.task
            if task is not None and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(
                        asyncio.gather(task, return_exceptions=True), CLEANUP_TIMEOUT_SECONDS
                    )
                except TimeoutError:
                    logger.warning("run %s did not stop when cancelled", self.request.run_id)
            await self._release()
            try:
                await finalize_run(
                    self._sessions,
                    self.request.run_id,
                    status="cancelled",
                    only_if_running=True,
                    stop_reason="cancelled",
                )
            except Exception:
                logger.warning("could not settle run %s", self.request.run_id, exc_info=True)

    async def _release(self) -> None:
        if self._released:
            return
        self._released = True
        # Shielded so a cancellation arriving mid-release cannot strand the slot.
        await asyncio.shield(self._slots.release(self.request.user_id))

    # --- the task ----------------------------------------------------------------

    async def _drive(self) -> None:
        try:
            outcome = await self._execute()
            await self._conclude(outcome)
        except asyncio.CancelledError:
            await self._conclude_cancelled()
            raise
        except Exception as error:
            logger.exception("run %s failed", self.request.run_id)
            failure = describe_error(error)
            self.recorder.publish(
                EventType.ERROR,
                {"message": failure.message, "kind": failure.kind, "status": failure.status},
            )
            await self._conclude(
                Outcome(status="failed", stop_reason="error", error=failure.message)
            )
        finally:
            await self._release()
            self.recorder.end_stream()

    @traced("rag_run")
    async def _execute(self) -> Outcome:
        request = self.request
        add_trace_metadata(
            repo_id=str(request.repository.id),
            arm=request.preset,
            execution=request.config.execution,
            config_hash=request.config.config_hash(),
            model=request.llm.model,
            key_source="byok" if request.llm.source == "user" else "server",
        )
        self.recorder.publish(
            EventType.RUN_STARTED,
            {
                "preset": request.preset,
                "config_hash": request.config.config_hash(),
                "model": request.model_label,
                "execution": request.config.execution,
                **(
                    {"conversation_id": str(request.conversation_id)}
                    if request.conversation_id
                    else {}
                ),
            },
        )
        if request.auto is not None:
            await self._announce_route(request.auto)
        if request.config.execution == "single_shot":
            return await self._single_shot()
        return await self._agent()

    async def _announce_route(self, route: AutoRoute) -> None:
        """Streams the routing decision and records it as a step of the run."""
        data = route.event_data()
        self.recorder.publish(EventType.ROUTE, data)
        await self.recorder.record(
            StepRecord(
                index=-1,
                kind="decision",
                node="route",
                payload={"requested_preset": "auto", **data, "decision": route.decision},
                duration_ms=(route.decision or {}).get("latency_ms") or 0.0,
            )
        )

    async def _agent(self) -> Outcome:
        request, kit = self.request, self._kit
        result = await run_agent(
            request.question,
            request.history,
            repository=request.repository,
            session_factory=self._sessions,  # type: ignore[arg-type]
            llm=request.llm,
            config=request.config,
            context_window=request.context_window,
            github_token=request.github_token,
            emit=self.recorder.emit,
            steps=self.recorder,
            run_id=request.run_id,
            decider=kit.decider,
            embed=kit.embed,
            client_factory=kit.client_factory,
        )
        return self._agent_outcome(result)

    def _agent_outcome(self, result: RunResult) -> Outcome:
        usage = UsageData(
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            tool_calls=result.tool_calls,
            iterations=result.iterations,
            elapsed_seconds=result.elapsed_seconds,
        )
        if result.status != "completed":
            return Outcome(
                status="failed",
                stop_reason=result.stop_reason.value,
                usage=usage,
                limits_reached=list(result.limits_reached),
                error=result.error.message if result.error else "The run failed.",
            )
        return Outcome(
            status="done",
            answer=result.answer,
            stop_reason=result.stop_reason.value,
            citations=[
                citation_from_evidence(key, result.evidence.get(key)) for key in result.cited
            ],
            unresolved=list(result.unresolved),
            standalone_question=None,
            usage=usage,
            limits_reached=list(result.limits_reached),
        )

    async def _single_shot(self) -> Outcome:
        request, kit = self.request, self._kit
        if request.on_free_tier and not await self._claim():
            return self._free_tier_refusal()

        async def emit(event_type: str, data: dict[str, Any]) -> None:
            if event_type == EventType.ANSWER_DELTA:
                self._answer_started = True
            await self.recorder.emit(event_type, data)

        try:
            async with self._sessions() as db:
                ctx = RetrievalContext(
                    repository_id=request.repository.id,
                    db=db,
                    embed=kit.embed or embed_texts,
                    emit=self.recorder.emit,
                )
                result = await answer(
                    request.config,
                    request.question,
                    ctx=ctx,
                    history=request.history,
                    llm=request.llm,
                    emit=emit,
                    stream=True,
                    client_factory=kit.client_factory,
                )
        except asyncio.CancelledError:
            if not self._answer_started:
                await self._refund()
            raise
        except Exception:
            await self._refund()
            raise
        if not result.generated:
            await self._refund()
        return self._single_shot_outcome(result)

    def _single_shot_outcome(self, result: SingleShotAnswer) -> Outcome:
        if result.cited_keys:
            citations = [
                _reference_citation(reference, key)
                for reference, key in zip(result.sources, result.cited_keys, strict=False)
            ]
        else:
            citations = [_reference_citation(reference, None) for reference in result.sources]
        return Outcome(
            status="done",
            answer=result.answer,
            stop_reason="answered" if result.generated else "no_context",
            citations=citations,
            unresolved=list(result.unresolved),
            standalone_question=result.retrieval.question,
            usage=UsageData(elapsed_seconds=round(time.monotonic() - self._started, 3)),
        )

    async def _claim(self) -> bool:
        """Claims one free-tier message for this run's answer, before it is generated.

        One answer is one message, however many model calls it takes.

        Returns:
            ``False`` when the allowance is already spent. A claim that fails for
            any other reason is logged and the run goes ahead uncharged, as a
            failed charge always has.
        """
        try:
            async with self._sessions() as db:
                claimed = await aclaim_free_chat_message(db, self.request.user_id)
        except Exception:
            logger.warning("could not charge run %s", self.request.run_id, exc_info=True)
            return True
        self._charged = claimed
        return claimed

    async def _refund(self) -> None:
        """Gives back this run's claimed message, once, when no answer was delivered.

        Shielded, because it also runs while the task is being cancelled.
        """
        if not self._charged:
            return
        self._charged = False
        try:
            await asyncio.shield(self._refund_now())
        except Exception:
            logger.warning("could not refund run %s", self.request.run_id, exc_info=True)

    async def _refund_now(self) -> None:
        async with self._sessions() as db:
            await arefund_free_chat_message(db, self.request.user_id)

    def _free_tier_refusal(self) -> Outcome:
        """Ends a run whose claim found the free allowance already spent."""
        message = "You've used all of your free chat questions."
        self.recorder.publish(
            EventType.ERROR, {"message": message, "kind": "free_tier_exhausted", "status": 402}
        )
        return Outcome(status="failed", stop_reason="free_tier_exhausted", error=message)

    # --- finishing ---------------------------------------------------------------

    async def _conclude(self, outcome: Outcome) -> None:
        request, recorder = self.request, self.recorder
        message_id: uuid.UUID | None = None
        if outcome.status == "done":
            if request.save_history:
                try:
                    message_id = await save_turn(
                        self._sessions,
                        run_id=request.run_id,
                        user_id=request.user_id,
                        repository_id=request.repository.id,
                        conversation_id=request.conversation_id,
                        new_conversation=request.new_conversation,
                        question=request.question,
                        answer=outcome.answer,
                        sources=outcome.citations,
                        answered_commit_sha=request.repository.ingested_commit_sha,
                    )
                except Exception:
                    logger.warning(
                        "could not save the turn of run %s", request.run_id, exc_info=True
                    )
            recorder.publish(
                EventType.DONE,
                DoneData(
                    run_id=str(request.run_id),
                    answer=outcome.answer,
                    citations=outcome.citations,
                    unresolved=outcome.unresolved,
                    stop_reason=outcome.stop_reason,
                    usage=outcome.usage,
                    chat_message_id=str(message_id) if message_id else None,
                    conversation_id=(
                        str(request.conversation_id)
                        if message_id and request.conversation_id
                        else None
                    ),
                    steps_dropped=recorder.dropped,
                    limits_reached=outcome.limits_reached,
                ).model_dump(mode="json"),
            )
        await recorder.close()
        await self._finalize(outcome, message_id)

    async def _finalize(self, outcome: Outcome, message_id: uuid.UUID | None) -> None:
        try:
            await finalize_run(
                self._sessions,
                self.request.run_id,
                status=outcome.status,
                stop_reason=outcome.stop_reason or None,
                answer=outcome.answer if outcome.status == "done" else None,
                citations=[c.model_dump(mode="json") for c in outcome.citations],
                usage=outcome.usage.model_dump(mode="json"),
                tool_calls=outcome.usage.tool_calls,
                iterations=outcome.usage.iterations,
                latency_ms=int((time.monotonic() - self._started) * 1000),
                error=outcome.error,
                standalone_question=outcome.standalone_question,
                chat_message_id=message_id,
            )
        except Exception:
            logger.warning("could not finalise run %s", self.request.run_id, exc_info=True)

    async def _conclude_cancelled(self) -> None:
        """Writes what a cancelled run did: its steps so far, no turn, no charge."""
        result = self.recorder.result
        usage = (
            UsageData(
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                tool_calls=result.tool_calls,
                iterations=result.iterations,
                elapsed_seconds=result.elapsed_seconds,
            )
            if result is not None
            else UsageData(elapsed_seconds=round(time.monotonic() - self._started, 3))
        )
        with anyio.CancelScope(shield=True):
            await self.recorder.close()
            await self._finalize(
                Outcome(status="cancelled", stop_reason="cancelled", usage=usage), None
            )
