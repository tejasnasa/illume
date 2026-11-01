"""Every generation call site forwards a reasoning-incapable provider's empty extras.

``LLMConfig.response_kwargs`` returns ``{}`` for a provider that does not accept
``reasoning.effort`` -- Groq is the registry's one such preset. The call sites used to
treat that empty dict as "no credential", replacing it with a hard-coded
``{"reasoning": {"effort": ...}}``, which 400s on exactly the provider the empty dict
was protecting. These tests pin each call site's actual request body instead of the
``LLMConfig`` helper, because the helper was already correct while the call sites were
not.

The recorder stands in for ``openai.OpenAI`` / ``AsyncOpenAI`` the same way
``tests.fixtures.openai_stub`` does: in process, no socket, and the request kwargs are
kept verbatim.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.services.llm_config import LLMConfig
from app.services.llm_providers import PROVIDERS

pytestmark = pytest.mark.unit


def _groq_config() -> LLMConfig:
    """The config a Groq BYOK user produces: no reasoning support, so empty extras."""
    groq = PROVIDERS["groq"]
    return LLMConfig(
        api_key="groq-key",
        model=groq.default_model,
        base_url=groq.base_url,
        supports_reasoning=groq.supports_reasoning,
        source="user",
    )


class _RecordingResponses:
    """Minimal ``client.responses`` that records each request's keyword arguments."""

    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.kwargs_list: list[dict[str, Any]] = []

    def create(self, *, model: Any = None, input: Any = None, **kwargs: Any) -> SimpleNamespace:
        self.kwargs_list.append(kwargs)
        return SimpleNamespace(output_text=self.output_text)


class _RecordingClient:
    def __init__(self, responses: Any) -> None:
        self.responses = responses


class _AsyncRecordingResponses(_RecordingResponses):
    """The async twin; ``rag`` awaits ``responses.create``."""

    async def create(
        self, *, model: Any = None, input: Any = None, **kwargs: Any
    ) -> SimpleNamespace:
        self.kwargs_list.append(kwargs)
        return SimpleNamespace(output_text=self.output_text)


def _factory(responses: Any):
    def _make(*args: Any, **kwargs: Any) -> _RecordingClient:
        return _RecordingClient(responses)

    return _make


class TestGlossaryBuilderOmitsReasoning:
    def test_groq_credential_sends_no_reasoning_field(self, monkeypatch):
        from app.services import glossary_builder

        responses = _RecordingResponses(
            '[{"name": "parse_config", "definition": "Reads the settings file."}]'
        )
        monkeypatch.setattr(glossary_builder, "OpenAI", _factory(responses))
        symbol = SimpleNamespace(
            id=uuid4(),
            name="parse_config",
            start_line=1,
            end_line=4,
            docstring=None,
            source_code="def parse_config(): ...",
        )
        file = SimpleNamespace(path="app/config.py")
        monkeypatch.setattr(glossary_builder, "_get_top_symbols", lambda *a, **k: [(symbol, file)])

        created = glossary_builder.build_glossary(
            MagicMock(), SimpleNamespace(id=uuid4()), llm=_groq_config()
        )

        assert created == 1
        assert responses.kwargs_list, "the glossary call site never reached the SDK"
        assert all("reasoning" not in kwargs for kwargs in responses.kwargs_list)


class TestOnboardingOmitsReasoning:
    def test_groq_credential_sends_no_reasoning_field(self, monkeypatch):
        from app.services import onboarding

        responses = _RecordingResponses(
            '[{"file_path": "app/config.py", "annotation": "Read this first."}]'
        )
        monkeypatch.setattr(onboarding.openai, "OpenAI", _factory(responses))

        annotations = onboarding._annotate_files(
            [{"path": "app/config.py", "fan_in": 3, "tier": 0}],
            {"app/config.py": "python"},
            llm=_groq_config(),
        )

        assert annotations == {"app/config.py": "Read this first."}
        assert responses.kwargs_list, "the reading-order call site never reached the SDK"
        assert all("reasoning" not in kwargs for kwargs in responses.kwargs_list)


class TestArchitectureBriefOmitsReasoning:
    def test_groq_credential_sends_no_reasoning_field(self, monkeypatch):
        from app.services import architecture_brief

        responses = _RecordingResponses("A small service.")
        monkeypatch.setattr(architecture_brief, "OpenAI", _factory(responses))

        architecture_brief._call_llm_narrative("summarise this repo", llm=_groq_config())

        assert responses.kwargs_list, "the architecture-brief call site never reached the SDK"
        assert all("reasoning" not in kwargs for kwargs in responses.kwargs_list)


class TestChatAnswerOmitsReasoning:
    async def test_groq_credential_sends_no_reasoning_field(self, monkeypatch):
        from app.services import rag

        responses = _AsyncRecordingResponses("The parser lives in app/parser.py.")
        monkeypatch.setattr(rag, "AsyncOpenAI", _factory(responses))

        async def _embed_query(client, query):
            return [0.0]

        async def _vector_search(db, repository_id, query_vector, top_k=10):
            return [SimpleNamespace(source_type="file", source_id=uuid4(), file_id=uuid4())]

        async def _resolve_sources(db, embeddings):
            return [rag.SourceReference(source_type="file", chunk_text="x", file_path="a.py")]

        monkeypatch.setattr(rag, "_embed_query", _embed_query)
        monkeypatch.setattr(rag, "_vector_search", _vector_search)
        monkeypatch.setattr(rag, "resolve_sources", _resolve_sources)

        result = await rag.answer_question(
            "where is the parser?", uuid4(), None, llm=_groq_config()
        )

        assert result.generated is True
        assert responses.kwargs_list, "the chat call site never reached the SDK"
        assert all("reasoning" not in kwargs for kwargs in responses.kwargs_list)


def test_empty_response_kwargs_stays_empty_at_the_sdk_boundary(monkeypatch):
    """The regression: ``response_kwargs() == {}`` is an answer, not a missing value.

    The four call sites each used to re-add a reasoning dict when the helper returned
    ``{}``. This asserts the empty dict reaches ``responses.create`` unchanged, so the
    original bug cannot reappear in any one site without a failure here.
    """
    from app.services import architecture_brief

    config = _groq_config()
    assert config.response_kwargs("low") == {}

    responses = _RecordingResponses("ok")
    monkeypatch.setattr(architecture_brief, "OpenAI", _factory(responses))

    architecture_brief._call_llm_narrative("prompt", llm=config)

    assert responses.kwargs_list == [{"max_output_tokens": 4000}]
