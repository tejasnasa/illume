"""The retrieval pipeline end to end over a seeded repository.

Dense search uses the deterministic fake embedder with the question mapped onto a
seeded chunk's vector, so the whole pipeline runs against real Postgres with no
network. The model is faked where a query rewrite is under test.
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace

import pytest
from sqlalchemy import text

from app.services.retrieval import channels as channel_registry
from app.services.retrieval import pipeline as pipeline_module
from app.services.retrieval.citations import code_key
from app.services.retrieval.config import (
    CLASSIC,
    HYBRID,
    HYBRID_RERANK,
    STRUCTURAL,
    CochangeChannel,
    DenseChannel,
    GraphChannel,
    HistoryChannel,
    LexicalChannel,
    PipelineConfig,
    QueryConfig,
    RerankConfig,
    SymbolChannel,
)
from app.services.retrieval.diversify import diversify
from app.services.retrieval.pipeline import retrieve
from tests.factories import make_user
from tests.fixtures.retrieval import (
    DEFAULT_SPEC,
    CochangeSpec,
    ImportSpec,
    RecordingEmit,
    RepoSpec,
    hash_vector,
    install_fake_openai,
    make_context,
    make_llm,
    render_symbol_chunk,
    seed_repo,
)

pytestmark = pytest.mark.integration

SECURITY = "app/auth/security.py"
SERVICE = "app/users/service.py"
ROUTES = "app/users/routes.py"
INVOICE = "app/billing/invoice.py"

QUESTION = "how does verify_password check bcrypt checkpw"
VERIFY_SPEC = DEFAULT_SPEC.files[0].symbols[0]
VERIFY_KEY = code_key(SECURITY, VERIFY_SPEC.start_line, VERIFY_SPEC.end_line)
VERIFY_VECTOR = hash_vector(render_symbol_chunk(SECURITY, VERIFY_SPEC))

# routes -> service -> security <- invoice, and files that change together.
STRUCTURE_SPEC: RepoSpec = replace(
    DEFAULT_SPEC,
    imports=(
        ImportSpec(ROUTES, SERVICE, weight=1),
        ImportSpec(SERVICE, SECURITY, weight=3),
        ImportSpec(INVOICE, SECURITY, weight=1),
    ),
    cochange=(CochangeSpec(SECURITY, ROUTES, together=4, a_count=5, b_count=5),),
)


def _context(db, seeded, emit=None):
    ctx = make_context(db, seeded.repo, {QUESTION: VERIFY_VECTOR})
    if emit is not None:
        ctx.emit = emit
    return ctx


def _hit_channels(candidate) -> set[str]:
    return {hit.channel for hit in candidate.channel_hits}


async def _seeded(db, spec=STRUCTURE_SPEC, name="retrieval-fixture"):
    return await seed_repo(db, await make_user(db), spec, name=name)


class TestPresets:
    async def test_classic_is_one_dense_list_in_distance_order(self, db_session):
        seeded = await _seeded(db_session)
        result = await retrieve(CLASSIC, QUESTION, ctx=_context(db_session, seeded))

        assert result.candidates[0].key == VERIFY_KEY
        assert all(c.fused_score is None for c in result.candidates)
        assert len(result.candidates) <= CLASSIC.diversify.total
        assert [(t.channel, t.variant) for t in result.trace.channels] == [("dense", 0)]
        assert result.trace.reranker == "none"
        assert not result.trace.reranker_degraded
        assert result.trace.degraded == ()

    async def test_hybrid_fuses_dense_lexical_and_symbol(self, db_session):
        seeded = await _seeded(db_session)
        result = await retrieve(HYBRID, QUESTION, ctx=_context(db_session, seeded))

        top = result.candidates[0]
        assert top.key == VERIFY_KEY
        assert {"dense", "lexical", "symbol"} <= _hit_channels(top)
        assert top.fused_score is not None
        scores = [c.fused_score for c in result.pool]
        assert scores == sorted(scores, reverse=True)
        assert {t.channel for t in result.trace.channels} == {"dense", "lexical", "symbol"}

    @pytest.mark.parametrize("preset", [HYBRID_RERANK, STRUCTURAL], ids=lambda p: p.name)
    async def test_presets_with_the_jev_reranker_degrade_to_the_fused_order(
        self, db_session, preset
    ):
        seeded = await _seeded(db_session)
        emit = RecordingEmit()
        result = await retrieve(preset, QUESTION, ctx=_context(db_session, seeded, emit))

        assert result.candidates
        assert result.candidates[0].key == VERIFY_KEY
        assert result.trace.reranker == "jev"
        assert result.trace.reranker_degraded
        assert [d["stage"] for d in emit.degraded] == ["rerank"]
        assert emit.degraded[0]["reranker"] == "jev"
        assert "not available" in emit.degraded[0]["reason"]
        # The fused order cut to top_n, then diversified as usual.
        expected = diversify(list(result.pool[: preset.rerank.top_n]), preset.diversify)
        assert [c.key for c in result.candidates] == [c.key for c in expected]

    async def test_structural_runs_every_configured_channel(self, db_session):
        seeded = await _seeded(db_session)
        result = await retrieve(STRUCTURAL, QUESTION, ctx=_context(db_session, seeded))

        ran = {(t.channel, t.stage) for t in result.trace.channels}
        assert ran == {
            ("dense", "search"),
            ("lexical", "search"),
            ("symbol", "search"),
            ("grep", "search"),
            ("history", "search"),
            ("graph", "expansion"),
            ("cochange", "expansion"),
        }
        assert all(t.error is None for t in result.trace.channels)


class TestExpansion:
    BASE = (DenseChannel(), LexicalChannel(), SymbolChannel())

    def _config(self, *extra) -> PipelineConfig:
        return PipelineConfig(name="custom", channels=(*self.BASE, *extra))

    async def test_graph_and_cochange_add_candidates_the_first_pass_missed(self, db_session):
        seeded = await _seeded(db_session)
        baseline = await retrieve(self._config(), QUESTION, ctx=_context(db_session, seeded))
        expanded = await retrieve(
            self._config(GraphChannel(), CochangeChannel()),
            QUESTION,
            ctx=_context(db_session, seeded),
        )

        baseline_keys = {c.key for c in baseline.pool}
        added = [c for c in expanded.pool if c.key not in baseline_keys]
        assert added, "expansion found nothing new"
        assert {hit.channel for c in added for hit in c.channel_hits} <= {"graph", "cochange"}
        added_paths = {c.file_path for c in added}
        assert SERVICE in added_paths  # one import from security
        assert ROUTES in added_paths  # changes with security

    async def test_expansion_hits_are_merged_into_the_base_candidates_they_share_a_key_with(
        self, db_session
    ):
        seeded = await _seeded(db_session)
        expanded = await retrieve(
            self._config(GraphChannel(), CochangeChannel()),
            QUESTION,
            ctx=_context(db_session, seeded),
        )
        keys = [c.key for c in expanded.pool]
        assert len(keys) == len(set(keys))
        scores = [c.fused_score for c in expanded.pool]
        assert scores == sorted(scores, reverse=True)

    async def test_without_expansion_channels_nothing_expands(self, db_session):
        seeded = await _seeded(db_session)
        result = await retrieve(self._config(), QUESTION, ctx=_context(db_session, seeded))
        assert all(t.stage == "search" for t in result.trace.channels)
        assert not {"graph", "cochange"} & {h.channel for c in result.pool for h in c.channel_hits}


class TestFailureIsolation:
    @staticmethod
    def _break_lexical(monkeypatch):
        class Exploding:
            kind = "lexical"

            async def search(self, ctx, variant, spec):
                # A real database error: it aborts the transaction unless it is
                # confined to a savepoint.
                await ctx.db.execute(text("SELECT * FROM table_that_does_not_exist"))
                return []

        monkeypatch.setitem(channel_registry._CHANNELS, "lexical", Exploding())

    async def test_a_channel_with_a_sql_error_does_not_break_later_channels(
        self, db_session, monkeypatch
    ):
        seeded = await _seeded(db_session)
        self._break_lexical(monkeypatch)
        emit = RecordingEmit()
        # symbol sorts after lexical, so it runs on the session the failure just touched.
        result = await retrieve(HYBRID, QUESTION, ctx=_context(db_session, seeded, emit))

        by_channel = {t.channel: t for t in result.trace.channels}
        assert by_channel["lexical"].error is not None
        assert "table_that_does_not_exist" in by_channel["lexical"].error
        assert by_channel["lexical"].candidates == 0
        assert by_channel["dense"].error is None and by_channel["dense"].candidates > 0
        assert by_channel["symbol"].error is None and by_channel["symbol"].candidates > 0

        assert result.candidates[0].key == VERIFY_KEY
        assert _hit_channels(result.candidates[0]) == {"dense", "symbol"}
        assert [d["channel"] for d in emit.degraded] == ["lexical"]
        assert emit.degraded[0]["stage"] == "search"
        assert result.trace.degraded[0]["channel"] == "lexical"

        # The session is still usable for the caller.
        assert (await db_session.execute(text("SELECT 1"))).scalar_one() == 1

    async def test_a_python_error_is_isolated_the_same_way(self, db_session, monkeypatch):
        seeded = await _seeded(db_session)

        class Broken:
            kind = "symbol"

            async def search(self, ctx, variant, spec):
                raise RuntimeError("index missing")

        monkeypatch.setitem(channel_registry._CHANNELS, "symbol", Broken())
        result = await retrieve(HYBRID, QUESTION, ctx=_context(db_session, seeded))
        errors = {t.channel: t.error for t in result.trace.channels if t.error}
        assert errors == {"symbol": "RuntimeError: index missing"}
        assert result.candidates

    async def test_every_search_failing_raises_the_channels_own_error(
        self, db_session, monkeypatch
    ):
        """With nothing to fall back to, an empty result would hide an outage as "no match"."""
        seeded = await _seeded(db_session)

        class Outage(Exception):
            pass

        class Broken:
            kind = "dense"

            async def search(self, ctx, variant, spec):
                raise Outage("embedding service unreachable")

        monkeypatch.setitem(channel_registry._CHANNELS, "dense", Broken())
        with pytest.raises(Outage, match="embedding service unreachable"):
            await retrieve(CLASSIC, QUESTION, ctx=_context(db_session, seeded))

    async def test_a_channel_returning_nothing_is_not_a_failure(self, db_session, monkeypatch):
        seeded = await _seeded(db_session)

        class Empty:
            kind = "dense"

            async def search(self, ctx, variant, spec):
                await ctx.db.execute(text("SELECT 1"))
                return []

        monkeypatch.setitem(channel_registry._CHANNELS, "dense", Empty())
        result = await retrieve(CLASSIC, QUESTION, ctx=_context(db_session, seeded))
        assert result.candidates == ()
        assert result.trace.channels[0].error is None

    async def test_a_failing_expansion_channel_leaves_the_first_pass_intact(
        self, db_session, monkeypatch
    ):
        seeded = await _seeded(db_session)

        class Broken:
            kind = "graph"

            async def expand(self, ctx, seeds, spec):
                await ctx.db.execute(text("SELECT * FROM missing_edges"))
                return []

        monkeypatch.setitem(channel_registry._EXPANSIONS, "graph", Broken())
        config = PipelineConfig(
            name="custom", channels=(DenseChannel(), SymbolChannel(), GraphChannel())
        )
        result = await retrieve(config, QUESTION, ctx=_context(db_session, seeded))
        graph = next(t for t in result.trace.channels if t.channel == "graph")
        assert graph.stage == "expansion" and graph.error
        assert result.candidates[0].key == VERIFY_KEY

    async def test_a_failing_reranker_falls_back_to_the_fused_order(self, db_session, monkeypatch):
        seeded = await _seeded(db_session)

        class Exploding:
            kind = "llm"

            async def rerank(self, question, candidates, top_n):
                raise RuntimeError("provider down")

        monkeypatch.setattr(pipeline_module, "get_reranker", lambda kind, **_: Exploding())
        config = HYBRID.model_copy(
            update={"rerank": RerankConfig(kind="llm", candidate_pool=10, top_n=2)}
        )
        emit = RecordingEmit()
        result = await retrieve(config, QUESTION, ctx=_context(db_session, seeded, emit))

        assert result.trace.reranker_degraded
        assert [c.key for c in result.candidates] == [c.key for c in result.pool[:2]]
        assert emit.degraded[0]["reason"] == "RuntimeError: provider down"


class TestIsolationAcrossRepositories:
    async def test_nothing_from_the_other_repository_appears(self, db_session):
        user = await make_user(db_session)
        first = await seed_repo(db_session, user, STRUCTURE_SPEC, name="first")
        second = await seed_repo(db_session, user, STRUCTURE_SPEC, name="second")

        result = await retrieve(STRUCTURAL, QUESTION, ctx=_context(db_session, first))

        assert result.pool
        allowed = first.source_ids() | first.file_ids()
        forbidden = second.source_ids() | second.file_ids()
        for candidate in (*result.pool, *result.candidates):
            assert candidate.source_id is None or candidate.source_id in allowed
            assert candidate.source_id not in forbidden
            assert candidate.file_id not in forbidden
        # Same paths in both repositories, so only ids tell the copies apart.
        assert any(c.file_id in first.file_ids() for c in result.pool)


class TestTrace:
    async def test_there_is_one_entry_per_channel_and_variant(self, db_session, monkeypatch):
        seeded = await _seeded(db_session)
        install_fake_openai(
            monkeypatch, json.dumps({"queries": ["verify_password", "password check", "bcrypt"]})
        )
        config = HYBRID.model_copy(
            update={"query": QueryConfig(transform="multi_query", n_variants=3)}
        )
        result = await retrieve(config, QUESTION, ctx=_context(db_session, seeded), llm=make_llm())

        assert [v.index for v in result.variants] == [0, 1, 2, 3]
        seen = [(t.channel, t.variant) for t in result.trace.channels]
        assert sorted(seen) == sorted(
            (channel, variant) for channel in ("dense", "lexical", "symbol") for variant in range(4)
        )
        assert len(set(seen)) == len(seen)
        assert all(t.ms >= 0 and t.stage == "search" for t in result.trace.channels)
        assert sum(t.candidates for t in result.trace.channels) > 0
        assert result.trace.config_hash == config.config_hash()

    async def test_hyde_is_searched_by_the_dense_channel_only(self, db_session, monkeypatch):
        seeded = await _seeded(db_session)
        install_fake_openai(monkeypatch, json.dumps({"snippet": "def verify_password(): ..."}))
        config = PipelineConfig(
            name="custom",
            query=QueryConfig(transform="hyde"),
            channels=(DenseChannel(), LexicalChannel(), SymbolChannel()),
        )
        result = await retrieve(config, QUESTION, ctx=_context(db_session, seeded), llm=make_llm())
        seen = sorted((t.channel, t.variant) for t in result.trace.channels)
        assert seen == [("dense", 0), ("dense", 1), ("lexical", 0), ("symbol", 0)]

    async def test_the_trace_is_json_serialisable(self, db_session, monkeypatch):
        seeded = await _seeded(db_session)
        result = await retrieve(STRUCTURAL, QUESTION, ctx=_context(db_session, seeded))
        encoded = json.dumps(asdict(result.trace))
        assert json.loads(encoded)["reranker"] == "jev"

    async def test_a_query_rewrite_failure_is_in_the_trace(self, db_session, monkeypatch):
        seeded = await _seeded(db_session)
        install_fake_openai(monkeypatch, "not json")
        config = HYBRID.model_copy(update={"query": QueryConfig(transform="multi_query")})
        result = await retrieve(config, QUESTION, ctx=_context(db_session, seeded), llm=make_llm())
        assert len(result.variants) == 1
        assert [(d["stage"], d["transform"]) for d in result.trace.degraded] == [
            ("query", "multi_query")
        ]


class TestCondense:
    async def test_a_follow_up_is_searched_as_the_standalone_question(
        self, db_session, monkeypatch
    ):
        seeded = await _seeded(db_session)
        responses = install_fake_openai(monkeypatch, json.dumps({"question": QUESTION}))

        class Turn:
            def __init__(self, role, content):
                self.role, self.content = role, content

        history = [Turn("user", "explain login"), Turn("assistant", "It uses bcrypt.")]
        result = await retrieve(
            HYBRID,
            "and how does it compare the hashes?",
            ctx=_context(db_session, seeded),
            history=history,
            llm=make_llm(),
        )
        assert len(responses.calls) == 1
        assert result.question == QUESTION
        assert result.variants[0].kind == "condensed"
        assert result.candidates[0].key == VERIFY_KEY


class TestPrefetch:
    async def test_every_needed_text_is_embedded_in_one_call(self, db_session, monkeypatch):
        seeded = await _seeded(db_session)
        install_fake_openai(
            monkeypatch, json.dumps({"queries": ["verify_password", "password check", "bcrypt"]})
        )
        ctx = _context(db_session, seeded)
        prefetched: list[list[str]] = []
        embed_batches: list[list[str]] = []
        real_prefetch, real_embed = ctx.prefetch_embeddings, ctx.embed

        async def spy_prefetch(texts):
            prefetched.append(list(texts))
            await real_prefetch(texts)

        async def spy_embed(texts):
            embed_batches.append(list(texts))
            return await real_embed(texts)

        monkeypatch.setattr(ctx, "prefetch_embeddings", spy_prefetch)
        monkeypatch.setattr(ctx, "embed", spy_embed)

        config = PipelineConfig(
            name="custom",
            query=QueryConfig(transform="multi_query"),
            channels=(DenseChannel(), HistoryChannel(), LexicalChannel()),
        )
        result = await retrieve(config, QUESTION, ctx=ctx, llm=make_llm())

        variant_texts = {v.text for v in result.variants}
        assert len(variant_texts) == 4
        assert len(prefetched) == 1
        assert set(prefetched[0]) == variant_texts
        # Dense and history both want each text; the context embeds each once.
        assert len(embed_batches) == 1
        assert sorted(embed_batches[0]) == sorted(variant_texts)

    async def test_hyde_text_is_prefetched_for_dense_but_not_history(self, db_session, monkeypatch):
        seeded = await _seeded(db_session)
        install_fake_openai(monkeypatch, json.dumps({"snippet": "def hypothetical(): ..."}))
        ctx = _context(db_session, seeded)
        prefetched: list[list[str]] = []
        real_prefetch = ctx.prefetch_embeddings

        async def spy_prefetch(texts):
            prefetched.append(list(texts))
            await real_prefetch(texts)

        monkeypatch.setattr(ctx, "prefetch_embeddings", spy_prefetch)
        config = PipelineConfig(
            name="custom",
            query=QueryConfig(transform="hyde"),
            channels=(DenseChannel(), HistoryChannel()),
        )
        await retrieve(config, QUESTION, ctx=ctx, llm=make_llm())
        assert len(prefetched) == 1
        assert set(prefetched[0]) == {QUESTION, "def hypothetical(): ..."}

    async def test_no_prefetch_when_no_channel_embeds(self, db_session, monkeypatch):
        seeded = await _seeded(db_session)
        ctx = _context(db_session, seeded)
        calls: list[object] = []

        async def spy_prefetch(texts):
            calls.append(texts)

        monkeypatch.setattr(ctx, "prefetch_embeddings", spy_prefetch)
        config = PipelineConfig(name="custom", channels=(LexicalChannel(), SymbolChannel()))
        await retrieve(config, QUESTION, ctx=ctx)
        assert calls == []

    async def test_a_failed_prefetch_degrades_only_the_dense_channel(self, db_session, monkeypatch):
        seeded = await _seeded(db_session)
        ctx = _context(db_session, seeded)

        async def broken_embed(texts):
            raise RuntimeError("embedding api down")

        monkeypatch.setattr(ctx, "embed", broken_embed)
        result = await retrieve(HYBRID, QUESTION, ctx=ctx)
        errors = {t.channel: t.error for t in result.trace.channels if t.error}
        assert set(errors) == {"dense"}
        assert "embedding api down" in errors["dense"]
        assert result.candidates
