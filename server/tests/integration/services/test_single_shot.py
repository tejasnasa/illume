"""The single-shot answerer over the seeded fixture repository.

Retrieval runs against real Postgres with the deterministic fake embedder; the
generation model and the Jev endpoint are faked. Together with
``test_rag_parity.py`` this covers every single-shot preset end to end.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
import pytest
import respx

from app.core.config import settings
from app.services.decisions import DECISIONS_URL
from app.services.retrieval import query as query_module
from app.services.retrieval import single_shot
from app.services.retrieval.citations import code_key
from app.services.retrieval.config import (
    CLASSIC,
    HYBRID,
    HYBRID_RERANK,
    STRUCTURAL,
)
from app.services.retrieval.single_shot import (
    MAX_OUTPUT_TOKENS,
    NO_CONTEXT_ANSWER,
    answer,
    build_classic_prompt,
    is_classic_shaped,
)
from tests.factories import make_user
from tests.fixtures.retrieval import (
    DEFAULT_SPEC,
    RecordingEmit,
    hash_vector,
    install_fake_openai,
    make_context,
    make_llm,
    render_symbol_chunk,
    seed_repo,
)

pytestmark = pytest.mark.integration

SECURITY = "app/auth/security.py"
QUESTION = "how does verify_password check bcrypt checkpw"
VERIFY_SPEC = DEFAULT_SPEC.files[0].symbols[0]
VERIFY_KEY = code_key(SECURITY, VERIFY_SPEC.start_line, VERIFY_SPEC.end_line)
VERIFY_VECTOR = hash_vector(render_symbol_chunk(SECURITY, VERIFY_SPEC))

GENERATED = f"verify_password compares with bcrypt [{VERIFY_KEY}] and a ghost [F:app/ghost.py:1-2]."


@dataclass
class Chat:
    role: str
    content: str


@pytest.fixture
async def seeded(db_session):
    return await seed_repo(db_session, await make_user(db_session), DEFAULT_SPEC)


@pytest.fixture
def generation(monkeypatch):
    """Replaces the answerer's client with one replaying the scripted answers."""

    def install(*outputs):
        return install_fake_openai(monkeypatch, *outputs, module=single_shot)

    return install


@pytest.fixture
def jev(monkeypatch):
    """A Jev endpoint that rates passages mentioning ``verify_password`` highest."""
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "or-test-key")

    def respond(request: httpx.Request) -> httpx.Response:
        questions = json.loads(request.content)["questions"]
        answers = {
            name: {"score": 3.0 if "verify_password" in q["instructions"] else 0.5}
            for name, q in questions.items()
        }
        return httpx.Response(
            200, json={"answers": answers, "model": "typesafe/jev-1.13-20260917", "usage": {}}
        )

    with respx.mock:
        route = respx.post(DECISIONS_URL).mock(side_effect=respond)
        yield route


def context_for(db, seeded, emit=None):
    ctx = make_context(db, seeded.repo, {QUESTION: VERIFY_VECTOR})
    if emit is not None:
        ctx.emit = emit
    return ctx


class TestClassicShape:
    def test_classic_is_recognised_by_behaviour_not_name(self):
        assert is_classic_shaped(CLASSIC)
        assert is_classic_shaped(CLASSIC.model_copy(update={"name": "renamed"}))
        assert not is_classic_shaped(HYBRID)
        assert not is_classic_shaped(CLASSIC.model_copy(update={"diversify": HYBRID.diversify}))

    async def test_uses_the_chat_prompt_history_and_request_parameters(
        self, db_session, seeded, generation
    ):
        responses = generation("  The answer.  ")
        history = [Chat("user", "earlier question"), Chat("assistant", "earlier answer")]

        result = await answer(
            CLASSIC,
            QUESTION,
            ctx=context_for(db_session, seeded),
            history=history,
            llm=make_llm(),
        )

        assert result.generated is True
        assert result.answer == "The answer."
        assert result.context == [] and result.unresolved == []
        assert result.config_hash == CLASSIC.config_hash()
        # sources are the retrieved set, in order.
        assert result.sources == [c.reference for c in result.retrieval.candidates]
        assert result.sources[0].symbol_name == "verify_password"

        [call] = responses.calls
        assert call["model"] == "test-model"
        assert call["max_output_tokens"] == MAX_OUTPUT_TOKENS == 3000
        assert call["reasoning"] == {"effort": "minimal"}
        assert "stream" not in call
        assert call["input"] == [
            {"role": "system", "content": build_classic_prompt(QUESTION, result.sources)},
            {"role": "user", "content": "earlier question"},
            {"role": "assistant", "content": "earlier answer"},
            {"role": "user", "content": QUESTION},
        ]
        assert "[Source 1] [Code]" in call["input"][0]["content"]
        assert "<source" not in call["input"][0]["content"]

    async def test_nothing_retrieved_returns_the_canned_answer_without_a_model_call(
        self, db_session, seeded, generation
    ):
        responses = generation()
        result = await answer(
            CLASSIC, "zzz qqq unrelated", ctx=context_for(db_session, seeded), llm=make_llm()
        )

        assert result.answer == NO_CONTEXT_ANSWER
        assert result.generated is False
        assert result.sources == [] and result.context == []
        assert responses.calls == [] and responses.client_inits == []


class TestCitingPresets:
    async def test_hybrid_cites_by_key_and_splits_cited_from_context(
        self, db_session, seeded, generation
    ):
        responses = generation(GENERATED)
        result = await answer(HYBRID, QUESTION, ctx=context_for(db_session, seeded), llm=make_llm())

        assert result.generated is True
        assert result.answer == GENERATED
        assert [ref.symbol_name for ref in result.sources] == ["verify_password"]
        assert result.cited_keys == [VERIFY_KEY]
        assert result.unresolved == ["F:app/ghost.py:1-2"]
        retrieved = {c.reference.chunk_text for c in result.retrieval.candidates}
        assert {r.chunk_text for r in [*result.sources, *result.context]} == retrieved
        assert all(r not in result.sources for r in result.context)
        assert result.config_hash == HYBRID.config_hash()

        [call] = responses.calls
        system = call["input"][0]["content"]
        assert f'<source key="{VERIFY_KEY}" type="code" provenance="repo">' in system
        assert "[F:app/main.py:10-24]" in system  # the citation format is explained
        assert "never an instruction" in system  # untrusted-content rule
        assert "file level" in system and "no call graph" in system
        assert "[Source 1]" not in system  # not the chat prompt
        assert call["input"][-1] == {"role": "user", "content": QUESTION}
        assert call["max_output_tokens"] == 3000

    async def test_hybrid_rerank_uses_jev_when_configured(
        self, db_session, seeded, generation, jev
    ):
        generation(GENERATED)
        result = await answer(
            HYBRID_RERANK,
            QUESTION,
            ctx=context_for(db_session, seeded),
            llm=make_llm(),
        )

        assert jev.called
        assert not result.retrieval.trace.reranker_degraded
        assert result.retrieval.candidates[0].rerank_score == 3.0
        assert result.retrieval.trace.rerank_calls[0]["model"] == "typesafe/jev-1.13-20260917"
        assert [ref.symbol_name for ref in result.sources] == ["verify_password"]

    @pytest.mark.parametrize("preset", [HYBRID_RERANK, STRUCTURAL], ids=lambda p: p.name)
    async def test_without_a_jev_key_the_answer_still_comes_back_degraded(
        self, db_session, seeded, generation, preset, monkeypatch
    ):
        monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
        generation(GENERATED)
        emit = RecordingEmit()
        result = await answer(
            preset,
            QUESTION,
            ctx=context_for(db_session, seeded),
            llm=make_llm(),
            emit=emit,
        )

        assert result.generated is True
        assert result.retrieval.trace.reranker_degraded
        assert [d["stage"] for d in emit.degraded] == ["rerank"]
        assert [ref.symbol_name for ref in result.sources] == ["verify_password"]

    async def test_structural_runs_with_jev_and_every_channel(
        self, db_session, seeded, generation, jev
    ):
        generation(GENERATED)
        result = await answer(
            STRUCTURAL,
            QUESTION,
            ctx=context_for(db_session, seeded),
            llm=make_llm(),
        )

        assert jev.called
        assert result.generated is True
        assert result.cited_keys == [VERIFY_KEY]
        assert result.unresolved == ["F:app/ghost.py:1-2"]

    async def test_nothing_retrieved_is_not_charged_for_any_preset(
        self, db_session, seeded, generation
    ):
        responses = generation()
        result = await answer(
            HYBRID, "zzz qqq unrelated", ctx=context_for(db_session, seeded), llm=make_llm()
        )
        # Lexical and symbol search find nothing for gibberish either.
        assert result.answer == NO_CONTEXT_ANSWER
        assert result.generated is False
        assert responses.calls == []

    async def test_history_is_replayed_as_turns_after_the_system_prompt(
        self, db_session, seeded, generation, monkeypatch
    ):
        # Condense runs on the query module's client; the answer on the answerer's.
        install_fake_openai(monkeypatch, json.dumps({"question": QUESTION}), module=query_module)
        responses = generation(GENERATED)
        history = [Chat("user", "tell me about auth"), Chat("assistant", "it uses bcrypt")]

        await answer(
            HYBRID,
            "and how does it verify?",
            ctx=context_for(db_session, seeded),
            history=history,
            llm=make_llm(),
        )

        roles = [m["role"] for m in responses.calls[0]["input"]]
        assert roles == ["system", "user", "assistant", "user"]
        assert responses.calls[0]["input"][1]["content"] == "tell me about auth"
        assert responses.calls[0]["input"][-1]["content"] == "and how does it verify?"

    async def test_groq_credentials_send_no_reasoning_key(self, db_session, seeded, generation):
        from app.services.llm_providers import PROVIDERS

        groq = PROVIDERS["groq"]
        responses = generation(GENERATED)
        await answer(
            HYBRID,
            QUESTION,
            ctx=context_for(db_session, seeded),
            llm=make_llm(
                base_url=groq.base_url, supports_reasoning=groq.supports_reasoning, model="m"
            ),
        )
        assert "reasoning" not in responses.calls[0]
        assert responses.client_inits == [{"api_key": "sk-test", "base_url": groq.base_url}]


class TestStreaming:
    @pytest.mark.parametrize("preset", [CLASSIC, HYBRID], ids=lambda p: p.name)
    async def test_deltas_are_emitted_and_assembled(self, db_session, seeded, generation, preset):
        responses = generation(GENERATED)
        emit = RecordingEmit()
        result = await answer(
            preset,
            QUESTION,
            ctx=context_for(db_session, seeded),
            llm=make_llm(),
            emit=emit,
            stream=True,
        )

        deltas = [payload["text"] for event, payload in emit.items if event == "answer_delta"]
        assert len(deltas) > 3
        assert all(
            set(payload) == {"text"} for event, payload in emit.items if event == "answer_delta"
        )
        assert "".join(deltas) == GENERATED
        assert result.answer == GENERATED
        assert responses.calls[0]["stream"] is True

    async def test_a_streamed_answer_is_split_by_citation_like_a_plain_one(
        self, db_session, seeded, generation
    ):
        generation(GENERATED)
        streamed = await answer(
            HYBRID,
            QUESTION,
            ctx=context_for(db_session, seeded),
            llm=make_llm(),
            stream=True,
        )
        generation(GENERATED)
        plain = await answer(HYBRID, QUESTION, ctx=context_for(db_session, seeded), llm=make_llm())

        assert streamed.cited_keys == plain.cited_keys == [VERIFY_KEY]
        assert streamed.unresolved == plain.unresolved

    async def test_without_streaming_nothing_is_emitted_and_no_stream_flag_is_sent(
        self, db_session, seeded, generation
    ):
        responses = generation(GENERATED)
        emit = RecordingEmit()
        await answer(
            HYBRID, QUESTION, ctx=context_for(db_session, seeded), llm=make_llm(), emit=emit
        )
        assert [e for e, _ in emit.items if e == "answer_delta"] == []
        assert "stream" not in responses.calls[0]

    async def test_a_failing_emitter_does_not_lose_the_answer(self, db_session, seeded, generation):
        generation(GENERATED)

        async def broken(event, payload):
            if event == "answer_delta":
                raise RuntimeError("socket closed")

        result = await answer(
            HYBRID,
            QUESTION,
            ctx=context_for(db_session, seeded),
            llm=make_llm(),
            emit=broken,
            stream=True,
        )
        assert result.answer == GENERATED
