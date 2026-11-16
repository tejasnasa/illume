"""``ask_illume``: Illume's own grounded answer, with citations, over MCP.

The other tools hand the host raw material; this one runs Illume's whole pipeline
and returns the finished answer. It does that by driving the same
:class:`~app.services.agent.session.RunSession` the web chat uses, after the same
checks (:func:`~app.services.agent.run_request.prepare_run`), so every rule the
chat enforces holds here too: the free tier is charged one message up front and
refunded when no answer is delivered, agent presets need the caller's own key,
a user has a bounded number of runs in flight, and the run is recorded in
``agent_runs`` with its steps and token usage.

What differs from the chat page:

- the run's record carries ``"source": "mcp"`` in its configuration;
- the answer is not saved as a turn of the repository's chat history;
- progress is reported to the client as MCP progress notifications, which also
  keep the stream alive for the length of a long run;
- a client that disconnects cancels the run, which settles it as cancelled and
  gives its slot back;
- the call has a time limit of its own, a little above the run's own budget.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import mcp_types as types
from mcp.server import ServerRequestContext
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.validation import MultiLineText
from app.mcp.auth import current_user_id
from app.mcp.limits import RateLimiter
from app.mcp.repos import McpRepoError, repo_argument, resolve_repo
from app.mcp.tool import McpTool, text_result
from app.models.user import User
from app.services.agent.auto import AUTO
from app.services.agent.events import EventType
from app.services.agent.persistence import SessionOpener
from app.services.agent.run_request import RunRefusal, prepare_run
from app.services.agent.session import RunKit, RunRequest, RunSession
from app.services.agent.slots import RunSlots
from app.services.entitlements import FREE_CHAT_MESSAGES
from app.services.retrieval.config import PipelineConfig

logger = logging.getLogger(__name__)

TOOL_NAME = "ask_illume"
SOURCE = "mcp"
"""What the run's record says asked the question."""

MODES = ("quick", "auto", "deep")
MAX_QUESTION_CHARS = 4000
"""The longest question accepted. The chat route sets no limit of its own."""

SINGLE_SHOT_TIMEOUT_SECONDS = 120.0
"""How long a single-shot answer may take before the call gives up."""

AGENT_TIMEOUT_MARGIN_SECONDS = 15.0
"""Added to an agent run's hard cancel, so the run's own limit is the one that fires."""

ANSWER_PROGRESS_SECONDS = 5.0
"""The least time between two progress notifications about the answer being written."""

_QUESTION_TEXT = TypeAdapter(MultiLineText)

_FREE_TIER_HINT = " Add your own AI key in Illume's settings to keep asking."

DESCRIPTION = (
    "Ask Illume itself a question about a repository and get its finished, grounded answer "
    "with citations, instead of searching the code yourself. `quick` (default) is a single "
    "retrieval-and-answer pass; `auto` lets Illume pick the approach for the question; `deep` "
    "runs a multi-step investigation. `auto` and `deep` run on the user's own AI key and can "
    "take a few minutes; `quick` works on the free tier, where each answer uses one of the "
    "user's free questions. Prefer the search and read tools when you only need to look "
    "something up. Pass `repo` to choose the repository."
)

INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "repo": {
            "type": "string",
            "description": (
                "The repository to ask about: its number, its UUID, or owner/name, as listed "
                "by list_repositories."
            ),
        },
        "question": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_QUESTION_CHARS,
            "description": "The question, in plain language.",
        },
        "mode": {
            "type": "string",
            "enum": list(MODES),
            "default": "quick",
            "description": (
                "`quick`: one fast answer. `auto`: Illume routes the question (own AI key "
                "required). `deep`: a thorough multi-step investigation (own AI key required)."
            ),
        },
    },
    "required": ["repo", "question"],
    "additionalProperties": False,
}


def _error(text: str) -> types.CallToolResult:
    return text_result(text, is_error=True)


def _github_ref(commit_sha: str | None, branch: str | None) -> str:
    """The ref a blob link points at: the ingested commit, else the branch, else ``master``."""
    return commit_sha or branch or "master"


def citation_url(
    citation: dict[str, Any], github_url: str, commit_sha: str | None, branch: str | None
) -> str | None:
    """The GitHub link for a citation, by the rule the chat page's citation cards use.

    Symbols and files link to the file at the ingested commit (a symbol with its
    line range), commits and pull requests to their own pages, anything else to
    nothing.

    Args:
        citation: A citation as the run's final event carries it.
        github_url: The repository's GitHub URL.
        commit_sha: The commit the repository was ingested at.
        branch: The branch it was ingested from, used when there is no commit.

    Returns:
        The URL, or ``None`` when the citation has no link target.
    """
    kind = citation.get("source_type")
    path = citation.get("file_path")
    ref = _github_ref(commit_sha, branch)
    if kind == "symbol" and path:
        start, end = citation.get("start_line"), citation.get("end_line")
        anchor = f"#L{start}-L{end}" if start is not None and end is not None else ""
        return f"{github_url}/blob/{ref}/{path}{anchor}"
    if kind == "file" and path:
        return f"{github_url}/blob/{ref}/{path}"
    if kind == "commit" and citation.get("commit_hash"):
        return f"{github_url}/commit/{citation['commit_hash']}"
    if kind == "pull_request" and citation.get("pr_number") is not None:
        return f"{github_url}/pull/{citation['pr_number']}"
    return None


def structured_citation(
    citation: dict[str, Any], github_url: str, commit_sha: str | None, branch: str | None
) -> dict[str, Any]:
    """One citation in the shape the tool returns.

    Args:
        citation: A citation as the run's final event carries it.
        github_url: The repository's GitHub URL.
        commit_sha: The commit the repository was ingested at.
        branch: The branch it was ingested from.

    Returns:
        ``key``, ``type``, ``path``, ``lines`` (``"start-end"`` or ``None``) and ``url``.
    """
    start, end = citation.get("start_line"), citation.get("end_line")
    return {
        "key": citation.get("key"),
        "type": citation.get("source_type"),
        "path": citation.get("file_path"),
        "lines": f"{start}-{end}" if start is not None and end is not None else None,
        "url": citation_url(citation, github_url, commit_sha, branch),
    }


def _citation_line(entry: dict[str, Any]) -> str:
    label = entry["path"] or entry["type"] or "source"
    if entry["lines"]:
        label = f"{label}:{entry['lines']}"
    key = f"[{entry['key']}] " if entry["key"] else ""
    url = f" <{entry['url']}>" if entry["url"] else ""
    return f"- {key}{label}{url}"


def run_timeout(config: PipelineConfig) -> float:
    """How long a call may wait for a run of this configuration.

    Args:
        config: The run's effective configuration.

    Returns:
        The run's own hard limit plus a margin for an agent run, or the
        single-shot limit.
    """
    if config.execution == "single_shot" or config.agent is None:
        return SINGLE_SHOT_TIMEOUT_SECONDS
    return config.agent.hard_cancel_seconds + AGENT_TIMEOUT_MARGIN_SECONDS


def _progress_message(event_type: EventType, data: dict[str, Any]) -> str | None:
    """What to tell the client about one run event, or ``None`` when it is not worth a note."""
    match event_type:
        case EventType.RUN_STARTED:
            return f"Run started ({data.get('preset')})"
        case EventType.ROUTE:
            return f"Routed to {data.get('resolved_preset')}"
        case EventType.PLAN:
            return "Planned the investigation"
        case EventType.RETRIEVAL:
            return "Retrieved context"
        case EventType.TOOL_CALL:
            return f"Calling {data.get('tool')}"
        case EventType.WORKER_STARTED:
            return "Investigating a sub-question"
        case _:
            return None


@dataclass
class _Finished:
    """What a drained run ended with: its final event, one of the two."""

    done: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class _Progress:
    """Sends progress notifications for one call, never letting a failure reach the run."""

    def __init__(self, ctx: ServerRequestContext[Any]) -> None:
        self._ctx = ctx
        self._count = 0
        self._answer_at: float | None = None

    async def send(self, message: str) -> None:
        self._count += 1
        try:
            await self._ctx.session.report_progress(float(self._count), None, message)
        except Exception:
            logger.debug("could not send a progress notification", exc_info=True)

    async def answering(self) -> None:
        now = time.monotonic()
        if self._answer_at is None or now - self._answer_at >= ANSWER_PROGRESS_SECONDS:
            self._answer_at = now
            await self.send("Writing the answer")


async def _drain(run: RunSession, progress: _Progress) -> _Finished:
    """Reads the run's events until it ends, reporting progress as it goes."""
    finished = _Finished()
    while True:
        event = await run.recorder.stream.get()
        if event is None:
            return finished
        if event.type is EventType.DONE:
            finished.done = event.data
        elif event.type is EventType.ERROR:
            finished.error = event.data
        elif event.type is EventType.ANSWER_DELTA:
            await progress.answering()
        elif (message := _progress_message(event.type, event.data)) is not None:
            await progress.send(message)


def _refusal_text(refusal: RunRefusal) -> str:
    detail = refusal.detail.strip()
    if refusal.status == 402 and detail.startswith("You've used all"):
        return detail + _FREE_TIER_HINT
    if refusal.status == 429:
        return f"{detail} Another run is in progress; try again shortly."
    return detail


def _result(request: RunRequest, finished: _Finished) -> types.CallToolResult:
    if finished.done is None:
        error = finished.error or {}
        message = str(error.get("message") or "The run ended without an answer.").strip()
        if error.get("kind") == "free_tier_exhausted":
            message += _FREE_TIER_HINT
        return _error(f"Illume could not answer: {message}")
    snapshot = request.repository
    answer = str(finished.done.get("answer", ""))
    citations = [
        structured_citation(
            c, snapshot.github_url, snapshot.ingested_commit_sha, snapshot.ingested_branch
        )
        for c in finished.done.get("citations", [])
    ]
    text = answer
    if citations:
        text += "\n\nSources:\n" + "\n".join(_citation_line(c) for c in citations)
    return text_result(
        text,
        structured={
            "answer": answer,
            "citations": citations,
            "usage": finished.done.get("usage", {}),
            "preset": request.preset,
        },
    )


def build_ask_tool(
    session_factory: async_sessionmaker[AsyncSession],
    limiter: RateLimiter,
    *,
    run_sessions: SessionOpener | None = None,
    kit_factory: Callable[[], RunKit] | None = None,
    slots_factory: Callable[[], RunSlots] | None = None,
) -> McpTool:
    """Build the ``ask_illume`` tool.

    Args:
        session_factory: Opens the sessions that check the request.
        limiter: Counts each call against the user's limits.
        run_sessions: Opens the sessions the run writes with. Defaults to
            ``session_factory``; a test passes one whose sessions never overlap.
        kit_factory: Returns the collaborators a run uses. Defaults to production's.
        slots_factory: Returns the per-user concurrency cap. Defaults to production's.

    Returns:
        The tool.
    """
    sessions: SessionOpener = run_sessions or session_factory
    new_kit = kit_factory or RunKit
    new_slots = slots_factory or RunSlots

    async def handler(
        ctx: ServerRequestContext[Any], arguments: dict[str, Any]
    ) -> types.CallToolResult:
        started = time.perf_counter()
        user_id = current_user_id(ctx)

        ref = repo_argument(arguments.get("repo"))
        question = arguments.get("question")
        mode = arguments.get("mode", "quick")
        if ref is None:
            return _error(
                "Invalid arguments: `repo` is required: the repository "
                "number, UUID or owner/name from list_repositories."
            )
        if not isinstance(question, str) or not question.strip():
            return _error("Invalid arguments: `question` is required and must not be empty.")
        if len(question) > MAX_QUESTION_CHARS:
            return _error(
                f"Invalid arguments: `question` is longer than {MAX_QUESTION_CHARS} characters."
            )
        try:
            _QUESTION_TEXT.validate_python(question)
        except ValidationError:
            return _error("Invalid arguments: `question` contains control characters.")
        if mode not in MODES:
            return _error(f"Invalid arguments: `mode` must be one of {', '.join(MODES)}.")

        if limited := await limiter.check_call(user_id):
            return _error(limited.message)

        async with session_factory() as db:
            try:
                repo = await resolve_repo(db, user_id, ref)
            except McpRepoError as error:
                return _error(error.message)
            repo_id = repo.id
            keyless = (await db.scalar(select(User.ai_api_key).where(User.id == user_id))) is None

        if limited := await limiter.check_ask(user_id):
            return _error(limited.message)

        preset = {
            "quick": "classic" if keyless else "hybrid_rerank",
            "auto": AUTO,
            "deep": "deep_agent",
        }[mode]
        kit, slots = new_kit(), new_slots()
        try:
            async with session_factory() as db:
                request = await prepare_run(
                    db,
                    user_id=user_id,
                    repo_id=repo_id,
                    question=question,
                    history=[],
                    preset=preset,
                    overrides=None,
                    sessions=sessions,
                    kit=kit,
                    slots=slots,
                    free_limit=FREE_CHAT_MESSAGES,
                    config_extra={"source": SOURCE},
                    save_history=False,
                )
        except RunRefusal as refusal:
            return _error(_refusal_text(refusal))

        status = "error"
        run = RunSession(request, sessions, slots, kit)
        run.start()
        try:
            progress = _Progress(ctx)
            try:
                async with asyncio.timeout(run_timeout(request.config)):
                    finished = await _drain(run, progress)
            except TimeoutError:
                status = "timeout"
                return _error(
                    "Illume did not finish in time, so the run was stopped. Try `quick` mode "
                    "or a narrower question."
                )
            result = _result(request, finished)
            status = "error" if result.is_error else "ok"
            return result
        finally:
            # Also reached when the client disconnects and this call is cancelled:
            # the run is stopped, settled as cancelled, and its slot given back.
            await run.cleanup()
            logger.info(
                "mcp_ask user=%s repo=%s mode=%s preset=%s status=%s ms=%.0f",
                user_id,
                repo_id,
                mode,
                request.preset,
                status,
                (time.perf_counter() - started) * 1000,
            )

    return McpTool(
        definition=types.Tool(
            name=TOOL_NAME,
            title="Ask Illume",
            description=DESCRIPTION,
            input_schema=INPUT_SCHEMA,
            annotations=types.ToolAnnotations(
                title="Ask Illume",
                read_only_hint=True,
                destructive_hint=False,
                idempotent_hint=False,
                open_world_hint=True,
            ),
        ),
        handler=handler,
    )
