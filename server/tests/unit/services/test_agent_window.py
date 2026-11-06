"""Fitting the conversation into the context window: estimates, stubs, refusals."""

from __future__ import annotations

import httpx
import pytest
from openai import APIStatusError, BadRequestError, RateLimitError

from app.services.agent.errors import ProviderStreamError
from app.services.agent.state import ReplaceItems, merge_items
from app.services.agent.window import (
    CHARS_PER_TOKEN,
    MIN_COMPACTED_CHARS,
    compact,
    conversation_chars,
    estimate_tokens,
    is_context_overflow,
)

pytestmark = pytest.mark.unit

LONG = "x" * MIN_COMPACTED_CHARS


def block(key: str) -> str:
    return f'<source key="{key}" type="code" provenance="repo">\n{LONG}\n</source>'


def call(call_id: str, name: str = "search_symbols", arguments: str = '{"name": "f"}'):
    return {"type": "function_call", "call_id": call_id, "name": name, "arguments": arguments}


def output(call_id: str, text: str):
    return {"type": "function_call_output", "call_id": call_id, "output": text}


def conversation() -> list[dict]:
    """System, question, then three tool-calling turns of one or two calls."""
    return [
        {"role": "system", "content": "You explore a repository."},
        {"role": "user", "content": "How is the password checked?"},
        call("a"),
        call("b", "read_symbol", '{"symbol_id": 4}'),
        output("a", block("F:app/a.py:1-9") + block("F:app/b.py:3-4")),
        output("b", block("F:app/c.py:1-2")),
        {"role": "user", "content": "Keep going."},
        call("c"),
        output("c", block("F:app/d.py:1-9")),
        call("d"),
        output("d", block("F:app/e.py:1-9")),
    ]


class TestEstimate:
    def test_without_a_call_yet_it_uses_the_fixed_ratio(self):
        assert estimate_tokens(7_000, last_tokens=0, last_chars=0) == round(7_000 / CHARS_PER_TOKEN)

    def test_the_last_call_calibrates_it(self):
        assert estimate_tokens(20_000, last_tokens=5_000, last_chars=10_000) == 10_000

    def test_size_is_measured_as_serialised(self):
        items = [{"role": "user", "content": "hi"}]
        assert conversation_chars(items) == len('{"role": "user", "content": "hi"}')


class TestCompact:
    def test_older_outputs_become_stubs_and_recent_turns_stay_whole(self):
        items = conversation()

        compacted, replaced = compact(items, keep_recent_turns=1)

        assert replaced == 3
        by_id = {i["call_id"]: i["output"] for i in compacted if "output" in i}
        assert by_id["d"] == items[-1]["output"]
        for call_id in ("a", "b", "c"):
            assert by_id[call_id].startswith("[Compacted")
        assert "F:app/a.py:1-9" in by_id["a"] and "F:app/b.py:3-4" in by_id["a"]
        assert "read_symbol" in by_id["b"] and '"symbol_id": 4' in by_id["b"]

    def test_every_call_keeps_exactly_one_output(self):
        compacted, _ = compact(conversation(), keep_recent_turns=0)

        calls = [i["call_id"] for i in compacted if i.get("type") == "function_call"]
        outputs = [i["call_id"] for i in compacted if i.get("type") == "function_call_output"]
        assert sorted(calls) == sorted(outputs) and len(outputs) == 4

    def test_messages_and_order_are_untouched(self):
        items = conversation()

        compacted, _ = compact(items, keep_recent_turns=0)

        assert len(compacted) == len(items)
        for before, after in zip(items, compacted, strict=True):
            if before.get("type") != "function_call_output":
                assert after == before

    def test_the_input_is_not_mutated(self):
        items = conversation()
        snapshot = [dict(item) for item in items]

        compact(items, keep_recent_turns=0)

        assert items == snapshot

    def test_keeping_every_turn_replaces_nothing(self):
        items = conversation()
        compacted, replaced = compact(items, keep_recent_turns=3)
        assert replaced == 0 and compacted == items

    def test_short_outputs_and_existing_stubs_are_left_alone(self):
        items = [
            call("a"),
            output("a", "no matches"),
            call("b"),
            output("b", block("F:x.py:1-2")),
            call("c"),
            output("c", block("F:y.py:1-2")),
        ]
        once, replaced = compact(items, keep_recent_turns=1)
        twice, again = compact(once, keep_recent_turns=0)

        assert replaced == 1
        assert once[1]["output"] == "no matches"
        assert again == 1  # only the newest result, which was kept the first time
        assert twice[3] == once[3]

    def test_a_long_key_list_is_cut_short(self):
        text = "".join(block(f"F:f{n}.py:1-2") for n in range(30))
        items = [call("a"), output("a", text), call("b"), output("b", LONG)]

        compacted, _ = compact(items, keep_recent_turns=1)

        assert "and 10 more" in compacted[1]["output"]


class TestReducer:
    def test_a_list_appends(self):
        assert merge_items([{"a": 1}], [{"b": 2}]) == [{"a": 1}, {"b": 2}]

    def test_a_replacement_replaces(self):
        assert merge_items([{"a": 1}], ReplaceItems([{"c": 3}])) == [{"c": 3}]


def _status(cls, status: int, message: str, body=None):
    request = httpx.Request("POST", "https://provider.test/v1/responses")
    return cls(message, response=httpx.Response(status, request=request), body=body)


class TestOverflow:
    @pytest.mark.parametrize(
        "message",
        [
            "This model's maximum context length is 128000 tokens.",
            "prompt is too long: 210000 tokens > 200000 maximum",
            "Input is too long for requested model.",
            "context_length_exceeded",
            "Request exceeds the model's maximum context window",
        ],
    )
    def test_a_400_saying_the_input_is_too_long_is_an_overflow(self, message):
        assert is_context_overflow(_status(BadRequestError, 400, message))

    def test_the_error_code_alone_is_enough(self):
        error = _status(BadRequestError, 400, "Bad request", {"code": "context_length_exceeded"})
        assert is_context_overflow(error)

    def test_a_413_is_an_overflow(self):
        assert is_context_overflow(_status(APIStatusError, 413, "Payload too large"))

    def test_a_stream_failure_saying_so_is_an_overflow(self):
        assert is_context_overflow(ProviderStreamError("maximum context length exceeded"))

    @pytest.mark.parametrize(
        "error",
        [
            _status(BadRequestError, 400, "Unsupported parameter: tool_choice"),
            _status(RateLimitError, 429, "Too many requests, maximum context of patience"),
            ProviderStreamError("the response failed"),
            ValueError("maximum context length"),
        ],
        ids=["other-400", "429", "other-stream", "not-a-provider-error"],
    )
    def test_anything_else_is_not(self, error):
        assert not is_context_overflow(error)
