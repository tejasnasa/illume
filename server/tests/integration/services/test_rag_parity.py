"""Parity: the Classic preset through the new pipeline equals the chat path it replaced.

The reference below is a frozen copy of the retrieval and generation path as it
stood before ``rag.answer_question`` became a wrapper over the retrieval
pipeline: the pgvector search with its diversity caps, batched source
resolution, the system prompt, and the message list and request keyword
arguments sent to the model. It is deliberately not imported from ``app``, so a
change to the live code cannot change the thing it is compared against. If a
difference here is intentional, that is a change to what the chat endpoint
returns, and it should be made on purpose, in this file as well.

Each scenario seeds one repository, runs the reference and the live path on the
same rows with the same fake embedder vectors, and compares what was retrieved,
what was cited, and every byte sent to the model.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from openai.types.responses import ResponseInputParam
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Embedding
from app.services import rag
from app.services.llm_config import LLMConfig
from app.services.llm_providers import PROVIDERS
from app.services.rag import ChatMessage
from app.services.retrieval.config import CLASSIC
from app.services.retrieval.pipeline import retrieve
from app.services.retrieval.resolve import SourceReference, resolve_sources
from app.services.retrieval.vector import prepare_filtered_vector_search
from tests.factories import make_user
from tests.fixtures.retrieval import (
    CommitSpec,
    DocumentSpec,
    FileSpec,
    PullRequestSpec,
    RepoSpec,
    SymbolSpec,
    angled_vector,
    axis_vector,
    make_context,
    make_llm,
    seed_repo,
)

pytestmark = pytest.mark.integration

QUESTION = "how are passwords checked?"
QUERY_VECTOR = axis_vector(0)
# Orthogonal to every seeded chunk, so beyond the 0.7 distance cut.
FAR_VECTOR = axis_vector(900)
CANNED = "No relevant code was found in this repository for your question."


# --- the frozen reference ---------------------------------------------------

TOP_K = 10

TYPE_CAPS = {
    "symbol": 5,
    "commit": 2,
    "pull_request": 1,
    "document": 1,
    "file": 2,
}


def reference_apply_diversity_caps(
    embeddings: Sequence[Embedding], total: int = TOP_K
) -> list[Embedding]:
    type_counts: defaultdict[str, int] = defaultdict(int)
    selected = []

    for e in embeddings:
        cap = TYPE_CAPS.get(e.source_type, 2)
        if type_counts[e.source_type] < cap:
            selected.append(e)
            type_counts[e.source_type] += 1
        if len(selected) == total:
            return selected

    for e in embeddings:
        if e not in selected:
            selected.append(e)
        if len(selected) == total:
            return selected

    return selected


async def reference_embed_query(client, query: str) -> list[float]:
    response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=query,
    )
    return response.data[0].embedding


async def reference_vector_search(db: AsyncSession, repository_id, query_vector, top_k=TOP_K):
    await prepare_filtered_vector_search(db)
    result = await db.execute(
        select(Embedding)
        .filter(
            Embedding.repository_id == repository_id,
            Embedding.embedding.cosine_distance(query_vector) < 0.7,
        )
        .order_by(Embedding.embedding.cosine_distance(query_vector))
        .limit(50)
    )
    embeddings = result.scalars().all()
    return reference_apply_diversity_caps(embeddings, top_k)


def reference_build_prompt(query: str, sources: list[SourceReference]) -> str:
    """Builds the system prompt with labeled context blocks and the grounding rules."""
    context_blocks = []

    for i, src in enumerate(sources):
        if src.source_type == "symbol":
            header = f"[Source {i + 1}] [Code] {src.file_path} — {src.symbol_name} (lines {src.start_line}–{src.end_line})"  # noqa: E501
        elif src.source_type == "commit":
            header = f"[Source {i + 1}] [Commit] {src.commit_hash} by {src.author_name}"
        elif src.source_type == "pull_request":
            header = f"[Source {i + 1}] [PR #{src.pr_number}] {src.pr_title}"
        elif src.source_type == "file":
            header = f"[Source {i + 1}] [Code] {src.file_path}"
        else:
            header = f"[Source {i + 1}] [README]"
        context_blocks.append(f"{header}\n{src.chunk_text}")

    context = "\n\n---\n\n".join(context_blocks)
    return f"""You are an expert code assistant analyzing a software repository.
            Answer the user's question using ONLY the context provided below.
            Context includes code, commit messages, pull requests, files and documentation.
            Be specific — reference file names, function names, line numbers, commit hashes, or PR numbers where relevant.
            If the answer cannot be found in the context, say so clearly.

            ## Context
            {context}

            ## Question
            {query}

            ## Answer
        """  # noqa: E501


@dataclass
class ReferenceOutcome:
    answer: str
    sources: list[SourceReference]
    generated: bool


async def reference_answer_question(
    query: str,
    repository_id: UUID,
    db: AsyncSession,
    history: list[ChatMessage] | None,
    llm: LLMConfig | None,
    *,
    embed_client,
    generation_client_factory,
) -> ReferenceOutcome:
    query_vector = await reference_embed_query(embed_client, query)
    chunks = await reference_vector_search(db, repository_id, query_vector, 10)

    if not chunks:
        return ReferenceOutcome(CANNED, [], False)

    sources = await resolve_sources(db, chunks)
    prompt = reference_build_prompt(query, sources)

    messages: list[dict] = [{"role": "system", "content": prompt}]
    if history:
        for turn in history:
            messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": query})

    generation_client_kwargs = (
        llm.client_kwargs() if llm is not None else {"api_key": settings.OPENAI_API_KEY}
    )
    generation_client = generation_client_factory(**generation_client_kwargs)
    generation_model = llm.model if llm is not None else settings.AI_MODEL
    generation_response_kwargs = (
        llm.response_kwargs("minimal") if llm is not None else {"reasoning": {"effort": "minimal"}}
    )

    response = await generation_client.responses.create(
        model=generation_model,
        **generation_response_kwargs,
        input=cast(ResponseInputParam, messages),
        max_output_tokens=3000,
    )
    return ReferenceOutcome((response.output_text or "").strip(), sources, True)


# --- a fake account that records both paths the same way --------------------


class RecordingAccount:
    """One OpenAI account's recorded traffic: clients built and requests made.

    Args:
        query_vector: What every embedding request returns.
    """

    def __init__(self, query_vector: list[float] = QUERY_VECTOR) -> None:
        self.query_vector = query_vector
        self.client_inits: list[dict[str, Any]] = []
        self.embedding_requests: list[dict[str, Any]] = []
        self.generation_requests: list[dict[str, Any]] = []

    def factory(self, **kwargs: Any) -> SimpleNamespace:
        self.client_inits.append(dict(kwargs))
        return SimpleNamespace(
            embeddings=SimpleNamespace(create=self._embed),
            responses=SimpleNamespace(create=self._generate),
        )

    async def _embed(self, **kwargs: Any) -> SimpleNamespace:
        self.embedding_requests.append(dict(kwargs))
        return SimpleNamespace(data=[SimpleNamespace(embedding=self.query_vector, index=0)])

    async def _generate(self, **kwargs: Any) -> SimpleNamespace:
        self.generation_requests.append(dict(kwargs))
        return SimpleNamespace(output_text="  The generated answer.  ")


@pytest.fixture
def install_account(monkeypatch):
    """Points ``rag.AsyncOpenAI``, which the wrapper builds its clients from, at a recorder."""

    def install(query_vector: list[float] = QUERY_VECTOR) -> RecordingAccount:
        account = RecordingAccount(query_vector)
        monkeypatch.setattr(rag, "AsyncOpenAI", account.factory)
        return account

    return install


# --- scenarios --------------------------------------------------------------


def _symbol_file(index: int, theta: float) -> FileSpec:
    return FileSpec(
        path=f"src/module_{index}.py",
        symbols=(
            SymbolSpec(
                name=f"func_{index}",
                source_code=f"def func_{index}():\n    return {index}\n",
                start_line=3,
                vector=angled_vector(theta),
            ),
        ),
    )


def mixed_spec() -> RepoSpec:
    """Sixteen hits inside the distance cut, every source type, caps that bite.

    Nearest first: symbols, commits, pull requests, README sections and file
    chunks interleaved, with seven symbols against a cap of five, three commits
    against two, and two of everything else against one. The first pass fills
    all ten slots, so the later commit, pull request, section, file and symbols
    never get in.
    """
    return RepoSpec(
        files=(
            _symbol_file(0, 0.05),
            _symbol_file(1, 0.10),
            _symbol_file(2, 0.20),
            _symbol_file(3, 0.30),
            _symbol_file(4, 0.45),
            _symbol_file(5, 0.60),
            _symbol_file(6, 0.75),
            FileSpec(path="docs/overview.md", file_chunk="docs/overview.md\nAn overview."),
            FileSpec(path="docs/design.md", file_chunk="docs/design.md\nThe design."),
        ),
        commits=(
            CommitSpec("aaaa111122223333", "fix: first commit", vector=angled_vector(0.15)),
            CommitSpec("bbbb111122223333", "feat: second commit", vector=angled_vector(0.35)),
            CommitSpec("cccc111122223333", "chore: third commit", vector=angled_vector(0.80)),
        ),
        pull_requests=(
            PullRequestSpec(7, "First PR", "about passwords", vector=angled_vector(0.25)),
            PullRequestSpec(8, "Second PR", "about tokens", vector=angled_vector(0.55)),
        ),
        documents=(
            DocumentSpec("Install", "Run it.", vector=angled_vector(0.40)),
            DocumentSpec("Usage", "Use it.", vector=angled_vector(0.65)),
        ),
    )


def backfill_spec() -> RepoSpec:
    """Twelve symbols, one commit and one pull request: the first pass leaves slots to backfill.

    The first pass takes five symbols, then the commit and the pull request. The
    remaining three slots are filled with the next-best symbols even though the
    symbol cap is spent, so the list has eight symbols and the commit and pull
    request sit in the middle of it rather than where relevance alone would put them.
    """
    thetas = [0.04 * (i + 1) for i in range(12)]
    return RepoSpec(
        files=tuple(_symbol_file(i, theta) for i, theta in enumerate(thetas)),
        commits=(CommitSpec("dddd111122223333", "fix: only commit", vector=angled_vector(0.30)),),
        pull_requests=(PullRequestSpec(9, "Only PR", "details", vector=angled_vector(0.33)),),
    )


SCENARIOS = {"mixed": mixed_spec, "backfill": backfill_spec}


async def seed_scenario(db, name: str):
    seeded = await seed_repo(db, await make_user(db), SCENARIOS[name]())
    # File chunks are seeded with hash vectors; place them in the ranking.
    placements = {"docs/overview.md": 0.50, "docs/design.md": 0.70}
    for embedding in seeded.embeddings:
        if embedding.source_type != "file":
            continue
        for path, theta in placements.items():
            if embedding.chunk_text.startswith(path):
                embedding.embedding = angled_vector(theta)
    await db.flush()
    return seeded


def groq_llm() -> LLMConfig:
    groq = PROVIDERS["groq"]
    return make_llm(
        base_url=groq.base_url, supports_reasoning=groq.supports_reasoning, model=groq.default_model
    )


HISTORY = [
    ChatMessage("user", "what is the auth flow?"),
    ChatMessage("assistant", "It checks a bcrypt hash."),
    ChatMessage("user", "and tokens?"),
]


async def run_live(db, seeded, llm, history) -> rag.RAGResponse:
    return await rag.answer_question(QUESTION, seeded.repo.id, db, history, llm=llm)


async def run_reference(db, seeded, llm, history, query_vector=QUERY_VECTOR):
    recorder = RecordingAccount(query_vector)
    embed_client = recorder.factory(api_key=settings.OPENAI_API_KEY)
    outcome = await reference_answer_question(
        QUESTION,
        seeded.repo.id,
        db,
        history,
        llm,
        embed_client=embed_client,
        generation_client_factory=recorder.factory,
    )
    return outcome, recorder


class TestScenarios:
    """The fixtures really do cover what they claim to."""

    async def test_the_mixed_scenario_has_more_hits_than_slots_and_the_caps_bite(self, db_session):
        seeded = await seed_scenario(db_session, "mixed")
        within_cut = list(
            await db_session.scalars(
                select(Embedding).where(
                    Embedding.repository_id == seeded.repo.id,
                    Embedding.embedding.cosine_distance(QUERY_VECTOR) < 0.7,
                )
            )
        )
        reference = await reference_vector_search(db_session, seeded.repo.id, QUERY_VECTOR, 10)

        assert len(within_cut) == 16
        assert {e.source_type for e in within_cut} == set(TYPE_CAPS)
        assert [e.source_type for e in reference].count("symbol") == 5
        selected = {e.id for e in reference}
        left_out = {e.source_type for e in within_cut if e.id not in selected}
        assert left_out == {"symbol", "commit", "pull_request", "document", "file"}

    async def test_the_backfill_scenario_exceeds_a_soft_cap_and_reorders(self, db_session):
        seeded = await seed_scenario(db_session, "backfill")
        reference = await reference_vector_search(db_session, seeded.repo.id, QUERY_VECTOR, 10)

        # Five capped symbols, the commit and the pull request, then three backfilled symbols.
        assert [e.source_type for e in reference] == [
            *["symbol"] * 5,
            "commit",
            "pull_request",
            *["symbol"] * 3,
        ]


class TestRetrievalParity:
    @pytest.mark.parametrize("scenario", sorted(SCENARIOS))
    async def test_the_same_chunks_in_the_same_order(self, db_session, scenario):
        seeded = await seed_scenario(db_session, scenario)

        reference = await reference_vector_search(db_session, seeded.repo.id, QUERY_VECTOR, 10)
        live = await retrieve(
            CLASSIC,
            QUESTION,
            ctx=make_context(db_session, seeded.repo, {QUESTION: QUERY_VECTOR}),
        )

        assert len(reference) == 10
        assert [(c.source_id, c.text) for c in live.candidates] == [
            (e.source_id, e.chunk_text) for e in reference
        ]


class TestAnswerParity:
    @pytest.mark.parametrize("scenario", sorted(SCENARIOS))
    @pytest.mark.parametrize(
        "llm_factory", [make_llm, groq_llm, lambda: None], ids=["byok", "groq", "server-key"]
    )
    @pytest.mark.parametrize("history", [None, HISTORY], ids=["no-history", "history"])
    async def test_sources_prompt_messages_and_request_kwargs_are_identical(
        self, db_session, install_account, scenario, llm_factory, history
    ):
        seeded = await seed_scenario(db_session, scenario)
        llm = llm_factory()
        account = install_account()

        expected, reference = await run_reference(db_session, seeded, llm, history)
        live = await run_live(db_session, seeded, llm, history)

        assert expected.generated is True and live.generated is True
        assert len(expected.sources) == 10
        # The same SourceReferences, in the same order, and the same answer text.
        assert live.sources == expected.sources
        assert live.answer == expected.answer == "The generated answer."

        [ref_request] = reference.generation_requests
        [live_request] = account.generation_requests

        # Byte-identical prompt.
        live_prompt = live_request["input"][0]["content"]
        assert live_prompt.encode("utf-8") == ref_request["input"][0]["content"].encode("utf-8")
        assert live_prompt == rag._build_prompt(QUESTION, expected.sources)

        # Identical messages and request keyword arguments, nothing extra.
        assert live_request["input"] == ref_request["input"]
        assert live_request == ref_request
        sends_reasoning = llm is None or llm.supports_reasoning
        assert set(live_request) == {
            "model",
            "input",
            "max_output_tokens",
            *(["reasoning"] if sends_reasoning else []),
        }
        assert live_request["max_output_tokens"] == 3000
        roles = [message["role"] for message in live_request["input"]]
        assert roles == ["system", *(turn.role for turn in history or []), "user"]

        # Identical clients: embeddings on the server key with no base URL, then generation.
        assert account.client_inits == reference.client_inits
        assert account.client_inits[0] == {"api_key": settings.OPENAI_API_KEY}
        assert account.embedding_requests == reference.embedding_requests
        assert account.embedding_requests == [
            {"model": "text-embedding-3-small", "input": QUESTION}
        ]

    async def test_every_source_type_renders_the_same_prompt(self):
        sources = [
            SourceReference("symbol", "def f(): ...", "a.py", "f", 3, 4),
            SourceReference("commit", "abc fix", commit_hash="abc1234", author_name="Ada"),
            SourceReference("pull_request", "PR text", pr_number=5, pr_title="Fix — it"),
            SourceReference("file", "a.py overview", file_path="a.py"),
            SourceReference("document", "# README\n## Install\nRun."),
        ]
        live = rag._build_prompt("why?", sources)
        expected = reference_build_prompt("why?", sources)
        assert live == expected
        assert live.encode("utf-8") == expected.encode("utf-8")


class TestNoContextParity:
    async def test_nothing_retrieved_is_the_canned_answer_without_a_model_call(
        self, db_session, install_account
    ):
        seeded = await seed_scenario(db_session, "mixed")
        account = install_account(FAR_VECTOR)

        expected, reference = await run_reference(
            db_session, seeded, make_llm(), None, query_vector=FAR_VECTOR
        )
        live = await run_live(db_session, seeded, make_llm(), None)

        assert expected.answer == live.answer == CANNED
        assert expected.sources == live.sources == []
        assert expected.generated is False and live.generated is False
        # Neither path made a model call or built a generation client.
        assert reference.generation_requests == [] and account.generation_requests == []
        assert (
            reference.client_inits == account.client_inits == [{"api_key": settings.OPENAI_API_KEY}]
        )

    async def test_a_repository_with_no_embeddings_is_the_canned_answer(
        self, db_session, install_account
    ):
        seeded = await seed_repo(db_session, await make_user(db_session), RepoSpec())
        account = install_account()
        live = await run_live(db_session, seeded, make_llm(), None)

        assert (live.answer, live.sources, live.generated) == (CANNED, [], False)
        assert account.generation_requests == []
        assert len(account.client_inits) == 1
