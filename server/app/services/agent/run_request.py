"""Everything a question must pass before a run starts, shared by every way of asking.

The streaming route and the MCP ``ask_illume`` tool both start the same
:class:`~app.services.agent.session.RunSession`. What comes before it is policy,
not transport, so it lives here once: the repository belongs to the caller and is
ready, the overrides fit the preset, a credential exists, agent presets have a key
of the caller's own whose model can call tools, the free-tier allowance is not
spent, and a run slot is free. Only then is the ``running`` row inserted and a
:class:`~app.services.agent.session.RunRequest` returned.

A check that fails raises :class:`RunRefusal`, which carries the HTTP status the
streaming route answers with and the text it shows. The route turns it into an
``HTTPException`` unchanged; the MCP tool turns it into an error result. Nothing
that costs a model call happens before every check has passed.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import Repository
from app.models.user import User
from app.services.agent.auto import AUTO, AutoRoute, resolve_auto
from app.services.agent.overrides import OverrideError, Overrides, apply_overrides
from app.services.agent.persistence import SessionOpener, create_run
from app.services.agent.prompts import PROMPT_VERSION
from app.services.agent.session import RunKit, RunRequest
from app.services.agent.slots import RunSlots
from app.services.agent.tools.context import RepoSnapshot
from app.services.decisions.openrouter import JEV_MODEL
from app.services.conversations import owned_conversation
from app.services.entitlements import llm_config_for
from app.services.rag import ChatMessage
from app.services.retrieval.config import PRESETS, PipelineConfig
from app.services.retrieval.single_shot import is_classic_shaped
from app.services.tool_support import ensure_tool_support

logger = logging.getLogger(__name__)

CLASSIC_HISTORY_MESSAGES = 5
"""Prior messages a Classic-shaped run replays, as the chat endpoint does."""

MAX_HISTORY_MESSAGES = 20
"""The most prior messages any preset can replay."""


class RunRefusal(Exception):
    """A question that may not start a run.

    Attributes:
        status: The HTTP status the streaming route answers with.
        detail: What to tell the asker.
    """

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def model_label(owner: User, model: str) -> str:
    """``provider:model``, with ``server`` for the operator's free-tier credential."""
    provider = owner.ai_provider if owner.ai_api_key else None
    return f"{provider or 'server'}:{model}"


def decider_label(config: PipelineConfig, model: str) -> str | None:
    """``jev:<model id>`` or ``llm:<model>``; ``None`` when the run asks no decisions."""
    asks = config.execution != "single_shot" or config.rerank.kind == "jev"
    if not asks:
        return None
    return f"jev:{JEV_MODEL}" if config.decider == "jev" else f"llm:{model}"


async def _known(value: bool | None) -> bool | None:
    """A tool-support verdict that was already measured, as an awaitable."""
    return value


async def owned_repository(db: AsyncSession, repo_id: uuid.UUID, user_id: Any) -> Repository:
    """The repository, if it is the caller's.

    Raises:
        RunRefusal: 404 when there is no such repository for this user.
    """
    repo = (
        await db.execute(
            select(Repository).filter(Repository.id == repo_id, Repository.user_id == user_id)
        )
    ).scalar_one_or_none()
    if repo is None:
        raise RunRefusal(404, "Repository not found")
    return repo


async def prepare_run(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    repo_id: uuid.UUID,
    question: str,
    history: Sequence[ChatMessage],
    preset: str,
    overrides: Overrides | None,
    sessions: SessionOpener,
    kit: RunKit,
    slots: RunSlots,
    free_limit: int,
    config_extra: dict[str, Any] | None = None,
    save_history: bool = True,
    conversation_id: uuid.UUID | None = None,
) -> RunRequest:
    """Runs every check a question must pass and records the run as ``running``.

    On success a run slot is held and the caller owns it: it must hand the
    request to a :class:`~app.services.agent.session.RunSession`, whose cleanup
    gives the slot back. On any refusal or failure no slot is held.

    The checks, in order: the repository is the caller's (404) and ready (400);
    the overrides fit the preset (422); a credential exists (402); agent presets
    have a key of the caller's own (402) whose model can call tools (400); the
    free-tier allowance is not spent (402); the caller has a free run slot (429).
    ``auto`` needs the caller's own key, and once a slot is held one routing
    decision on the operator's key picks the preset, which the overrides are then
    checked against (422).

    Args:
        db: Async session for the checks only. It is committed before the slot is
            taken, so no transaction stays open for the length of the run.
        user_id: The asking user.
        repo_id: The repository to ask about.
        question: The question as typed.
        history: Earlier turns, oldest first, not yet bounded.
        preset: A preset name, or ``auto``.
        overrides: Settings changed for this run only.
        sessions: Opens the sessions the run writes with.
        kit: Collaborators a test replaces.
        slots: The per-user concurrency cap.
        free_limit: The free-tier allowance the early check compares against.
        config_extra: Keys added to the run row's ``config`` record, such as where
            the question came from. They are not part of the configuration hash.
        save_history: Whether the run's answer is saved as a chat turn.
        conversation_id: The conversation the turn joins; a conversation that is
            not the caller's is a 404 refusal, checked right after the repository.
            When ``None`` and the turn is saved, a new conversation id is chosen;
            its row is written only when the turn is saved, so a run that ends
            without an answer leaves no conversation behind.

    Returns:
        The resolved run, already inserted as a ``running`` row.

    Raises:
        RunRefusal: A check failed.
    """
    repo = await owned_repository(db, repo_id, user_id)
    if repo.status != "ready":
        raise RunRefusal(400, f"Repository is not ready for querying (status: {repo.status})")
    new_conversation = False
    if save_history:
        if conversation_id is None:
            conversation_id = uuid.uuid4()
            new_conversation = True
        elif await owned_conversation(db, user_id, repo_id, conversation_id) is None:
            raise RunRefusal(404, "Conversation not found")
    else:
        conversation_id = None

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
    is_auto = preset == AUTO
    config: PipelineConfig | None = None
    if not is_auto:
        try:
            config = apply_overrides(PRESETS[preset], overrides, own_key=own_key)
        except OverrideError as error:
            raise RunRefusal(422, str(error)) from error

    llm_config = llm_config_for(owner)
    if owner is None or llm_config is None:
        raise RunRefusal(
            402,
            "Add your own API key to ask questions about this repository. "
            "Configure one in your account settings.",
        )

    assert user_id is not None  # an owner was found by it
    on_free_tier = owner.ai_api_key is None
    supports_tools: bool | None = None
    if is_auto:
        if on_free_tier:
            raise RunRefusal(
                402,
                "Auto picks a preset per question and runs on your own API key. "
                "Add one in your account settings to use it.",
            )
        supports_tools = await ensure_tool_support(db, owner)
    elif config is not None and config.execution != "single_shot":
        if on_free_tier:
            raise RunRefusal(
                402,
                "Agent presets run on your own API key. "
                "Add one in your account settings to use them.",
            )
        supports_tools = await ensure_tool_support(db, owner)
        if supports_tools is False:
            raise RunRefusal(
                400,
                "The model behind your API key does not support tool calling, "
                "which agent presets need. Choose a single-shot preset or change the model.",
            )
    if on_free_tier and owner.free_chat_messages_used >= free_limit:
        raise RunRefusal(402, "You've used all of your free chat questions. ")

    # Copy what the run needs out of the ORM rows, then end the request's
    # transaction: the run outlives this call and must not hold a connection.
    snapshot = RepoSnapshot.from_repository(repo)
    context_window = (
        overrides.agent.context_window
        if overrides and overrides.agent and overrides.agent.context_window
        else owner.ai_context_window
    )
    github_token = owner.github_access_token
    label = model_label(owner, llm_config.model)
    await db.commit()

    if not await slots.acquire(user_id):
        raise RunRefusal(429, "Too many answers are running at once. Wait for one to finish.")

    run_id = uuid.uuid4()
    auto: AutoRoute | None = None
    try:
        if is_auto:
            auto = await resolve_auto(
                question,
                list(history),
                decider=kit.decider,
                supports_tools=lambda: _known(supports_tools),
            )
            try:
                config = apply_overrides(PRESETS[auto.resolved_preset], overrides, own_key=own_key)
            except OverrideError as error:
                raise RunRefusal(422, str(error)) from error
        assert config is not None
        resolved_preset = auto.resolved_preset if auto is not None else preset
        bound = CLASSIC_HISTORY_MESSAGES if is_classic_shaped(config) else MAX_HISTORY_MESSAGES
        bounded = list(history[-bound:])
        await create_run(
            sessions,
            run_id=run_id,
            user_id=user_id,
            repository_id=repo_id,
            question=question,
            preset=resolved_preset,
            config={**config.model_dump(mode="json"), **(config_extra or {})},
            config_hash=config.config_hash(),
            prompt_version=PROMPT_VERSION if config.execution != "single_shot" else None,
            model=label,
            decider=decider_label(config, llm_config.model),
            ingested_commit_sha=snapshot.ingested_commit_sha,
        )
    except BaseException:
        await slots.release(user_id)
        raise

    return RunRequest(
        run_id=run_id,
        user_id=user_id,
        repository=snapshot,
        question=question,
        history=bounded,
        preset=resolved_preset,
        config=config,
        llm=llm_config,
        model_label=label,
        github_token=github_token,
        context_window=context_window,
        on_free_tier=on_free_tier,
        auto=auto,
        save_history=save_history,
        conversation_id=conversation_id,
        new_conversation=new_conversation,
    )
