"""Scripted judges and small gold sets shared by the judge-pass tests."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

from evals.arms import Arm, get_arm
from evals.gold.schema import GoldItem, make_item
from evals.run.endpoint import JudgeEndpoint
from evals.run.records import CandidateRecord, Generation, Usage
from tests.evals.run_helpers import GENERATOR
from tests.fixtures.agent_run import say

BASE = "c" * 40
CITED = "F:app/auth/security.py:10-20"


def verdict_json(correct: int = 3, faithful: int = 2, abstained: bool = False, **extra: Any) -> str:
    """The text of a well-formed judgment."""
    return json.dumps(
        {
            "correct": correct,
            "faithful": faithful,
            "abstained": abstained,
            "rationale": "matches the notes",
            **extra,
        }
    )


def verdict(correct: int = 3, faithful: int = 2, abstained: bool = False):
    """A scripted Responses reply carrying a well-formed judgment."""
    return say(verdict_json(correct, faithful, abstained))


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
        base.update(cluster=f"example#{n // 2}", merges_since_base=n, template="changeset.blind")
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


class ChatReply:
    """A fake chat-completions client that replays contents, recording the requests."""

    def __init__(self, contents: list[str], *, reject_json_mode: bool = False) -> None:
        self.contents = list(contents)
        self.requests: list[dict[str, Any]] = []
        self.reject_json_mode = reject_json_mode
        self.chat = SimpleNamespace(completions=self)

    def factory(self, **kwargs: Any) -> ChatReply:
        self.client_kwargs = kwargs
        return self

    async def create(self, **kwargs: Any) -> Any:
        import httpx
        from openai import BadRequestError

        self.requests.append(kwargs)
        if self.reject_json_mode and "response_format" in kwargs:
            raise BadRequestError(
                "no json mode",
                response=httpx.Response(400, request=httpx.Request("POST", "http://x")),
                body=None,
            )
        content = self.contents.pop(0)
        return SimpleNamespace(
            model="reported-chat-model",
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(
                prompt_tokens=1000,
                completion_tokens=50,
                prompt_tokens_details=SimpleNamespace(cached_tokens=0),
            ),
        )


def usage(model: str = "gpt-6-luna") -> Usage:
    return Usage(provider="openai", model=model, kind="judge", input_tokens=100)
