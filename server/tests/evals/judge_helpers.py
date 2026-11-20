"""A scripted judge model and small gold sets shared by the judge-pass tests."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from evals.arms import Arm, get_arm
from evals.gold.schema import GoldItem, make_item
from evals.run.endpoint import JudgeEndpoint
from evals.run.records import CandidateRecord, Generation, Usage
from tests.evals.run_helpers import GENERATOR

BASE = "c" * 40
CITED = "F:app/auth/security.py:10-20"

DEFAULT_REPLIES: dict[str, Any] = {
    "ReasonScore": {"reason": "matches the reference", "score": 3},
    "Truths": {"truths": ["a fact in the evidence"]},
    "Claims": {"claims": ["claim one", "claim two"]},
    "Statements": {"statements": ["statement one", "statement two"]},
    "Verdicts": {
        "verdicts": [{"verdict": "yes", "reason": None}, {"verdict": "yes", "reason": None}]
    },
}
"""What the fake judge answers per schema when a test scripts nothing else."""


def verdicts(*values: str) -> dict[str, Any]:
    """A ``Verdicts`` reply with one verdict per value (``yes``, ``no`` or ``borderline``)."""
    return {"verdicts": [{"verdict": v, "reason": None} for v in values]}


class FakeJudge:
    """A judge client that answers DeepEval's structured calls from a script, offline.

    It speaks both the Responses API and chat completions. The schema DeepEval asked for is read
    from the request (the format name on the Responses API, the schema's title in the prompt on
    chat), and the reply for that schema comes from ``replies``: a value, or a callable of the
    call's prompt text. Every request is recorded verbatim.

    Args:
        replies: Overrides of ``DEFAULT_REPLIES`` by schema name.
        delay: Seconds each call waits, to exercise timeouts.
        error: Raised from every call instead of answering.
        reject_structured: Raise a bad request when a structured format is asked for.
        report_usage: Whether responses carry token usage.
    """

    def __init__(
        self,
        replies: dict[str, Any] | None = None,
        *,
        delay: float = 0.0,
        error: Exception | None = None,
        reject_structured: bool = False,
        report_usage: bool = True,
    ) -> None:
        self.replies = {**DEFAULT_REPLIES, **(replies or {})}
        self.delay = delay
        self.error = error
        self.reject_structured = reject_structured
        self.report_usage = report_usage
        self.requests: list[dict[str, Any]] = []
        self.responses = SimpleNamespace(create=self._responses)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.client_kwargs: dict[str, Any] = {}

    def factory(self, **kwargs: Any) -> FakeJudge:
        """Stands in for ``AsyncOpenAI``; remembers the keyword arguments it got."""
        self.client_kwargs = kwargs
        return self

    @property
    def calls(self) -> int:
        """How many requests were made."""
        return len(self.requests)

    def texts(self) -> list[str]:
        """The prompt text of every request, in order."""
        return [_text_of(request) for request in self.requests]

    def names(self) -> list[str]:
        """The schema name of every request, in order (``reply`` for a plain one)."""
        return [_schema_name(request) for request in self.requests]

    def _reply(self, request: dict[str, Any]) -> str:
        name = _schema_name(request)
        value = self.replies.get(name, "")
        if callable(value):
            value = value(_text_of(request))
        return value if isinstance(value, str) else json.dumps(value)

    async def _wait_and_check(self, request: dict[str, Any]) -> None:
        self.requests.append(copy.deepcopy(request))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error

    async def _responses(self, **kwargs: Any) -> Any:
        await self._wait_and_check(kwargs)
        if self.reject_structured and "text" in kwargs:
            raise _bad_request()
        usage = (
            SimpleNamespace(
                input_tokens=1000,
                output_tokens=50,
                input_tokens_details=SimpleNamespace(cached_tokens=0),
            )
            if self.report_usage
            else None
        )
        return SimpleNamespace(
            output_text=self._reply(kwargs), usage=usage, model="reported-judge-model"
        )

    async def _chat(self, **kwargs: Any) -> Any:
        await self._wait_and_check(kwargs)
        if self.reject_structured and "response_format" in kwargs:
            raise _bad_request()
        usage = (
            SimpleNamespace(
                prompt_tokens=1000,
                completion_tokens=50,
                prompt_tokens_details=SimpleNamespace(cached_tokens=0),
            )
            if self.report_usage
            else None
        )
        return SimpleNamespace(
            model="reported-chat-model",
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._reply(kwargs)))],
            usage=usage,
        )


def _bad_request() -> Exception:
    import httpx
    from openai import BadRequestError

    return BadRequestError(
        "no structured output",
        response=httpx.Response(400, request=httpx.Request("POST", "http://x")),
        body=None,
    )


def _text_of(request: dict[str, Any]) -> str:
    parts = request.get("input") or request.get("messages") or []
    return "\n".join(str(part["content"]) for part in parts)


def _schema_name(request: dict[str, Any]) -> str:
    named = ((request.get("text") or {}).get("format") or {}).get("name")
    if named:
        return str(named)
    titles = re.findall(r'"title": "(\w+)"', _text_of(request))
    return titles[-1] if titles else "reply"


def endpoint(model: str = "gpt-6-luna", base_url: str | None = None, **kw: Any) -> JudgeEndpoint:
    """A judge endpoint with a dummy key."""
    return JudgeEndpoint(model=model, base_url=base_url, api_key=kw.pop("api_key", "k-test"), **kw)


def item(family: str, n: int, **fields: Any) -> GoldItem:
    """A small gold item of a family."""
    base: dict[str, Any] = {
        "repo": "example/sample",
        "base_commit": BASE,
        "family": family,
        "template": f"{family}.t",
        "question": f"What does feature {family}{n} do?",
        "question_seed": f"{family} {n}",
        "gold_files": (f"app/{family}{n}.py",),
        "gold_answer_notes": (f"Feature {n} validates input.",),
    }
    if family == "rationale":
        base["circular_with"] = ("history",)
    elif family == "structural":
        base["circular_with"] = ("graph",)
    elif family == "changeset":
        base.update(
            cluster=f"example#{n // 2}",
            merges_since_base=n,
            template="changeset.blind",
            question_seed=f"Add input validation {n}\n\nThe handler now rejects empty input.",
        )
    base.update(fields)
    return make_item(**base)


def generation(
    gold: GoldItem,
    arm: str | Arm = "classic",
    *,
    key: str | None = None,
    answer: str | None = None,
    status: str = "ok",
    **fields: Any,
) -> Generation:
    """A recorded generation of an item by an arm."""
    chosen = get_arm(arm) if isinstance(arm, str) else arm
    fields = {
        "cited_keys": [CITED],
        "candidates": [CandidateRecord(key=CITED, rank=1, source_type="symbol")],
        **fields,
    }
    if status == "error":
        fields["error"] = "boom"
    return Generation(
        record_key=key or hashlib.sha256(f"{gold.id}:{chosen.name}".encode()).hexdigest()[:16],
        item_id=gold.id,
        arm=chosen.name,
        config_hash=chosen.config_hash(),
        model=chosen.model or GENERATOR,
        answer=answer if answer is not None else f"It validates input [{CITED}].\n\nFiles:\n- x.py",
        status=status,  # type: ignore[arg-type]
        **fields,
    )


def evidence(text: str = "def check(value): ...") -> Callable[[Any], Callable[[str], str | None]]:
    """An ``evidence_for`` that answers the standard cited key with ``text``."""
    return lambda gold: {CITED: text}.get


def usage(model: str = "gpt-6-luna") -> Usage:
    return Usage(provider="openai", model=model, kind="judge", input_tokens=100)
