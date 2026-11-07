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
  far are written, the run is marked cancelled, and no turn is saved or charged.

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

from app.services.agent.deps import ResultScreen, Verifier
from app.services.agent.errors import describe_error
from app.services.agent.events import (
    CitationData,
    DoneData,
    EventType,
    UsageData,
    VerificationData,
)
from app.services.agent.guard import RoundScreen
from app.services.agent.persistence import (
    RunRecorder,
    SessionOpener,
    citation_from_evidence,
    finalize_run,
    save_turn,
)
from app.services.agent.runner import RunResult, run_agent
from app.services.agent.slots import RunSlots
from app.services.agent.tools.context import RepoSnapshot
from app.services.decisions import Decider
from app.services.entitlements import aclaim_free_chat_message
from app.services.llm_config import LLMConfig
from app.services.rag import ChatMessage
from app.services.retrieval.channels.base import Embedder, RetrievalContext
from app.services.retrieval.config import PipelineConfig
from app.services.retrieval.embedding import embed_texts
from app.services.retrieval.resolve import SourceReference
from app.services.retrieval.single_shot import SingleShotAnswer, answer

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
        decider: Makes the gate's, verifier's and guard's decisions.
        verifier: Checks the answer's citations.
        round_screen: Screens a round of tool results for injected instructions.
        screen: Inspects one tool result.
    """

    client_factory: Any = None
    embed: Embedder | None = None
    decider: Decider | None = None
    verifier: Verifier | None = None
    round_screen: RoundScreen | None = None
    screen: ResultScreen | None = None


@dataclass(frozen=True)
class RunRequest:
    """Everything resolved about a run before it starts.

    Attributes:
        run_id: The run's id, already inserted as a ``running`` row.
        user_id: The asking user.
        repository: The repository, copied out of its row.
        question: The question as typed.
        history: Earlier turns, oldest first, already bounded.
        preset: The preset the request named.
        config: The effective configuration, overrides applied.
        llm: The generation credential.
        model_label: ``provider:model`` for the run's record.
        github_token: The owner's GitHub token, for reading whole files.
        context_window: The input window one model call may carry, or ``None``
            for the configuration's.
        on_free_tier: Whether a generated answer is charged to the free tier.
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


@dataclass
class Outcome:
    """How a run that was not cancelled ended.

    Attributes:
        status: ``done`` or ``failed``.
        answer: The answer; empty when the run failed.
        stop_reason: Why the run stopped.
        citations: The evidence the answer cites.
        unresolved: Cited keys that match nothing the run saw.
        verification: The citation check's report, when one ran.
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
    verification: dict[str, Any] | None = None
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

    async def _execute(self) -> Outcome:
        request = self.request
        self.recorder.publish(
            EventType.RUN_STARTED,
            {
                "preset": request.preset,
                "config_hash": request.config.config_hash(),
                "model": request.model_label,
                "execution": request.config.execution,
            },
        )
        if request.config.execution == "single_shot":
            return await self._single_shot()
        return await self._agent()

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
            verifier=kit.verifier,
            screen=kit.screen,
            round_screen=kit.round_screen,
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
            verification=result.verification.to_dict() if result.verification else None,
            standalone_question=None,
            usage=usage,
            limits_reached=list(result.limits_reached),
        )

    async def _single_shot(self) -> Outcome:
        request, kit = self.request, self._kit
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
                emit=self.recorder.emit,
                stream=True,
                client_factory=kit.client_factory,
                decider=kit.decider,
            )
        if request.on_free_tier and result.generated:
            await self._charge()
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
            verification=result.verification.to_dict() if result.verification else None,
            standalone_question=result.retrieval.question,
            usage=UsageData(elapsed_seconds=round(time.monotonic() - self._started, 3)),
        )

    async def _charge(self) -> None:
        """Charges the free tier once, for the one answer, however many calls it took."""
        try:
            async with self._sessions() as db:
                await aclaim_free_chat_message(db, self.request.user_id)
        except Exception:
            logger.warning("could not charge run %s", self.request.run_id, exc_info=True)

    # --- finishing ---------------------------------------------------------------

    async def _conclude(self, outcome: Outcome) -> None:
        request, recorder = self.request, self.recorder
        message_id: uuid.UUID | None = None
        if outcome.status == "done":
            try:
                message_id = await save_turn(
                    self._sessions,
                    run_id=request.run_id,
                    user_id=request.user_id,
                    repository_id=request.repository.id,
                    question=request.question,
                    answer=outcome.answer,
                    sources=outcome.citations,
                )
            except Exception:
                logger.warning("could not save the turn of run %s", request.run_id, exc_info=True)
            verification = (
                VerificationData.model_validate(outcome.verification)
                if outcome.verification
                else None
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
                    verification=verification,
                    chat_message_id=str(message_id) if message_id else None,
                    steps_dropped=recorder.dropped,
                    limits_reached=outcome.limits_reached,
                ).model_dump(mode="json"),
            )
        await recorder.close()
        await self._finalize(outcome, message_id)

    async def _finalize(self, outcome: Outcome, message_id: uuid.UUID | None) -> None:
        verification = outcome.verification
        try:
            await finalize_run(
                self._sessions,
                self.request.run_id,
                status=outcome.status,
                stop_reason=outcome.stop_reason or None,
                answer=outcome.answer if outcome.status == "done" else None,
                citations=[c.model_dump(mode="json") for c in outcome.citations],
                verification=verification,
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
