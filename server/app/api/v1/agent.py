"""Streaming answers and the list of a repository's runs.

``POST /{repo_id}/chat/stream`` answers a question with any preset and streams
what happens as server-sent events. It makes the same ownership, readiness and
quota checks as ``POST /{repo_id}/chat``, then hands the run to a
:class:`~app.services.agent.session.RunSession`, which records it so that
``GET /{repo_id}/agent-runs`` can list it afterwards.

The request is authenticated by the session cookie like every other route:
there is no token in the URL, which is why the stream is a ``POST`` read with
``fetch`` rather than an ``EventSource``.
"""

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette import EventSourceResponse
from starlette.background import BackgroundTask

from app.api.v1.chat import ChatMessageRequest
from app.api.validation import MultiLineText
from app.core.database import AsyncSessionLocal, get_async_db
from app.models.agent_run import AgentRun
from app.models.repository import Repository
from app.models.user import User
from app.services.agent.auto import AUTO, AutoRoute, resolve_auto
from app.services.agent.overrides import OverrideError, Overrides, apply_overrides
from app.services.agent.persistence import (
    create_run,
    last_activity,
    public_status,
)
from app.services.agent.prompts import PROMPT_VERSION
from app.services.agent.session import RunKit, RunRequest, RunSession
from app.services.agent.slots import RunSlots
from app.services.agent.tools.context import RepoSnapshot
from app.services.decisions.openrouter import JEV_MODEL
from app.services.entitlements import FREE_CHAT_MESSAGES, llm_config_for
from app.services.rag import ChatMessage
from app.services.retrieval.config import PRESETS, PipelineConfig
from app.services.retrieval.single_shot import is_classic_shaped
from app.services.tool_support import ensure_tool_support

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/repository", tags=["agent"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
SSE_PING_SECONDS = 15

CLASSIC_HISTORY_MESSAGES = 5
"""Prior messages a Classic-shaped run replays, as the chat endpoint does."""

MAX_HISTORY_MESSAGES = 20
"""The most prior messages any preset can replay."""

SessionOpener = Callable[[], AbstractAsyncContextManager[AsyncSession]]


# --- seams ---------------------------------------------------------------------------


def get_run_sessions() -> SessionOpener:
    """Opens the sessions a run writes with; each is its own, never the request's."""
    return AsyncSessionLocal


def get_run_kit() -> RunKit:
    """The collaborators a run uses; production defaults."""
    return RunKit()


def get_run_slots() -> RunSlots:
    """The per-user concurrency cap."""
    return RunSlots()


# --- request and response models -----------------------------------------------------


class StreamRequest(BaseModel):
    """A question for the streaming endpoint.

    Attributes:
        question: The question; multi-line, like the chat composer's.
        history: Earlier turns, oldest first.
        preset: A preset name, or ``auto`` to have one decision pick the preset
            from the question. ``auto`` needs the caller's own key.
        overrides: Settings changed for this run only; they apply to the preset
            ``auto`` resolves to. See
            :mod:`app.services.agent.overrides` for what is accepted.
    """

    model_config = ConfigDict(extra="forbid")

    question: MultiLineText
    history: list[ChatMessageRequest] = []
    preset: str = "classic"
    overrides: Overrides | None = None

    @field_validator("preset")
    @classmethod
    def _known_preset(cls, value: str) -> str:
        if value != AUTO and value not in PRESETS:
            raise ValueError(f"unknown preset {value!r}; choose one of {sorted([AUTO, *PRESETS])}")
        return value


class AgentRunSummary(BaseModel):
    """One run, without its events.

    Attributes:
        id: The run.
        question: What was asked.
        preset: The preset that answered.
        status: ``running``, ``done``, ``failed``, ``cancelled`` or
            ``interrupted`` (a run whose process died before it finished).
        stop_reason: Why the run stopped.
        model: ``provider:model`` of the generation model.
        config_hash: Hash of the effective configuration.
        ingested_commit_sha: The snapshot the run answered against.
        chat_message_id: The saved chat turn, when there is one.
        tool_calls: Tool calls made.
        iterations: Model turns taken.
        latency_ms: Wall time of the run.
        input_tokens: Tokens the model read across the run.
        output_tokens: Tokens the model wrote across the run.
        error: Why it failed, when it did.
        created_at: When it started.
        finished_at: When it ended.
    """

    id: uuid.UUID
    question: str
    preset: str
    status: str
    stop_reason: str | None
    model: str | None
    config_hash: str
    ingested_commit_sha: str | None
    chat_message_id: uuid.UUID | None
    tool_calls: int | None
    iterations: int | None
    latency_ms: int | None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None
    created_at: datetime
    finished_at: datetime | None


def _summary_fields(run: AgentRun, status: str) -> dict[str, Any]:
    return {
        "id": run.id,
        "question": run.question,
        "preset": run.preset,
        "status": status,
        "stop_reason": run.stop_reason,
        "model": run.model,
        "config_hash": run.config_hash,
        "ingested_commit_sha": run.ingested_commit_sha,
        "chat_message_id": run.chat_message_id,
        "tool_calls": run.tool_calls,
        "iterations": run.iterations,
        "latency_ms": run.latency_ms,
        "input_tokens": (run.usage or {}).get("input_tokens"),
        "output_tokens": (run.usage or {}).get("output_tokens"),
        "error": run.error,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
    }


# --- helpers -------------------------------------------------------------------------


async def _owned_repository(db: AsyncSession, repo_id: uuid.UUID, user_id: Any) -> Repository:
    repo = (
        await db.execute(
            select(Repository).filter(Repository.id == repo_id, Repository.user_id == user_id)
        )
    ).scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


def _model_label(owner: User, model: str) -> str:
    """``provider:model``, with ``server`` for the operator's free-tier credential."""
    provider = owner.ai_provider if owner.ai_api_key else None
    return f"{provider or 'server'}:{model}"


def _decider_label(config: PipelineConfig, model: str) -> str | None:
    """``jev:<model id>`` or ``llm:<model>``; ``None`` when the run asks no decisions."""
    asks = config.execution != "single_shot" or config.rerank.kind == "jev"
    if not asks:
        return None
    return f"jev:{JEV_MODEL}" if config.decider == "jev" else f"llm:{model}"


async def _known(value: bool | None) -> bool | None:
    """A tool-support verdict that was already measured, as an awaitable."""
    return value


# --- routes --------------------------------------------------------------------------


@router.post("/{repo_id}/chat/stream")
async def stream_chat(
    repo_id: uuid.UUID,
    payload: StreamRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    sessions: SessionOpener = Depends(get_run_sessions),
    kit: RunKit = Depends(get_run_kit),
    slots: RunSlots = Depends(get_run_slots),
):
    """Answer a question with a preset and stream the run as server-sent events.

    Checks, in order: the repository is the caller's (404) and ready (400); the
    overrides fit the preset (422); a credential exists (402); agent presets have a
    key of the caller's own (402) whose model can call tools (400); the free-tier
    allowance is not spent (402); the caller has a free run slot (429). Nothing
    that costs a model call happens before all of them pass.

    ``auto`` needs the caller's own key (402 on the free tier). Once a slot is
    held, one routing decision on the operator's key picks the preset, which then
    runs as if it had been requested; the overrides are checked against that
    preset (422). The decision itself never fails the request: it falls back to
    ``structural``.

    Each event is ``event: <type>`` with the envelope as JSON in ``data``. The
    stream ends with ``done`` or ``error``. A client that disconnects cancels the
    run; the steps taken so far are kept.

    Args:
        repo_id: ID of the repository to query.
        payload: Question, history, preset and overrides.
        request: Request carrying the authenticated user ID in state.
        db: Async session for the checks only; it is released before streaming.
        sessions: Opens the sessions the run writes with.
        kit: Collaborators a test replaces.
        slots: The per-user concurrency cap.

    Returns:
        An event stream.

    Raises:
        HTTPException: 400, 402, 404, 422 or 429 as above.
    """
    user_id = getattr(request.state, "user_id", None)
    repo = await _owned_repository(db, repo_id, user_id)
    if repo.status != "ready":
        raise HTTPException(
            status_code=400,
            detail=f"Repository is not ready for querying (status: {repo.status})",
        )

    owner = (
        (
            await db.execute(
                select(User).where(User.id == user_id).execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if user_id
        else None
    )
    # What the drawer may change depends on who pays for the extra calls.
    own_key = owner is not None and owner.ai_api_key is not None
    is_auto = payload.preset == AUTO
    config: PipelineConfig | None = None
    if not is_auto:
        try:
            config = apply_overrides(PRESETS[payload.preset], payload.overrides, own_key=own_key)
        except OverrideError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    llm_config = llm_config_for(owner)
    if owner is None or llm_config is None:
        raise HTTPException(
            status_code=402,
            detail=(
                "Add your own API key to ask questions about this repository. "
                "Configure one in your account settings."
            ),
        )

    on_free_tier = owner.ai_api_key is None
    supports_tools: bool | None = None
    if is_auto:
        if on_free_tier:
            raise HTTPException(
                status_code=402,
                detail=(
                    "Auto picks a preset per question and runs on your own API key. "
                    "Add one in your account settings to use it."
                ),
            )
        supports_tools = await ensure_tool_support(db, owner)
    elif config is not None and config.execution != "single_shot":
        if on_free_tier:
            raise HTTPException(
                status_code=402,
                detail=(
                    "Agent presets run on your own API key. "
                    "Add one in your account settings to use them."
                ),
            )
        supports_tools = await ensure_tool_support(db, owner)
        if supports_tools is False:
            raise HTTPException(
                status_code=400,
                detail=(
                    "The model behind your API key does not support tool calling, "
                    "which agent presets need. Choose a single-shot preset or change the model."
                ),
            )
    if on_free_tier and owner.free_chat_messages_used >= FREE_CHAT_MESSAGES:
        raise HTTPException(
            status_code=402,
            detail="You've used all of your free chat questions. ",
        )

    # Copy what the run needs out of the ORM rows, then end the request's
    # transaction: the stream outlives this handler and must not hold a connection.
    snapshot = RepoSnapshot.from_repository(repo)
    context_window = (
        payload.overrides.agent.context_window
        if payload.overrides and payload.overrides.agent and payload.overrides.agent.context_window
        else owner.ai_context_window
    )
    github_token = owner.github_access_token
    model_label = _model_label(owner, llm_config.model)
    await db.commit()

    if not await slots.acquire(user_id):
        raise HTTPException(
            status_code=429,
            detail="Too many answers are running at once. Wait for one to finish.",
        )

    run_id = uuid.uuid4()
    auto: AutoRoute | None = None
    try:
        if is_auto:
            auto = await resolve_auto(
                payload.question,
                [ChatMessage(role=m.role, content=m.content) for m in payload.history],
                decider=kit.decider,
                supports_tools=lambda: _known(supports_tools),
            )
            try:
                config = apply_overrides(
                    PRESETS[auto.resolved_preset], payload.overrides, own_key=own_key
                )
            except OverrideError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
        assert config is not None
        resolved_preset = auto.resolved_preset if auto is not None else payload.preset
        bound = CLASSIC_HISTORY_MESSAGES if is_classic_shaped(config) else MAX_HISTORY_MESSAGES
        history = [ChatMessage(role=m.role, content=m.content) for m in payload.history[-bound:]]
        await create_run(
            sessions,
            run_id=run_id,
            user_id=user_id,
            repository_id=repo_id,
            question=payload.question,
            preset=resolved_preset,
            config=config.model_dump(mode="json"),
            config_hash=config.config_hash(),
            prompt_version=PROMPT_VERSION if config.execution != "single_shot" else None,
            model=model_label,
            decider=_decider_label(config, llm_config.model),
            ingested_commit_sha=snapshot.ingested_commit_sha,
        )
    except BaseException:
        await slots.release(user_id)
        raise

    run = RunSession(
        RunRequest(
            run_id=run_id,
            user_id=user_id,
            repository=snapshot,
            question=payload.question,
            history=history,
            preset=resolved_preset,
            config=config,
            llm=llm_config,
            model_label=model_label,
            github_token=github_token,
            context_window=context_window,
            on_free_tier=on_free_tier,
            auto=auto,
        ),
        sessions,
        slots,
        kit,
    )
    run.start()
    return EventSourceResponse(
        run.frames(),
        ping=SSE_PING_SECONDS,
        headers=SSE_HEADERS,
        background=BackgroundTask(run.cleanup),
    )


@router.get("/{repo_id}/agent-runs", response_model=list[AgentRunSummary])
async def list_agent_runs(
    repo_id: uuid.UUID,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_async_db),
):
    """List the caller's runs on a repository, newest first.

    Args:
        repo_id: ID of the repository.
        request: Request carrying the authenticated user ID in state.
        limit: How many runs to return.
        db: Async database session.

    Returns:
        The runs, without their events.

    Raises:
        HTTPException: 404 if the repository is not the caller's.
    """
    user_id = getattr(request.state, "user_id", None)
    await _owned_repository(db, repo_id, user_id)
    runs = (
        (
            await db.execute(
                select(AgentRun)
                .where(AgentRun.repository_id == repo_id, AgentRun.user_id == user_id)
                .order_by(AgentRun.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    seen = await last_activity(db, [run.id for run in runs if run.status == "running"])
    return [
        AgentRunSummary(**_summary_fields(run, public_status(run, seen.get(run.id))))
        for run in runs
    ]
