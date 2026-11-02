"""Query variants: condense, multi_query and hyde, and every way a model call can fail.

The model is faked in process the way ``test_generation_reasoning_kwargs`` fakes
it: a stand-in for ``AsyncOpenAI`` that records each request's keyword arguments
and replays scripted outputs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from app.services.llm_config import LLMConfig
from app.services.llm_providers import PROVIDERS
from app.services.retrieval.config import QueryConfig
from app.services.retrieval.query import build_variants
from tests.fixtures.retrieval import (
    FakeResponses,
    RecordingEmit,
    install_fake_openai,
    make_llm,
)

pytestmark = pytest.mark.unit


@dataclass
class Turn:
    role: str
    content: str


@pytest.fixture
def events() -> RecordingEmit:
    return RecordingEmit()


@pytest.fixture
def fake_openai(monkeypatch):
    """Installs a fake ``AsyncOpenAI`` and returns a function that scripts its outputs."""
    state: dict[str, Any] = {"inits": []}

    def script(*outputs: Any) -> FakeResponses:
        responses = install_fake_openai(monkeypatch, *outputs)
        state["inits"] = responses.client_inits
        return responses

    script.state = state  # type: ignore[attr-defined]
    return script


_llm = make_llm


def _groq() -> LLMConfig:
    groq = PROVIDERS["groq"]
    return LLMConfig(
        api_key="groq-key",
        model=groq.default_model,
        base_url=groq.base_url,
        supports_reasoning=groq.supports_reasoning,
        source="user",
    )


HISTORY = [
    Turn("user", "How does login work?"),
    Turn("assistant", "It checks the password in app/auth/security.py."),
    Turn("user", "What about its tests?"),
    Turn("assistant", "They live in tests/test_security.py."),
    Turn("user", "And the token expiry?"),
]


class TestIdentity:
    async def test_the_question_is_variant_zero_and_no_model_is_called(self, fake_openai, events):
        responses = fake_openai()
        standalone, variants = await build_variants(
            "where is login?", HISTORY, QueryConfig(), llm=_llm(), emit=events
        )
        assert standalone == "where is login?"
        assert [(v.text, v.kind, v.index) for v in variants] == [("where is login?", "original", 0)]
        assert responses.calls == []
        assert events.items == []


class TestCondense:
    async def test_skipped_without_history(self, fake_openai, events):
        responses = fake_openai()
        standalone, variants = await build_variants(
            "what about tests?", [], QueryConfig(condense=True), llm=_llm(), emit=events
        )
        assert standalone == "what about tests?"
        assert variants[0].kind == "original"
        assert responses.calls == []

    async def test_skipped_when_the_history_window_is_zero(self, fake_openai, events):
        responses = fake_openai()
        await build_variants(
            "q", HISTORY, QueryConfig(condense=True, history_messages=0), llm=_llm(), emit=events
        )
        assert responses.calls == []

    async def test_rewrites_the_follow_up_as_variant_zero(self, fake_openai, events):
        responses = fake_openai(json.dumps({"question": "What tests cover token expiry?"}))
        standalone, variants = await build_variants(
            "And the token expiry?", HISTORY, QueryConfig(condense=True), llm=_llm(), emit=events
        )
        assert standalone == "What tests cover token expiry?"
        assert [(v.text, v.kind, v.index) for v in variants] == [
            ("What tests cover token expiry?", "condensed", 0)
        ]
        assert len(responses.calls) == 1
        assert events.items == []

    async def test_only_the_last_history_messages_are_sent(self, fake_openai, events):
        responses = fake_openai(json.dumps({"question": "standalone"}))
        await build_variants(
            "And the token expiry?",
            HISTORY,
            QueryConfig(condense=True, history_messages=2),
            llm=_llm(),
            emit=events,
        )
        prompt = responses.calls[0]["input"][1]["content"]
        assert "They live in tests/test_security.py." in prompt
        assert "And the token expiry?" in prompt
        assert "What about its tests?" not in prompt
        assert "How does login work?" not in prompt

    async def test_the_default_window_is_five_messages(self, fake_openai, events):
        responses = fake_openai(json.dumps({"question": "standalone"}))
        longer = [Turn("user", "oldest message")] + HISTORY
        await build_variants("q", longer, QueryConfig(condense=True), llm=_llm(), emit=events)
        prompt = responses.calls[0]["input"][1]["content"]
        assert "oldest message" not in prompt
        assert "How does login work?" in prompt

    async def test_request_shape_is_structured_output_on_the_users_client(
        self, fake_openai, events
    ):
        responses = fake_openai(json.dumps({"question": "standalone"}))
        llm = _llm(base_url="https://example.test/v1")
        await build_variants("q", HISTORY, QueryConfig(condense=True), llm=llm, emit=events)
        call = responses.calls[0]
        assert call["model"] == "test-model"
        assert call["reasoning"] == {"effort": "minimal"}
        assert call["text"]["format"]["type"] == "json_schema"
        assert call["text"]["format"]["schema"]["required"] == ["question"]
        assert fake_openai.state["inits"] == [
            {"api_key": "sk-test", "base_url": "https://example.test/v1"}
        ]

    async def test_a_missing_base_url_is_omitted_not_passed_as_none(self, fake_openai, events):
        fake_openai(json.dumps({"question": "standalone"}))
        await build_variants("q", HISTORY, QueryConfig(condense=True), llm=_llm(), emit=events)
        assert fake_openai.state["inits"] == [{"api_key": "sk-test"}]

    async def test_composes_with_multi_query(self, fake_openai, events):
        responses = fake_openai(
            json.dumps({"question": "standalone q"}),
            json.dumps({"queries": ["a one", "b two", "c three"]}),
        )
        config = QueryConfig(condense=True, transform="multi_query")
        standalone, variants = await build_variants("q", HISTORY, config, llm=_llm(), emit=events)
        assert standalone == "standalone q"
        assert [(v.kind, v.index) for v in variants] == [
            ("condensed", 0),
            ("multi_query", 1),
            ("multi_query", 2),
            ("multi_query", 3),
        ]
        # The rewrites are made from the standalone question.
        assert responses.calls[1]["input"][1]["content"] == "standalone q"

    @pytest.mark.parametrize(
        "bad",
        [
            "not json at all",
            '{"question": ',
            '{"unrelated": 1}',
            '{"question": "  "}',
            "",
            "[1, 2]",
        ],
    )
    async def test_unusable_output_keeps_the_original_question(self, fake_openai, events, bad):
        fake_openai(bad)
        standalone, variants = await build_variants(
            "And the token expiry?", HISTORY, QueryConfig(condense=True), llm=_llm(), emit=events
        )
        assert standalone == "And the token expiry?"
        assert [(v.kind, v.index) for v in variants] == [("original", 0)]
        assert len(events.degraded) == 1
        assert events.degraded[0]["transform"] == "condense"
        assert events.degraded[0]["reason"]

    async def test_a_provider_error_keeps_the_original_question(self, fake_openai, events):
        fake_openai(RuntimeError("503 from provider"))
        standalone, variants = await build_variants(
            "follow up", HISTORY, QueryConfig(condense=True), llm=_llm(), emit=events
        )
        assert standalone == "follow up"
        assert [v.kind for v in variants] == ["original"]
        assert len(events.degraded) == 1
        assert "503 from provider" in events.degraded[0]["reason"]

    async def test_a_code_fenced_object_is_parsed_leniently(self, fake_openai, events):
        fake_openai('```json\n{"question": "fenced"}\n```')
        standalone, variants = await build_variants(
            "q", HISTORY, QueryConfig(condense=True), llm=_llm(), emit=events
        )
        assert (standalone, variants[0].kind) == ("fenced", "condensed")
        assert events.items == []

    async def test_an_object_wrapped_in_prose_is_parsed_leniently(self, fake_openai, events):
        fake_openai('Sure! Here you go: {"question": "wrapped"} Hope that helps.')
        standalone, _ = await build_variants(
            "q", HISTORY, QueryConfig(condense=True), llm=_llm(), emit=events
        )
        assert standalone == "wrapped"
        assert events.degraded == []


class TestMultiQuery:
    async def test_appends_the_rewrites_with_indices_from_one(self, fake_openai, events):
        responses = fake_openai(
            json.dumps({"queries": ["verify_password", "check a password", "rejects wrong hash"]})
        )
        config = QueryConfig(transform="multi_query", n_variants=3)
        standalone, variants = await build_variants(
            "how are passwords checked?", [], config, llm=_llm(), emit=events
        )
        assert standalone == "how are passwords checked?"
        assert [(v.text, v.kind, v.index) for v in variants] == [
            ("how are passwords checked?", "original", 0),
            ("verify_password", "multi_query", 1),
            ("check a password", "multi_query", 2),
            ("rejects wrong hash", "multi_query", 3),
        ]
        assert len(responses.calls) == 1
        assert "exactly 3" in responses.calls[0]["input"][0]["content"]
        assert events.items == []

    async def test_extra_rewrites_beyond_n_are_dropped(self, fake_openai, events):
        fake_openai(json.dumps({"queries": [f"query number {i}" for i in range(8)]}))
        config = QueryConfig(transform="multi_query", n_variants=4)
        _, variants = await build_variants("q", [], config, llm=_llm(), emit=events)
        assert [v.index for v in variants] == [0, 1, 2, 3, 4]

    async def test_repeats_of_the_question_or_each_other_are_dropped(self, fake_openai, events):
        fake_openai(json.dumps({"queries": ["The Question", "fresh one", "Fresh One", "other"]}))
        config = QueryConfig(transform="multi_query")
        _, variants = await build_variants("the question", [], config, llm=_llm(), emit=events)
        assert [(v.text, v.index) for v in variants] == [
            ("the question", 0),
            ("fresh one", 1),
            ("other", 2),
        ]

    async def test_a_bare_json_list_is_accepted(self, fake_openai, events):
        fake_openai(json.dumps(["alpha query", "beta query", "gamma query"]))
        _, variants = await build_variants(
            "q", [], QueryConfig(transform="multi_query"), llm=_llm(), emit=events
        )
        assert len(variants) == 4
        assert events.degraded == []

    @pytest.mark.parametrize("bad", ["garbage", '{"queries": "oops"}', '{"queries": []}', "{"])
    async def test_unusable_output_adds_nothing_and_degrades_once(self, fake_openai, events, bad):
        fake_openai(bad)
        standalone, variants = await build_variants(
            "q", [], QueryConfig(transform="multi_query"), llm=_llm(), emit=events
        )
        assert standalone == "q"
        assert [(v.kind, v.index) for v in variants] == [("original", 0)]
        assert len(events.degraded) == 1
        assert events.degraded[0]["transform"] == "multi_query"

    async def test_a_provider_error_adds_nothing_and_degrades_once(self, fake_openai, events):
        fake_openai(TimeoutError("slow"))
        _, variants = await build_variants(
            "q", [], QueryConfig(transform="multi_query"), llm=_llm(), emit=events
        )
        assert len(variants) == 1
        assert [d["transform"] for d in events.degraded] == ["multi_query"]


class TestHyde:
    async def test_appends_one_hyde_variant(self, fake_openai, events):
        fake_openai(json.dumps({"snippet": "def verify_password(plain, hashed): ..."}))
        _, variants = await build_variants(
            "how are passwords checked?", [], QueryConfig(transform="hyde"), llm=_llm(), emit=events
        )
        assert [(v.kind, v.index) for v in variants] == [("original", 0), ("hyde", 1)]
        assert variants[1].text == "def verify_password(plain, hashed): ..."

    async def test_malformed_output_adds_nothing_and_degrades_once(self, fake_openai, events):
        fake_openai("def not_json(): pass")
        _, variants = await build_variants(
            "q", [], QueryConfig(transform="hyde"), llm=_llm(), emit=events
        )
        assert [v.kind for v in variants] == ["original"]
        assert [d["transform"] for d in events.degraded] == ["hyde"]


class TestCredentials:
    async def test_no_credential_means_no_model_call(self, fake_openai, events, monkeypatch):
        responses = fake_openai()
        monkeypatch.setattr(LLMConfig, "server_default", classmethod(lambda cls: None))
        config = QueryConfig(condense=True, transform="multi_query")
        standalone, variants = await build_variants("q", HISTORY, config, llm=None, emit=events)
        assert (standalone, [v.kind for v in variants]) == ("q", ["original"])
        assert responses.calls == []
        assert fake_openai.state["inits"] == []
        assert sorted(d["transform"] for d in events.degraded) == ["condense", "multi_query"]

    async def test_no_credential_and_nothing_to_do_is_silent(
        self, fake_openai, events, monkeypatch
    ):
        fake_openai()
        monkeypatch.setattr(LLMConfig, "server_default", classmethod(lambda cls: None))
        await build_variants("q", [], QueryConfig(condense=True), llm=None, emit=events)
        assert events.items == []

    async def test_none_falls_back_to_the_server_default(self, fake_openai, events, monkeypatch):
        responses = fake_openai(json.dumps({"question": "from server key"}))
        server = _llm(api_key="server-key", source="server")
        monkeypatch.setattr(LLMConfig, "server_default", classmethod(lambda cls: server))
        standalone, _ = await build_variants(
            "q", HISTORY, QueryConfig(condense=True), llm=None, emit=events
        )
        assert standalone == "from server key"
        assert fake_openai.state["inits"] == [{"api_key": "server-key"}]
        assert len(responses.calls) == 1

    async def test_groq_style_configs_send_no_reasoning_key(self, fake_openai, events):
        responses = fake_openai(
            json.dumps({"question": "standalone"}),
            json.dumps({"queries": ["one q", "two q", "three q"]}),
        )
        config = QueryConfig(condense=True, transform="multi_query")
        await build_variants("q", HISTORY, config, llm=_groq(), emit=events)
        assert len(responses.calls) == 2
        assert all("reasoning" not in call for call in responses.calls)
        assert all(call["text"]["format"]["type"] == "json_schema" for call in responses.calls)


class TestProviderWithoutJsonSchema:
    """A provider that 400s on ``json_schema`` still gets its rewrite, via plain instructions."""

    @staticmethod
    def _rejection():
        import httpx
        from openai import BadRequestError

        request = httpx.Request("POST", "https://example.invalid/v1/responses")
        response = httpx.Response(400, request=request, json={"error": {"message": "no"}})
        return BadRequestError("json_schema is not supported", response=response, body=None)

    async def test_condense_retries_without_the_format_and_parses_the_reply(
        self, fake_openai, events
    ):
        responses = fake_openai(
            self._rejection(),
            'Sure: {"question": "When does the login token expire?"}',
        )

        standalone, variants = await build_variants(
            "And the token expiry?",
            HISTORY,
            QueryConfig(condense=True),
            llm=_llm(),
            emit=events,
        )

        assert standalone == "When does the login token expire?"
        assert variants[0].kind == "condensed"
        assert len(responses.calls) == 2
        assert "text" in responses.calls[0]
        assert "text" not in responses.calls[1]
        system = responses.calls[1]["input"][0]["content"]
        assert "JSON schema" in system
        assert events.degraded == []

    async def test_a_second_failure_still_degrades_once(self, fake_openai, events):
        fake_openai(self._rejection(), "not json at all")

        standalone, variants = await build_variants(
            "And the token expiry?",
            HISTORY,
            QueryConfig(condense=True),
            llm=_llm(),
            emit=events,
        )

        assert standalone == "And the token expiry?"
        assert variants[0].kind == "original"
        assert len(events.degraded) == 1
