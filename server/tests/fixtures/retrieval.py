"""A data-driven repository for exercising the retrieval channels.

The repository is described by a :class:`RepoSpec` -- files, the symbols in
them, commits, pull requests and README sections -- and :func:`seed_repo` turns
a spec into rows. Growing the fixture means adding entries to
:data:`DEFAULT_SPEC`, not writing more seeding code.

The same spec can be seeded twice under two repositories. Both copies then have
the same paths and the same symbol names, which is the case that catches a
channel joining on a path or a name instead of on ``file_id`` and
``repository_id``.

Embedding vectors are deterministic. By default a row's vector is a hash of its
text (:func:`hash_vector`), which is stable but unrelated to any query. A test
that needs a known dense ordering gives the row a ``vector`` and maps the query
text to a vector with :func:`fake_embedder`.
"""

from __future__ import annotations

import hashlib
import math
import random
import textwrap
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AstSymbol,
    Commit,
    Dependency,
    Embedding,
    File,
    PullRequest,
    Repository,
    User,
)
from app.models.file_cochange import FileCochange
from app.services.cochange import build_cochange
from app.services.embedder import (
    _build_chunk_text,
    _build_commit_chunk,
    _build_file_chunk,
    _build_pr_chunk,
    _build_readme_chunks,
)
from app.services.llm_config import LLMConfig
from app.services.retrieval.candidate import Candidate
from app.services.retrieval.channels.base import Embedder, RetrievalContext
from app.services.retrieval.citations import commit_key, document_key
from app.services.retrieval.resolve import SourceReference
from tests.factories import make_repo

DIMENSIONS = 1536
SPARSE_NONZERO = 32

# Namespace for the row ids of a spec seeded with ``stable_ids``.
STABLE_ID_NAMESPACE = uuid.UUID("3f1c2b7a-6d94-4e08-9a5b-1c7e2d8f4a60")


# --- vectors ---------------------------------------------------------------


def hash_vector(text: str, dimensions: int = DIMENSIONS) -> list[float]:
    """A deterministic unit vector derived from the text's SHA-256."""
    seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
    rng = random.Random(seed)
    values = [rng.gauss(0.0, 1.0) for _ in range(dimensions)]
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]


def sparse_hash_vector(
    text: str, dimensions: int = DIMENSIONS, nonzero: int = SPARSE_NONZERO
) -> list[float]:
    """A deterministic unit vector with only ``nonzero`` non-zero components.

    Behaves like :func:`hash_vector` for a test's purposes: the same text gives the
    same vector, and two different texts are nearly orthogonal, far outside the 0.7
    distance cut. It exists because the HNSW index costs about 50 ms to insert a
    dense random 1536-dimension vector and about 5 ms to insert a sparse one, which
    is the difference between a fixture of 170 chunks seeding in 1 s or in 9 s.
    """
    seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
    rng = random.Random(seed)
    values = [0.0] * dimensions
    for position in rng.sample(range(dimensions), nonzero):
        values[position] = rng.gauss(0.0, 1.0)
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]


def axis_vector(index: int = 0, dimensions: int = DIMENSIONS) -> list[float]:
    """A unit vector along one axis. Two different axes are at distance 1.0."""
    vector = [0.0] * dimensions
    vector[index] = 1.0
    return vector


def angled_vector(theta: float, dimensions: int = DIMENSIONS) -> list[float]:
    """A unit vector at angle ``theta`` radians from axis 0, in the plane of axes 0 and 1.

    Its cosine distance from :func:`axis_vector` ``(0)`` is ``1 - cos(theta)``,
    so larger angles sort further away.
    """
    return [math.cos(theta), math.sin(theta)] + [0.0] * (dimensions - 2)


def fake_embedder(mapping: Mapping[str, list[float]] | None = None) -> Embedder:
    """An embedder that needs no network.

    Args:
        mapping: Query text to the exact vector it should embed to. Any other
            text embeds to :func:`hash_vector`.
    """
    known = dict(mapping or {})

    async def embed(texts: Sequence[str]) -> list[list[float]]:
        return [known[text] if text in known else hash_vector(text) for text in texts]

    return embed


def make_context(
    db: AsyncSession,
    repo: Repository,
    mapping: Mapping[str, list[float]] | None = None,
) -> RetrievalContext:
    """A retrieval context over one repository with the fake embedder."""
    return RetrievalContext(repository_id=repo.id, db=db, embed=fake_embedder(mapping))


@asynccontextmanager
async def rolled_back_session(engine) -> AsyncIterator[AsyncSession]:
    """A session whose work is always rolled back, for fixtures wider than one test.

    The session joins an outer transaction that is never committed, as the
    ``db_session`` fixture does. A module-scoped fixture or a standalone script
    uses this where ``db_session`` is not available.
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


# --- a fake model and event sink ----------------------------------------------


class FakeResponses:
    """A stand-in for ``client.responses`` that replays scripted outputs.

    A call with ``stream=True`` gets an async iterator of events instead: one
    ``response.output_text.delta`` per piece of the output (split by
    :attr:`chunk_size` characters), then a ``response.completed`` event.

    Attributes:
        calls: The keyword arguments of every ``create`` call, verbatim.
        client_inits: The keyword arguments of every client constructed.
        chunk_size: How many characters each streamed delta carries.
    """

    def __init__(self, outputs: Sequence[Any]) -> None:
        self.outputs = list(outputs)
        self.calls: list[dict[str, Any]] = []
        self.client_inits: list[dict[str, Any]] = []
        self.chunk_size = 5

    async def create(self, **kwargs: Any) -> Any:
        """Records the request and returns the next output, raising it if it is an exception."""
        self.calls.append(kwargs)
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        if kwargs.get("stream"):
            return self._events(output)
        return SimpleNamespace(output_text=output)

    async def _events(self, output: str):
        yield SimpleNamespace(type="response.created")
        for start in range(0, len(output), self.chunk_size):
            yield SimpleNamespace(
                type="response.output_text.delta", delta=output[start : start + self.chunk_size]
            )
        yield SimpleNamespace(type="response.completed")


def install_fake_openai(monkeypatch, *outputs: Any, module: Any = None) -> FakeResponses:
    """Replaces ``AsyncOpenAI`` in a module with a client replaying ``outputs``.

    Args:
        monkeypatch: The pytest fixture.
        *outputs: The scripted replies, in call order; an exception is raised.
        module: The module whose ``AsyncOpenAI`` name is replaced. Defaults to
            the query module; the LLM reranker and the answerer have their own.
    """
    from app.services.retrieval import query as query_module

    responses = FakeResponses(outputs)

    def factory(*args: Any, **kwargs: Any) -> SimpleNamespace:
        responses.client_inits.append(kwargs)
        return SimpleNamespace(responses=responses)

    monkeypatch.setattr(module if module is not None else query_module, "AsyncOpenAI", factory)
    return responses


def make_candidate(
    key: str,
    text: str = "",
    *,
    source_type: str = "symbol",
    file_path: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    commit_hash: str | None = None,
    pr_number: int | None = None,
    fused_score: float | None = None,
) -> Candidate:
    """A candidate that needs no database, for tests of the stages after retrieval."""
    reference = SourceReference(
        source_type=source_type,
        chunk_text=text or key,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        commit_hash=commit_hash,
        pr_number=pr_number,
    )
    return Candidate(
        key=key,
        reference=reference,
        text=text or key,
        fused_score=fused_score,
        provenance="history" if source_type in ("commit", "pull_request") else "repo",
    )


def make_llm(**overrides: Any) -> LLMConfig:
    """A BYOK-style credential that never reaches a network."""
    fields: dict[str, Any] = {
        "api_key": "sk-test",
        "model": "test-model",
        "base_url": None,
        "supports_reasoning": True,
        "source": "user",
    }
    fields.update(overrides)
    return LLMConfig(**fields)


class RecordingEmit:
    """An emitter that keeps every event for assertions."""

    def __init__(self) -> None:
        self.items: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, event: str, payload: dict[str, Any]) -> None:
        self.items.append((event, payload))

    @property
    def degraded(self) -> list[dict[str, Any]]:
        """The payloads of the ``degraded`` events, in order."""
        return [payload for event, payload in self.items if event == "degraded"]


# --- the description of a repository ----------------------------------------


@dataclass(frozen=True)
class SymbolSpec:
    """One symbol and whether it has an embedding row.

    Attributes:
        name: The symbol's name.
        kind: ``function``, ``class``, ``method``, or a kind that is never searched.
        source_code: The stored body.
        start_line: First line in the file.
        embed: Whether to add a ``symbol`` embedding row for it.
        chunk_text: The embedded text; rendered from the symbol when ``None``.
        vector: The embedding vector; a hash of the chunk text when ``None``.
    """

    name: str
    kind: str = "function"
    source_code: str = ""
    start_line: int = 1
    embed: bool = True
    chunk_text: str | None = None
    vector: list[float] | None = None

    @property
    def end_line(self) -> int:
        """Last line, derived from the body."""
        return self.start_line + max(len(self.source_code.splitlines()), 1) - 1


@dataclass(frozen=True)
class FileSpec:
    """A file, its symbols and an optional whole-file chunk."""

    path: str
    symbols: tuple[SymbolSpec, ...] = ()
    fan_in: int = 0
    language: str = "python"
    file_chunk: str | None = None


@dataclass(frozen=True)
class CommitSpec:
    """A commit and its embedded chunk."""

    hash: str
    message: str
    files: tuple[str, ...] = ()
    author: str = "Ada Lovelace"
    vector: list[float] | None = None
    chunk_text: str | None = None


@dataclass(frozen=True)
class PullRequestSpec:
    """A pull request and its embedded chunk."""

    number: int
    title: str
    description: str = ""
    vector: list[float] | None = None
    chunk_text: str | None = None


@dataclass(frozen=True)
class DocumentSpec:
    """A README section and its embedded chunk."""

    heading: str
    body: str
    vector: list[float] | None = None
    chunk_text: str | None = None


@dataclass(frozen=True)
class ImportSpec:
    """One file importing another.

    Attributes:
        source: Path of the importing file.
        target: Path of the imported file. It needs at least one symbol of any kind.
        weight: How many symbol-level dependencies the pair collapses to. Each is
            a fresh ``import`` symbol in the source, which is never a graph node.
    """

    source: str
    target: str
    weight: int = 1


@dataclass(frozen=True)
class CochangeSpec:
    """A stored co-change pair, given by path in either order."""

    path_a: str
    path_b: str
    together: int = 2
    a_count: int = 2
    b_count: int = 2

    @property
    def jaccard(self) -> float:
        """``together / (a_count + b_count - together)``."""
        return self.together / (self.a_count + self.b_count - self.together)


@dataclass(frozen=True)
class RepoSpec:
    """Everything one fixture repository contains.

    Attributes:
        files: The files and their symbols.
        imports: File-to-file imports, stored as symbol-level dependencies.
        cochange: Co-change pairs inserted as given.
        commits: Commits, with the paths each changed.
        pull_requests: Pull requests.
        documents: README sections.
        derive_cochange: Also run the real ``build_cochange`` over the seeded
            commits, so the table holds what ingestion would have produced.
        sparse_vectors: Embed with :func:`sparse_hash_vector` instead of
            :func:`hash_vector`, which seeds a large spec several times faster.
        stable_ids: Give every row an id derived from the repository name, so
            tie-breaking by id, and therefore ranking, is the same on every run.
    """

    files: tuple[FileSpec, ...] = ()
    imports: tuple[ImportSpec, ...] = ()
    cochange: tuple[CochangeSpec, ...] = ()
    commits: tuple[CommitSpec, ...] = ()
    pull_requests: tuple[PullRequestSpec, ...] = ()
    documents: tuple[DocumentSpec, ...] = ()
    derive_cochange: bool = False
    sparse_vectors: bool = False
    stable_ids: bool = False


# --- the rows that were created ---------------------------------------------


@dataclass
class SeededRepo:
    """The rows :func:`seed_repo` created, indexed for assertions.

    Attributes:
        repo: The repository.
        files: Files by path.
        symbols: Symbols by ``(path, name)``.
        symbol_embeddings: Symbol embedding rows by ``(path, name)``.
        commits: Commits by hash.
        pull_requests: Pull requests by number.
        embeddings: Every embedding row created, in creation order.
    """

    repo: Repository
    files: dict[str, File] = field(default_factory=dict)
    symbols: dict[tuple[str, str], AstSymbol] = field(default_factory=dict)
    symbol_embeddings: dict[tuple[str, str], Embedding] = field(default_factory=dict)
    commits: dict[str, Commit] = field(default_factory=dict)
    pull_requests: dict[int, PullRequest] = field(default_factory=dict)
    embeddings: list[Embedding] = field(default_factory=list)

    def symbol_named(self, name: str) -> AstSymbol:
        """The only symbol with this name; fails when the name is not unique."""
        found = [symbol for (_, n), symbol in self.symbols.items() if n == name]
        assert len(found) == 1, f"{name!r} matches {len(found)} symbols"
        return found[0]

    def source_ids(self) -> set[uuid.UUID]:
        """Every row id a candidate from this repository may carry as ``source_id``."""
        ids = {symbol.id for symbol in self.symbols.values()}
        ids |= {commit.id for commit in self.commits.values()}
        ids |= {pull_request.id for pull_request in self.pull_requests.values()}
        ids |= {embedding.source_id for embedding in self.embeddings}
        return ids

    def file_ids(self) -> set[uuid.UUID]:
        """The ids of this repository's files."""
        return {file.id for file in self.files.values()}


def render_symbol_chunk(path: str, spec: SymbolSpec) -> str:
    """The chunk text a symbol is embedded with in this fixture."""
    return f"# {path}\n## {spec.kind}: {spec.name}\n{spec.source_code}"


async def seed_repo(
    db: AsyncSession,
    user: User,
    spec: RepoSpec | None = None,
    *,
    name: str = "retrieval-fixture",
) -> SeededRepo:
    """Creates a repository and everything in ``spec`` under it.

    Args:
        db: The test session.
        user: The owner.
        spec: What to create; :data:`DEFAULT_SPEC` when omitted.
        name: The repository name. With ``spec.stable_ids`` it also seeds the row ids,
            so a spec with stable ids can be seeded once per name in a transaction.
    """
    spec = spec or DEFAULT_SPEC
    repo = await make_repo(db, user, name=name)
    seeded = SeededRepo(repo=repo)

    def row_id(kind: str, *parts: object) -> dict[str, uuid.UUID]:
        """An explicit ``id`` keyword for the row, or nothing when ids are left random.

        Channels break ties between equally ranked rows by id, so random ids make a
        ranking near a cut-off differ from run to run. A check that asserts on
        positions needs the same order every time.
        """
        if not spec.stable_ids:
            return {}
        return {"id": uuid.uuid5(STABLE_ID_NAMESPACE, "/".join([name, kind, *map(str, parts)]))}

    # Rows are added in groups and flushed once per group: a group's ids are needed
    # by the next one, and one round trip per row made seeding the larger fixture
    # the slowest part of the suite that uses it. Server-side defaults come back
    # with the INSERT, so nothing needs a refresh.
    for file_spec in spec.files:
        file = File(
            **row_id("file", file_spec.path),
            repository_id=repo.id,
            path=file_spec.path,
            language=file_spec.language,
            loc=10,
            fan_in=file_spec.fan_in,
            fan_out=0,
            criticality="safe",
            has_tests=False,
        )
        seeded.files[file_spec.path] = file
    db.add_all(seeded.files.values())
    await db.flush()

    for file_spec in spec.files:
        for symbol_spec in file_spec.symbols:
            symbol = AstSymbol(
                **row_id("symbol", file_spec.path, symbol_spec.name),
                file_id=seeded.files[file_spec.path].id,
                kind=symbol_spec.kind,
                name=symbol_spec.name,
                start_line=symbol_spec.start_line,
                end_line=symbol_spec.end_line,
                source_code=symbol_spec.source_code,
                cyclomatic_complexity=1,
            )
            seeded.symbols[(file_spec.path, symbol_spec.name)] = symbol

    # Each import is a fresh symbol in the importing file, never a graph node. The
    # target is the first symbol the imported file holds.
    first_symbol = {}
    for (path, _), symbol in seeded.symbols.items():
        first_symbol.setdefault(path, symbol)
    import_pairs: list[tuple[AstSymbol, str]] = []
    for import_spec in spec.imports:
        for index in range(import_spec.weight):
            source_symbol = AstSymbol(
                **row_id("import", import_spec.source, import_spec.target, index),
                file_id=seeded.files[import_spec.source].id,
                kind="import",
                name=f"import_{import_spec.target}_{index}",
                start_line=1,
                end_line=5,
                source_code="",
                cyclomatic_complexity=1,
            )
            seeded.symbols[(import_spec.source, source_symbol.name)] = source_symbol
            import_pairs.append((source_symbol, import_spec.target))
    db.add_all(seeded.symbols.values())
    await db.flush()

    db.add_all(
        Dependency(
            source_symbol_id=source_symbol.id,
            target_symbol_id=first_symbol[target].id,
            dep_type="imports",
        )
        for source_symbol, target in import_pairs
    )

    for pair in spec.cochange:
        left, right = seeded.files[pair.path_a], seeded.files[pair.path_b]
        left_count, right_count = pair.a_count, pair.b_count
        if left.id > right.id:
            left, right, left_count, right_count = right, left, right_count, left_count
        db.add(
            FileCochange(
                file_a_id=left.id,
                file_b_id=right.id,
                repository_id=repo.id,
                together=pair.together,
                a_count=left_count,
                b_count=right_count,
                jaccard=pair.jaccard,
            )
        )

    base = datetime(2026, 1, 1, tzinfo=UTC)
    for index, commit_spec in enumerate(spec.commits):
        seeded.commits[commit_spec.hash] = Commit(
            **row_id("commit", commit_spec.hash),
            repository_id=repo.id,
            hash=commit_spec.hash,
            author_name=commit_spec.author,
            author_email="ada@example.com",
            message=commit_spec.message,
            files_changed=len(commit_spec.files),
            changed_files_list=list(commit_spec.files),
            authored_at=base + timedelta(days=index),
        )
    for pr_spec in spec.pull_requests:
        seeded.pull_requests[pr_spec.number] = PullRequest(
            **row_id("pull_request", pr_spec.number),
            repository_id=repo.id,
            number=pr_spec.number,
            title=pr_spec.title,
            description=pr_spec.description,
            author="Ada Lovelace",
            files_changed=0,
        )
    db.add_all(seeded.commits.values())
    db.add_all(seeded.pull_requests.values())
    await db.flush()

    # Embedding rows last, in the order they are reported: per file the symbols and
    # then the file chunk, followed by commits, pull requests and README sections.
    def document_id(index: int) -> uuid.UUID:
        """The source id of README section ``index``: fixed with stable ids, else random."""
        if spec.stable_ids:
            return uuid.uuid5(STABLE_ID_NAMESPACE, f"{name}/document/{index}")
        return uuid.uuid4()

    default_vector = sparse_hash_vector if spec.sparse_vectors else hash_vector

    def embedding(source_id, source_type, chunk, vector, file_id=None) -> Embedding:
        return Embedding(
            **row_id("embedding", source_type, source_id),
            repository_id=repo.id,
            source_id=source_id,
            source_type=source_type,
            chunk_text=chunk,
            file_id=file_id,
            embedding=vector or default_vector(chunk),
        )

    for file_spec in spec.files:
        file = seeded.files[file_spec.path]
        for symbol_spec in file_spec.symbols:
            if not symbol_spec.embed:
                continue
            symbol = seeded.symbols[(file_spec.path, symbol_spec.name)]
            chunk = symbol_spec.chunk_text or render_symbol_chunk(file_spec.path, symbol_spec)
            row = embedding(symbol.id, "symbol", chunk, symbol_spec.vector, file.id)
            seeded.symbol_embeddings[(file_spec.path, symbol_spec.name)] = row
            seeded.embeddings.append(row)
        if file_spec.file_chunk is not None:
            seeded.embeddings.append(
                embedding(file.id, "file", file_spec.file_chunk, None, file.id)
            )

    for commit_spec in spec.commits:
        chunk = commit_spec.chunk_text or (
            f"{commit_spec.hash[:8]} by {commit_spec.author}\n{commit_spec.message}\n"
            + "\n".join(commit_spec.files)
        )
        commit = seeded.commits[commit_spec.hash]
        seeded.embeddings.append(embedding(commit.id, "commit", chunk, commit_spec.vector))

    for pr_spec in spec.pull_requests:
        chunk = (
            pr_spec.chunk_text or f"PR #{pr_spec.number}: {pr_spec.title}\n{pr_spec.description}"
        )
        pull_request = seeded.pull_requests[pr_spec.number]
        seeded.embeddings.append(embedding(pull_request.id, "pull_request", chunk, pr_spec.vector))

    for index, document in enumerate(spec.documents):
        chunk = document.chunk_text or f"# README\n## {document.heading}\n{document.body}"
        seeded.embeddings.append(embedding(document_id(index), "document", chunk, document.vector))

    db.add_all(seeded.embeddings)
    await db.flush()
    if spec.derive_cochange:
        # The real builder is synchronous, so it runs on the session's sync face
        # and sees the rows flushed above.
        await db.run_sync(lambda sync_db: build_cochange(sync_db, repo.id))
    return seeded


# --- the default repository --------------------------------------------------

DEFAULT_SPEC = RepoSpec(
    files=(
        FileSpec(
            path="app/auth/security.py",
            fan_in=5,
            file_chunk=(
                "app/auth/security.py\nPassword hashing and token checks.\n"
                "verify_password, hash_password"
            ),
            symbols=(
                SymbolSpec(
                    name="verify_password",
                    source_code=(
                        "def verify_password(plain, hashed):\n"
                        "    # compare with bcrypt\n"
                        "    return bcrypt.checkpw(plain, hashed)\n"
                    ),
                    start_line=10,
                ),
                SymbolSpec(
                    name="hash_password",
                    source_code=(
                        "def hash_password(plain):\n"
                        "    return bcrypt.hashpw(plain, bcrypt.gensalt())\n"
                    ),
                    start_line=20,
                ),
                SymbolSpec(
                    name="PasswordPolicy",
                    kind="class",
                    source_code="class PasswordPolicy:\n    min_length = 12\n",
                    start_line=30,
                ),
            ),
        ),
        FileSpec(
            path="app/users/service.py",
            fan_in=3,
            symbols=(
                SymbolSpec(
                    name="getUserById",
                    source_code=(
                        "def getUserById(user_id):\n    return db.query(User).get(user_id)\n"
                    ),
                    start_line=5,
                ),
                SymbolSpec(
                    name="create_user",
                    source_code="def create_user(email):\n    return User(email=email)\n",
                    start_line=15,
                ),
                SymbolSpec(
                    name="delete_user",
                    kind="method",
                    source_code="def delete_user(self, user_id):\n    self.db.delete(user_id)\n",
                    start_line=25,
                    embed=False,
                ),
            ),
        ),
        FileSpec(
            path="app/users/routes.py",
            fan_in=1,
            symbols=(
                # Imports and variables are stored but never searched.
                SymbolSpec(
                    name="getUserById",
                    kind="import",
                    source_code="from app.users.service import getUserById\n",
                    embed=False,
                ),
                SymbolSpec(
                    name="MAX_PAGE_SIZE",
                    kind="variable",
                    source_code="MAX_PAGE_SIZE = 100\n",
                    start_line=3,
                    embed=False,
                ),
                SymbolSpec(
                    name="list_users",
                    source_code="def list_users():\n    return fetch_all(User)\n",
                    start_line=8,
                ),
            ),
        ),
        FileSpec(
            path="app/billing/invoice.py",
            fan_in=1,
            symbols=(
                SymbolSpec(
                    name="format_discount",
                    source_code='def format_discount(rate):\n    return f"{rate}% off"\n',
                    start_line=4,
                ),
                SymbolSpec(
                    name="compute_total",
                    source_code=(
                        "def compute_total(items):\n    return sum(i.price for i in items)\n"
                    ),
                    start_line=12,
                ),
            ),
        ),
    ),
    commits=(
        CommitSpec(
            hash="a1b2c3d4e5f60718",
            message="fix: reject expired tokens in verify_password",
            files=("app/auth/security.py",),
        ),
        CommitSpec(
            hash="b2c3d4e5f6071829",
            message="feat: add invoice totals",
            files=("app/billing/invoice.py",),
        ),
        CommitSpec(
            hash="c3d4e5f607182930",
            message="chore: bump dependencies",
            files=("pyproject.toml",),
        ),
    ),
    pull_requests=(
        PullRequestSpec(
            number=12,
            title="Switch password hashing to bcrypt",
            description="Replaces sha1 hashing; verify_password now uses bcrypt.checkpw.",
        ),
        PullRequestSpec(
            number=13,
            title="Add invoice discounts",
            description="Adds format_discount to the billing module.",
        ),
    ),
    documents=(
        DocumentSpec(heading="Installation", body="Run uv sync, then start the server."),
        DocumentSpec(heading="Authentication", body="Passwords are hashed with bcrypt."),
    ),
)


# --- a realistic repository with known answers ----------------------------------
#
# "Harbor": a small web API with authentication, users, billing, a job queue,
# notifications and middleware. Thirty files, with the facts the retrieval check
# depends on written down next to the code that creates them:
#
# * Imports form a graph with one barrel (`app/auth/__init__.py`, which only
#   re-exports) and importers that reach `security.py` only through it.
# * Three pairs of files change together without importing each other. The
#   history also holds one bulk commit over 30 paths, which the co-change
#   builder must ignore.
# * `rebuild_monthly_statements` is longer than the embedder's chunk limit, so it
#   has no symbol embedding row: only grep and symbol-name search can reach it.
# * `getUserById` is camelCase, `verify_password` is snake_case.
#
# Chunk text is rendered with the embedder's own builders, so it has the shape
# the real index has.

# The same estimate the embedder applies: four characters to a token.
_CHUNK_TOKEN_LIMIT = 2048


def _def(kind: str, name: str, source: str, *, embed: bool = True) -> tuple[str, str, str, bool]:
    """One symbol of a module: its kind, name and source, as it appears in the file."""
    return kind, name, textwrap.dedent(source).strip("\n") + "\n", embed


def _module(
    path: str,
    defs: Sequence[tuple[str, str, str, bool]] = (),
    *,
    note: str | None = None,
    language: str = "python",
) -> FileSpec:
    """A file spec with the symbols laid out one after another and chunks rendered.

    A symbol gets an embedding row only when it is a function, class or method and
    ``embed`` allows it. The whole-file chunk is added when there is a ``note``.
    """
    symbols: list[SymbolSpec] = []
    line = 4
    for kind, name, source, embed in defs:
        searchable = kind in ("function", "class", "method")
        symbol = SymbolSpec(
            name=name,
            kind=kind,
            source_code=source,
            start_line=line,
            embed=embed and searchable,
            chunk_text=_build_chunk_text(path, kind, name, source) if searchable else None,
        )
        symbols.append(symbol)
        line = symbol.end_line + 3
    names = [s.name for s in symbols if s.kind in ("function", "class", "method")]
    return FileSpec(
        path=path,
        symbols=tuple(symbols),
        language=language,
        file_chunk=_build_file_chunk(path, names, note) if note else None,
    )


def _commit(message: str, files: Sequence[str], author: str = "Ada Lovelace") -> CommitSpec:
    """A commit whose hash is derived from its message, with the embedder's chunk text."""
    digest = hashlib.sha1(message.encode("utf-8")).hexdigest()[:16]
    chunk = _build_commit_chunk(
        SimpleNamespace(
            hash=digest, author_name=author, message=message, changed_files_list=list(files)
        )
    )
    return CommitSpec(
        hash=digest, message=message, files=tuple(files), author=author, chunk_text=chunk
    )


def _pull_request(number: int, title: str, description: str) -> PullRequestSpec:
    """A pull request with the embedder's chunk text."""
    chunk = _build_pr_chunk(SimpleNamespace(number=number, title=title, description=description))
    return PullRequestSpec(number=number, title=title, description=description, chunk_text=chunk)


# The function below has to be longer than the embedder will index. It is built
# from one rounding rule per currency so it reads like real, repetitive
# production code rather than filler.
_CURRENCY_DIGITS = (
    ("USD", 2), ("EUR", 2), ("GBP", 2), ("JPY", 0), ("CHF", 2), ("CAD", 2), ("AUD", 2),
    ("NZD", 2), ("SEK", 2), ("NOK", 2), ("DKK", 2), ("PLN", 2), ("CZK", 2), ("HUF", 2),
    ("INR", 2), ("BRL", 2), ("MXN", 2), ("ZAR", 2), ("SGD", 2), ("HKD", 2), ("KRW", 0),
    ("TRY", 2), ("ILS", 2), ("THB", 2), ("IDR", 2), ("MYR", 2), ("PHP", 2), ("TWD", 2),
    ("CLP", 0), ("COP", 2), ("VND", 0), ("ISK", 0), ("KWD", 3), ("BHD", 3), ("OMR", 3),
)  # fmt: skip


def _long_statement_function() -> str:
    """The source of ``rebuild_monthly_statements``, deliberately over the chunk limit."""
    lines = [
        "def rebuild_monthly_statements(session, account_id, period):",
        '    """Recompute every statement line for one account and billing period.',
        "",
        "    Charges are grouped by currency and rounded by that currency's own rule, so",
        "    a month that spans a plan change still adds up to what was invoiced.",
        '    """',
        "    charges = session.query(Charge).filter_by(account_id=account_id).all()",
        "    statements = []",
        "    for currency, group in group_by_currency(charges):",
        "        carry = Decimal(0)",
        "        for charge in group:",
        "            if period.start < LEGACY_PRORATION_CUTOFF:",
        "                carry += prorate_by_calendar_days(charge, period)",
        "            else:",
        "                carry += prorate_by_billing_cycle(charge, period)",
    ]
    for code, digits in _CURRENCY_DIGITS:
        lines += [
            f'        if currency == "{code}":',
            f"            minor_units = {digits}",
            "            carry = round_half_even(carry, minor_units)",
            f'            statements.append(StatementLine(currency="{code}", amount=carry))',
            "            session.add(statements[-1])",
            f'            audit.record("statement_line", currency="{code}", digits=minor_units)',
        ]
    lines += ["    session.flush()", "    return statements"]
    return "\n".join(lines)


_STATEMENTS_SOURCE = _long_statement_function()
assert len(_STATEMENTS_SOURCE) // 4 > _CHUNK_TOKEN_LIMIT, "the long function must exceed the limit"


# --- the files ---------------------------------------------------------------

_MAIN = _module(
    "app/main.py",
    [
        _def(
            "function",
            "create_app",
            '''
            def create_app() -> FastAPI:
                """Build the application: settings, error handlers and every router."""
                settings = get_settings()
                app = FastAPI(title="Harbor", debug=settings.debug)
                init_engine(settings.database_url)
                register_error_handlers(app)
                app.include_router(users_router, prefix="/users")
                app.include_router(billing_router, prefix="/billing")
                return app
            ''',
        ),
    ],
    note="Application entry point that wires settings, the database and the routers together.",
)

_CONFIG = _module(
    "app/config.py",
    [
        _def(
            "class",
            "Settings",
            '''
            class Settings(BaseModel):
                """Environment-driven configuration for the whole service."""

                database_url: str
                smtp_host: str = "localhost"
                secret_key: str
                debug: bool = False
            ''',
        ),
        _def(
            "function",
            "get_settings",
            '''
            @lru_cache
            def get_settings() -> Settings:
                """Read the environment once and cache the parsed settings."""
                return Settings(**os.environ)
            ''',
        ),
    ],
    note="Typed configuration read from environment variables.",
)

_DB = _module(
    "app/db.py",
    [
        _def(
            "function",
            "init_engine",
            '''
            def init_engine(url: str) -> None:
                """Create the shared engine and session factory."""
                global _engine, _sessions
                _engine = create_engine(url, pool_pre_ping=True)
                _sessions = sessionmaker(bind=_engine)
            ''',
        ),
        _def(
            "function",
            "get_session",
            '''
            def get_session() -> Iterator[Session]:
                """Yield one database session per request and close it afterwards."""
                session = _sessions()
                try:
                    yield session
                finally:
                    session.close()
            ''',
        ),
    ],
    note="Database engine and the per-request session dependency.",
)

_DEPS = _module(
    "app/deps.py",
    [
        _def(
            "function",
            "get_current_user",
            '''
            def get_current_user(request: Request, session: Session = Depends(get_session)):
                """Resolve the bearer credential on the request into a user row."""
                claims = decode_token(request.headers["authorization"][7:])
                return session.get(User, claims["sub"])
            ''',
        ),
        _def(
            "function",
            "require_admin",
            '''
            def require_admin(user=Depends(get_current_user)):
                """Reject callers that are not administrators."""
                if not user.is_admin:
                    raise ApiError(403, "administrators only")
                return user
            ''',
        ),
    ],
    note="Request dependencies that turn a credential into the calling user.",
)

_ERRORS = _module(
    "app/errors.py",
    [
        _def(
            "class",
            "ApiError",
            '''
            class ApiError(Exception):
                """An error that maps directly onto an HTTP status and a message."""

                def __init__(self, status: int, detail: str) -> None:
                    super().__init__(detail)
                    self.status = status
                    self.detail = detail
            ''',
        ),
        _def(
            "function",
            "register_error_handlers",
            '''
            def register_error_handlers(app: FastAPI) -> None:
                """Turn ApiError into a JSON response with the right status."""

                @app.exception_handler(ApiError)
                async def _handle(_request, error: ApiError):
                    return JSONResponse({"detail": error.detail}, status_code=error.status)
            ''',
        ),
    ],
    note="Shared exception type and its HTTP translation.",
)

_AUTH_INIT = _module(
    "app/auth/__init__.py",
    [
        _def("import", "verify_password", "from app.auth.security import verify_password\n"),
        _def("import", "hash_password", "from app.auth.security import hash_password\n"),
        _def("import", "PasswordPolicy", "from app.auth.security import PasswordPolicy\n"),
        _def("import", "create_access_token", "from app.auth.tokens import create_access_token\n"),
        _def("import", "decode_token", "from app.auth.tokens import decode_token\n"),
    ],
)

_SECURITY = _module(
    "app/auth/security.py",
    [
        _def(
            "function",
            "verify_password",
            '''
            def verify_password(plain: str, hashed: bytes) -> bool:
                """Check a login attempt against the stored bcrypt hash."""
                return bcrypt.checkpw(plain.encode(), hashed)
            ''',
        ),
        _def(
            "function",
            "hash_password",
            '''
            def hash_password(plain: str) -> bytes:
                """Hash a new secret with bcrypt and a fresh salt."""
                return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12))
            ''',
        ),
        _def(
            "class",
            "PasswordPolicy",
            '''
            class PasswordPolicy:
                """Minimum strength a new secret has to meet before it is accepted."""

                min_length = 12
                require_digit = True
            ''',
        ),
    ],
    note="Secret hashing and the strength policy for new secrets.",
)

_TOKENS = _module(
    "app/auth/tokens.py",
    [
        _def(
            "function",
            "create_access_token",
            '''
            def create_access_token(user_id: str, ttl_minutes: int = 60) -> str:
                """Sign a short-lived bearer token for one user."""
                expires = utc_now() + timedelta(minutes=ttl_minutes)
                return jwt.encode({"sub": user_id, "exp": expires}, SECRET, algorithm="HS256")
            ''',
        ),
        _def(
            "function",
            "decode_token",
            '''
            def decode_token(token: str) -> dict:
                """Verify the signature and expiry of a bearer token and return its claims."""
                try:
                    return jwt.decode(token, SECRET, algorithms=["HS256"])
                except jwt.ExpiredSignatureError as error:
                    raise TokenExpired(str(error)) from error
            ''',
        ),
        _def(
            "class",
            "TokenExpired",
            '''
            class TokenExpired(Exception):
                """Raised when a bearer token is well formed but past its expiry."""
            ''',
        ),
    ],
    note="Issuing and verifying signed bearer tokens.",
)

_AUTH_ROUTES = _module(
    "app/auth/routes.py",
    [
        _def(
            "function",
            "login",
            '''
            @router.post("/login")
            def login(body: LoginBody, request: Request, session=Depends(get_session)):
                """Exchange an email and secret for a bearer token."""
                throttle.allow(request.client.host)
                user = getUserById(session, body.email)
                if user is None or not verify_password(body.secret, user.hashed):
                    raise ApiError(401, "invalid credentials")
                return {"token": create_access_token(str(user.id))}
            ''',
        ),
        _def(
            "function",
            "register",
            '''
            @router.post("/register")
            def register(body: RegisterBody, session=Depends(get_session)):
                """Create an account and return its first bearer token."""
                user = create_user(session, body.email, body.secret)
                return {"token": create_access_token(str(user.id))}
            ''',
        ),
        _def(
            "function",
            "refresh",
            '''
            @router.post("/refresh")
            def refresh(user=Depends(get_current_user)):
                """Issue a new bearer token for an already signed-in user."""
                return {"token": create_access_token(str(user.id))}
            ''',
        ),
    ],
    note="HTTP endpoints for signing in, registering and renewing a session.",
)

_USER_MODELS = _module(
    "app/users/models.py",
    [
        _def(
            "class",
            "User",
            '''
            class User(Base):
                """An account that can sign in."""

                __tablename__ = "users"
                id = Column(UUID, primary_key=True)
                email = Column(String, unique=True)
                hashed = Column(LargeBinary)
                is_admin = Column(Boolean, default=False)
            ''',
        ),
        _def(
            "class",
            "UserProfile",
            '''
            class UserProfile(Base):
                """Display details that belong to one user."""

                __tablename__ = "user_profiles"
                user_id = Column(UUID, ForeignKey("users.id"), primary_key=True)
                display_name = Column(String)
            ''',
        ),
    ],
    note="Database models for accounts and their profiles.",
)

_USER_SERVICE = _module(
    "app/users/service.py",
    [
        _def(
            "function",
            "getUserById",
            '''
            def getUserById(session, user_id):
                """Fetch one user by primary key, or None when there is no such row."""
                return session.get(User, user_id)
            ''',
        ),
        _def(
            "function",
            "get_user_by_email",
            '''
            def get_user_by_email(session, email):
                """Look an account up by its unique email address."""
                return session.query(User).filter(User.email == email.lower()).one_or_none()
            ''',
        ),
        _def(
            "function",
            "create_user",
            '''
            def create_user(session, email, secret):
                """Create an account, hashing the secret before it is stored."""
                user = User(email=email.lower(), hashed=hash_password(secret))
                session.add(user)
                session.flush()
                return user
            ''',
        ),
        _def(
            "function",
            "deactivate_user",
            '''
            def deactivate_user(session, user_id):
                """Mark an account as closed without deleting its history."""
                user = session.get(User, user_id)
                user.closed_at = utc_now()
            ''',
        ),
    ],
    note="Lookups and writes for user accounts.",
)

_USER_ROUTES = _module(
    "app/users/routes.py",
    [
        _def(
            "function",
            "list_users",
            '''
            @router.get("/")
            def list_users(page: PageParams = Depends(), session=Depends(get_session)):
                """Return one page of accounts, newest first."""
                throttle.allow("list-users")
                return paginate(session.query(User).order_by(User.created_at.desc()), page)
            ''',
        ),
        _def(
            "function",
            "show_user",
            '''
            @router.get("/{user_id}")
            def show_user(user_id: str, session=Depends(get_session)):
                """Return one account or a 404."""
                user = getUserById(session, user_id)
                if user is None:
                    raise ApiError(404, "no such user")
                return user
            ''',
        ),
        _def(
            "function",
            "update_user",
            '''
            @router.patch("/{user_id}")
            def update_user(user_id: str, body: UserPatch, user=Depends(get_current_user)):
                """Let a user edit their own display name."""
                if str(user.id) != user_id:
                    raise ApiError(403, "not your account")
                user.profile.display_name = body.display_name
                return user
            ''',
        ),
    ],
    note="HTTP endpoints for listing and editing accounts.",
)

_BILLING_MODELS = _module(
    "app/billing/models.py",
    [
        _def(
            "class",
            "Invoice",
            '''
            class Invoice(Base):
                """A bill sent to one account for one period."""

                __tablename__ = "invoices"
                id = Column(UUID, primary_key=True)
                account_id = Column(UUID, index=True)
                status = Column(String, default="draft")
            ''',
        ),
        _def(
            "class",
            "LineItem",
            '''
            class LineItem(Base):
                """One priced row on an invoice."""

                __tablename__ = "line_items"
                invoice_id = Column(UUID, ForeignKey("invoices.id"))
                unit_cents = Column(Integer)
                quantity = Column(Integer, default=1)
            ''',
        ),
    ],
    note="Billing tables: invoices and their line items.",
)

_PRICING = _module(
    "app/billing/pricing.py",
    [
        _def(
            "function",
            "compute_total",
            '''
            def compute_total(items):
                """Sum the quantity times unit price of every line, in cents."""
                return sum(item.unit_cents * item.quantity for item in items)
            ''',
        ),
        _def(
            "function",
            "apply_coupon",
            '''
            def apply_coupon(total_cents, coupon):
                """Reduce an amount by a percentage coupon, never below zero."""
                reduced = total_cents * (100 - coupon.percent) // 100
                return max(reduced, 0)
            ''',
        ),
        _def(
            "function",
            "format_discount",
            '''
            def format_discount(percent):
                """Render a coupon percentage as the text shown to customers."""
                return f"{percent}% off"
            ''',
        ),
    ],
    note="Totals and coupon arithmetic for billing.",
)

_INVOICE = _module(
    "app/billing/invoice.py",
    [
        _def(
            "function",
            "build_invoice",
            '''
            def build_invoice(session, account_id, items, coupon=None):
                """Price the items, apply any coupon and store the resulting invoice."""
                total = compute_total(items)
                if coupon is not None:
                    total = apply_coupon(total, coupon)
                invoice = Invoice(account_id=account_id, total_cents=total)
                session.add(invoice)
                return invoice
            ''',
        ),
        _def(
            "class",
            "InvoiceRenderer",
            '''
            class InvoiceRenderer:
                """Turns a stored invoice into the document a customer downloads."""

                def __init__(self, template_dir: str) -> None:
                    self.template_dir = template_dir
            ''',
        ),
        _def(
            "method",
            "render_pdf",
            '''
            def render_pdf(self, invoice) -> bytes:
                """Lay the invoice out as a PDF and return the file bytes."""
                html = self._env.get_template("invoice.html").render(invoice=invoice)
                return pdf_from_html(html)
            ''',
        ),
    ],
    note="Creating invoices and rendering them as downloadable documents.",
)

_BILLING_ROUTES = _module(
    "app/billing/routes.py",
    [
        _def(
            "function",
            "create_invoice_route",
            '''
            @router.post("/invoices")
            def create_invoice_route(body: InvoiceBody, user=Depends(get_current_user)):
                """Create a draft invoice for the signed-in account."""
                return build_invoice(session_of(user), user.id, body.items, body.coupon)
            ''',
        ),
        _def(
            "function",
            "get_invoice",
            '''
            @router.get("/invoices/{invoice_id}")
            def get_invoice(invoice_id: str, user=Depends(get_current_user)):
                """Return one of the caller's invoices."""
                return session_of(user).get(Invoice, invoice_id)
            ''',
        ),
    ],
    note="HTTP endpoints for creating and fetching invoices.",
)

_STATEMENTS = _module(
    "app/billing/statements.py",
    [
        _def(
            "function",
            "statement_period_bounds",
            '''
            def statement_period_bounds(year: int, month: int):
                """First and last instant of a calendar month in UTC."""
                start = datetime(year, month, 1, tzinfo=UTC)
                return start, (start + timedelta(days=32)).replace(day=1)
            ''',
        ),
        ("function", "rebuild_monthly_statements", _STATEMENTS_SOURCE + "\n", False),
    ],
    note="Monthly account statements assembled from charges.",
)

_WEBHOOKS = _module(
    "app/billing/webhooks.py",
    [
        _def(
            "function",
            "verify_signature",
            '''
            def verify_signature(payload: bytes, header: str) -> bool:
                """Check the provider's HMAC signature header in constant time."""
                expected = hmac.new(WEBHOOK_SECRET, payload, "sha256").hexdigest()
                return hmac.compare_digest(expected, header)
            ''',
        ),
        _def(
            "function",
            "handle_payment_webhook",
            '''
            @router.post("/webhooks/payment")
            async def handle_payment_webhook(request: Request):
                """Mark an invoice as paid when the provider reports a successful charge."""
                payload = await request.body()
                if not verify_signature(payload, request.headers["x-harbor-signature"]):
                    raise ApiError(400, "bad signature")
                event = json.loads(payload)
                if event["type"] == "charge.succeeded":
                    mark_paid(event["invoice"])
            ''',
        ),
    ],
    note="Receives and authenticates payment provider callbacks.",
)

_QUEUE = _module(
    "app/jobs/queue.py",
    [
        _def(
            "class",
            "JobQueue",
            '''
            class JobQueue:
                """A Redis-backed first-in first-out queue of background jobs."""

                def __init__(self, redis, name: str = "jobs") -> None:
                    self.redis = redis
                    self.name = name
            ''',
        ),
        _def(
            "method",
            "enqueue",
            '''
            def enqueue(self, kind: str, payload: dict) -> str:
                """Append a job and return its identifier."""
                job_id = uuid4().hex
                self.redis.rpush(self.name, json.dumps({"id": job_id, "kind": kind, **payload}))
                return job_id
            ''',
        ),
        _def(
            "method",
            "dequeue",
            '''
            def dequeue(self, timeout: int = 5):
                """Block for up to ``timeout`` seconds waiting for the next job."""
                item = self.redis.blpop(self.name, timeout=timeout)
                return json.loads(item[1]) if item else None
            ''',
        ),
    ],
    note="The job queue itself: enqueue and dequeue.",
)

_WORKER = _module(
    "app/jobs/worker.py",
    [
        _def(
            "function",
            "run_worker",
            '''
            def run_worker(queue: JobQueue) -> None:
                """Pull jobs forever and hand each one to process_job."""
                while True:
                    job = queue.dequeue()
                    if job is not None:
                        process_job(queue, job)
            ''',
        ),
        _def(
            "function",
            "process_job",
            '''
            def process_job(queue: JobQueue, job: dict) -> None:
                """Run one job; on failure put it back after a delay, up to the attempt cap."""
                try:
                    HANDLERS[job["kind"]](job)
                except Exception:
                    attempt = job.get("attempt", 0) + 1
                    if should_retry(attempt):
                        time.sleep(backoff_delay(attempt))
                        queue.enqueue(job["kind"], {**job, "attempt": attempt})
            ''',
        ),
    ],
    note="The worker loop that executes queued jobs.",
)

_SCHEDULER = _module(
    "app/jobs/scheduler.py",
    [
        _def(
            "function",
            "schedule_recurring",
            '''
            def schedule_recurring(queue: JobQueue, kind: str, cron: str) -> None:
                """Register a job that is enqueued every time the cron expression fires."""
                SCHEDULE.append((parse_cron(cron), kind, queue))
            ''',
        ),
        _def(
            "function",
            "parse_cron",
            '''
            def parse_cron(expression: str):
                """Split a five-field cron expression into minute, hour, day, month, weekday."""
                fields = expression.split()
                if len(fields) != 5:
                    raise ValueError("expected five cron fields")
                return fields
            ''',
        ),
    ],
    note="Recurring job registration from cron expressions.",
)

_RETRY = _module(
    "app/jobs/retry.py",
    [
        _def(
            "function",
            "backoff_delay",
            '''
            def backoff_delay(attempt: int) -> float:
                """Exponential backoff with jitter, doubling per attempt up to five minutes."""
                base = min(2**attempt, 300)
                return base * random.uniform(0.5, 1.0)
            ''',
        ),
        _def(
            "function",
            "should_retry",
            '''
            def should_retry(attempt: int, limit: int = 6) -> bool:
                """A failed job is retried until it has been attempted six times."""
                return attempt < limit
            ''',
        ),
    ],
    note="How long to wait before a failed job runs again, and when to give up.",
)

_EMAIL = _module(
    "app/notifications/email.py",
    [
        _def(
            "function",
            "send_email",
            '''
            def send_email(to: str, subject: str, html: str) -> None:
                """Deliver one message through the configured SMTP host."""
                message = EmailMessage()
                message["To"], message["Subject"] = to, subject
                message.set_content(html, subtype="html")
                with smtplib.SMTP(get_settings().smtp_host) as smtp:
                    smtp.send_message(message)
            ''',
        ),
    ],
    note="Outbound mail delivery over SMTP.",
)

_TEMPLATES = _module(
    "app/notifications/templates.py",
    [
        _def(
            "function",
            "welcome_email",
            '''
            def welcome_email(user) -> str:
                """The greeting sent to a new account holder."""
                return f"<h1>Welcome, {user.profile.display_name}</h1><p>Your account is ready.</p>"
            ''',
        ),
        _def(
            "function",
            "receipt_html",
            '''
            def receipt_html(order_ref: str, lines) -> str:
                """The message body confirming that a payment went through."""
                rows = "".join(f"<tr><td>{l.label}</td><td>{l.amount}</td></tr>" for l in lines)
                head = f"<h1>Thanks for your payment</h1><p>Reference {order_ref}</p>"
                return head + f"<table>{rows}</table>"
            ''',
        ),
    ],
    note="HTML bodies for welcome messages and payment receipts.",
)

_RATELIMIT = _module(
    "app/middleware/ratelimit.py",
    [
        _def(
            "class",
            "RateLimiter",
            '''
            class RateLimiter:
                """Reject clients that exceed the allowed number of requests per minute."""

                def __init__(self, per_minute: int = 60) -> None:
                    self.per_minute = per_minute
                    self.hits: dict[str, deque] = defaultdict(deque)
            ''',
        ),
        _def(
            "method",
            "allow",
            '''
            def allow(self, client: str) -> None:
                """Record a request; raise once the client has sent too many in the last minute."""
                now = time.monotonic()
                window = self.hits[client]
                while window and now - window[0] > 60:
                    window.popleft()
                if len(window) >= self.per_minute:
                    raise ApiError(429, "too many requests")
                window.append(now)
            ''',
        ),
        _def(
            "function",
            "check_rate_limit",
            '''
            def check_rate_limit(request: Request) -> None:
                """Middleware hook applying the shared limiter to the caller's address."""
                LIMITER.allow(request.client.host)
            ''',
        ),
    ],
    note="Sliding-window request throttling per client address.",
)

_REQUEST_LOG = _module(
    "app/middleware/logging.py",
    [
        _def(
            "function",
            "request_logger",
            '''
            async def request_logger(request: Request, call_next):
                """Log the method, path, status code and duration of every request."""
                started = time.perf_counter()
                response = await call_next(request)
                logger.info("%s %s %s %.1fms", request.method, request.url.path,
                            response.status_code, (time.perf_counter() - started) * 1000)
                return response
            ''',
        ),
    ],
    note="Structured access logging for every request.",
)

_DATES = _module(
    "app/utils/dates.py",
    [
        _def(
            "function",
            "utc_now",
            '''
            def utc_now() -> datetime:
                """The current time as a timezone-aware UTC datetime."""
                return datetime.now(UTC)
            ''',
        ),
        _def(
            "function",
            "parse_iso",
            '''
            def parse_iso(value: str) -> datetime:
                """Parse an ISO 8601 timestamp, assuming UTC when no offset is given."""
                parsed = datetime.fromisoformat(value)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            ''',
        ),
    ],
)

_PAGINATION = _module(
    "app/utils/pagination.py",
    [
        _def(
            "class",
            "PageParams",
            '''
            class PageParams(BaseModel):
                """The page number and size a list endpoint accepts."""

                page: int = 1
                size: int = Field(default=25, le=100)
            ''',
        ),
        _def(
            "function",
            "paginate",
            '''
            def paginate(query, params: PageParams):
                """Slice a query to one page and report the total row count."""
                total = query.count()
                rows = query.offset((params.page - 1) * params.size).limit(params.size).all()
                return {"total": total, "rows": rows}
            ''',
        ),
    ],
)

_TEST_PRICING = _module(
    "tests/test_pricing.py",
    [
        _def(
            "function",
            "test_coupon_never_goes_negative",
            """
            def test_coupon_never_goes_negative():
                assert apply_coupon(500, Coupon(percent=100)) == 0
                assert apply_coupon(500, Coupon(percent=40)) == 300
            """,
        ),
    ],
)

_TEST_AUTH = _module(
    "tests/test_auth.py",
    [
        _def(
            "function",
            "test_session_token_roundtrip",
            """
            def test_session_token_roundtrip():
                claims = decode_token(create_access_token("u-1", ttl_minutes=5))
                assert claims["sub"] == "u-1"
            """,
        ),
    ],
)

# Every file imports from the ones listed, by path. `app/auth/__init__.py` is the
# only barrel; `deps.py` and `tests/test_auth.py` reach `security.py` through it.
_IMPORTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("app/main.py", ("app/config.py", "app/db.py", "app/errors.py", "app/users/routes.py",
                     "app/billing/routes.py")),
    ("app/deps.py", ("app/auth/__init__.py", "app/db.py", "app/users/models.py",
                     "app/errors.py")),
    ("app/auth/__init__.py", ("app/auth/security.py", "app/auth/tokens.py")),
    ("app/auth/tokens.py", ("app/config.py", "app/utils/dates.py")),
    ("app/auth/routes.py", ("app/auth/security.py", "app/auth/tokens.py", "app/users/service.py",
                            "app/deps.py", "app/db.py", "app/errors.py",
                            "app/middleware/ratelimit.py")),
    ("app/users/service.py", ("app/users/models.py", "app/auth/security.py",
                              "app/utils/dates.py")),
    ("app/users/routes.py", ("app/deps.py", "app/users/service.py", "app/utils/pagination.py",
                             "app/errors.py", "app/db.py", "app/middleware/ratelimit.py")),
    ("app/billing/pricing.py", ("app/billing/models.py",)),
    ("app/billing/invoice.py", ("app/billing/models.py", "app/billing/pricing.py",
                                "app/utils/dates.py")),
    ("app/billing/routes.py", ("app/deps.py", "app/billing/invoice.py", "app/billing/models.py")),
    ("app/billing/statements.py", ("app/billing/models.py", "app/db.py", "app/utils/dates.py")),
    ("app/billing/webhooks.py", ("app/billing/models.py", "app/errors.py",
                                 "app/notifications/email.py")),
    ("app/jobs/worker.py", ("app/jobs/queue.py", "app/jobs/retry.py", "app/db.py")),
    ("app/jobs/scheduler.py", ("app/jobs/queue.py",)),
    ("app/notifications/email.py", ("app/config.py",)),
    ("app/notifications/templates.py", ("app/users/models.py",)),
    ("app/middleware/ratelimit.py", ("app/config.py", "app/errors.py")),
    ("tests/test_pricing.py", ("app/billing/pricing.py",)),
    ("tests/test_auth.py", ("app/auth/__init__.py",)),
)  # fmt: skip

_MODULES: tuple[FileSpec, ...] = (
    _MAIN, _CONFIG, _DB, _DEPS, _ERRORS, _AUTH_INIT, _SECURITY, _TOKENS, _AUTH_ROUTES,
    _USER_MODELS, _USER_SERVICE, _USER_ROUTES, _BILLING_MODELS, _PRICING, _INVOICE,
    _BILLING_ROUTES, _STATEMENTS, _WEBHOOKS, _QUEUE, _WORKER, _SCHEDULER, _RETRY, _EMAIL,
    _TEMPLATES, _RATELIMIT, _REQUEST_LOG, _DATES, _PAGINATION, _TEST_PRICING, _TEST_AUTH,
)  # fmt: skip


def _with_fan_in(
    modules: Sequence[FileSpec], imports: Sequence[tuple[str, Sequence[str]]]
) -> tuple[FileSpec, ...]:
    """Each module with ``fan_in`` set to the number of files that import it."""
    importers: dict[str, int] = {}
    for _, targets in imports:
        for target in targets:
            importers[target] = importers.get(target, 0) + 1
    return tuple(replace(module, fan_in=importers.get(module.path, 0)) for module in modules)


# --- history: commits, pull requests, README ---------------------------------------

_ALL_PATHS = tuple(module.path for module in _MODULES)

BCRYPT_COMMIT = _commit(
    "feat: switch password hashing to bcrypt",
    ["app/auth/security.py", "app/users/service.py"],
    "Grace Hopper",
)
DISCOUNT_COMMIT = _commit(
    "feat: add invoice totals and coupon discounts",
    ["app/billing/pricing.py", "app/billing/invoice.py", "app/billing/models.py"],
)
BULK_COMMIT = _commit(
    "style: reformat the whole repository",
    [*_ALL_PATHS, "pyproject.toml", "README.md", "Makefile", "docs/index.md", "alembic.ini"],
    "Linus Torvalds",
)

_COMMITS = (
    _commit(
        "feat: initial service skeleton",
        ["app/main.py", "app/config.py", "app/db.py", "app/errors.py", "app/deps.py"],
    ),
    BCRYPT_COMMIT,
    _commit("fix: reject expired bearer tokens", ["app/auth/tokens.py", "app/deps.py"]),
    DISCOUNT_COMMIT,
    # The first two commits that touch both of the next two files: one co-change pair.
    _commit(
        "feat: email a receipt when an invoice is paid",
        ["app/billing/invoice.py", "app/notifications/templates.py", "app/notifications/email.py"],
        "Grace Hopper",
    ),
    _commit(
        "fix: show the discount line on the receipt",
        ["app/billing/invoice.py", "app/notifications/templates.py"],
    ),
    _commit(
        "feat: sliding-window throttle on sign-in",
        [
            "app/middleware/ratelimit.py",
            "app/auth/tokens.py",
            "app/auth/routes.py",
            "app/config.py",
        ],
    ),
    _commit(
        "fix: throttle key uses the forwarded address",
        ["app/middleware/ratelimit.py", "app/auth/tokens.py"],
        "Linus Torvalds",
    ),
    _commit(
        "feat: retry failed jobs with exponential backoff",
        ["app/jobs/retry.py", "app/jobs/worker.py", "app/billing/webhooks.py"],
    ),
    _commit(
        "fix: cap the backoff and add jitter",
        ["app/jobs/retry.py", "app/billing/webhooks.py"],
        "Grace Hopper",
    ),
    _commit(
        "feat: monthly account statements",
        ["app/billing/statements.py", "app/billing/models.py"],
    ),
    BULK_COMMIT,
    _commit("chore: bump dependencies", ["pyproject.toml"]),
    _commit("feat: paginate the user list", ["app/users/routes.py", "app/utils/pagination.py"]),
    _commit(
        "feat: recurring jobs from cron expressions", ["app/jobs/scheduler.py", "app/jobs/queue.py"]
    ),
)

# The pairs `build_cochange` should derive from the commits above: two or more
# commits together, no bulk commit, no import between the two files.
EXPECTED_COCHANGE_PAIRS: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"app/billing/invoice.py", "app/notifications/templates.py"}),
        frozenset({"app/middleware/ratelimit.py", "app/auth/tokens.py"}),
        frozenset({"app/jobs/retry.py", "app/billing/webhooks.py"}),
    }
)

_PULL_REQUESTS = (
    _pull_request(
        12,
        "Switch password hashing to bcrypt",
        "Replaces sha1 hashing. hash_password and verify_password now use bcrypt with a "
        "per-user salt, and existing accounts are rehashed on their next sign-in.",
    ),
    _pull_request(
        13,
        "Add invoice discounts",
        "Adds apply_coupon and format_discount to the billing module so a percentage "
        "coupon can reduce an invoice total.",
    ),
    _pull_request(
        14,
        "Retry failed jobs with exponential backoff",
        "Jobs that raise are put back on the queue after a growing delay, six attempts at most.",
    ),
    _pull_request(
        15,
        "Throttle sign-in attempts",
        "Adds a sliding-window limiter keyed on the client address and applies it to login.",
    ),
    _pull_request(
        16,
        "Monthly account statements",
        "Adds statement generation that groups charges by currency for each billing period.",
    ),
)

README = """\
# Harbor

Harbor is a small web API with accounts, billing and background jobs.

## Installation

Install dependencies with `uv sync`, then copy `.env.example` to `.env` and fill in the
database URL and the secret key.

## Running the worker

Start the job worker in a second terminal with `python -m app.jobs.worker`. It reads the
`jobs` list in Redis, so Redis has to be running before the worker starts.

## Authentication

Sign in at `/auth/login` with an email and secret to receive a bearer token. Send it in the
`Authorization` header on every other request.

## Billing

Invoices are priced in cents. Payment providers report results to `/billing/webhooks/payment`.
"""

_DOCUMENTS = tuple(
    DocumentSpec(heading="", body="", chunk_text=chunk) for chunk in _build_readme_chunks(README)
)

RETRIEVAL_FIXTURE = RepoSpec(
    files=_with_fan_in(_MODULES, _IMPORTS),
    imports=tuple(
        ImportSpec(source=source, target=target)
        for source, targets in _IMPORTS
        for target in targets
    ),
    commits=_COMMITS,
    pull_requests=_PULL_REQUESTS,
    documents=_DOCUMENTS,
    derive_cochange=True,
    sparse_vectors=True,
    stable_ids=True,
)


# --- known-answer questions ---------------------------------------------------------


@dataclass(frozen=True)
class RetrievalQuestion:
    """A question about :data:`RETRIEVAL_FIXTURE` and what a good answer must cite.

    Attributes:
        id: A short name for failure messages.
        text: The question as a user would type it.
        gold: What the retrieved context must contain. A bare path means any
            chunk of that file; a ``C:``, ``PR:``, ``D:`` or ``F:`` string is a
            citation key and must match a candidate's key exactly.
        needs: The channel this question is designed to need, and why. This is
            the design intent; the recall test reports what actually happens.
    """

    id: str
    text: str
    gold: tuple[str, ...]
    needs: str


def matches_gold(candidate: Candidate, item: str) -> bool:
    """Whether a candidate satisfies one gold item (a file path or a citation key)."""
    if item.startswith(("C:", "PR:", "D:", "F:")):
        return candidate.key == item
    return candidate.file_path == item


RETRIEVAL_QUESTIONS: tuple[RetrievalQuestion, ...] = (
    RetrievalQuestion(
        id="exact-snake",
        text="Where is `verify_password` defined?",
        gold=("app/auth/security.py",),
        needs="symbol: the exact name. Lexical also matches the name in the chunk text.",
    ),
    RetrievalQuestion(
        id="exact-camel",
        text="Where is getUserById defined?",
        gold=("app/users/service.py",),
        needs="symbol: the exact camelCase name. Lexical matches it whole and split.",
    ),
    RetrievalQuestion(
        id="camel-in-words",
        text="get user by id",
        gold=("app/users/service.py",),
        needs="lexical: the index splits getUserById into words. Symbol finds no identifier here.",
    ),
    RetrievalQuestion(
        id="grep-long-function",
        text="Where is LEGACY_PRORATION_CUTOFF applied?",
        gold=("app/billing/statements.py",),
        needs=(
            "grep: the token appears only inside a function too long to be embedded, "
            "so no chunk holds it. Structural and the agent presets enable grep."
        ),
    ),
    RetrievalQuestion(
        id="graph-direct",
        text="What relies on RateLimiter?",
        gold=("app/auth/routes.py", "app/users/routes.py"),
        needs=(
            "graph: the class is found by name; its two importers never say 'rate' or "
            "'limiter' (they call it `throttle`)."
        ),
    ),
    RetrievalQuestion(
        id="graph-through-barrel",
        text="What relies on PasswordPolicy?",
        gold=("app/deps.py", "tests/test_auth.py"),
        needs=(
            "graph: both files reach security.py only through the auth/__init__.py barrel, "
            "and neither mentions passwords or policies."
        ),
    ),
    RetrievalQuestion(
        id="cochange",
        text="What else usually changes together with `backoff_delay`?",
        gold=("app/billing/webhooks.py",),
        needs=(
            "cochange: webhooks.py changed with retry.py in two commits, imports nothing "
            "from it, and shares no word with the question."
        ),
    ),
    RetrievalQuestion(
        id="history-why",
        text="Why was password hashing switched to bcrypt?",
        gold=("PR:12", commit_key(BCRYPT_COMMIT.hash)),
        needs=(
            "history: the answer is a PR and a commit. Lexical over all chunks can also "
            "reach them, so this tests the history channel's restriction rather than "
            "something only it can do."
        ),
    ),
    RetrievalQuestion(
        id="history-when",
        text="When did invoice discount support get added?",
        gold=("PR:13", commit_key(DISCOUNT_COMMIT.hash)),
        needs="history: the answer is a PR and a commit; lexical overlaps as above.",
    ),
    RetrievalQuestion(
        id="readme",
        text="How do I run the background worker locally?",
        gold=(document_key("Running the worker"),),
        needs="lexical: the README section is the only chunk about starting the worker.",
    ),
    RetrievalQuestion(
        id="plain-retry",
        text="How are failed jobs retried with backoff?",
        gold=("app/jobs/retry.py", "app/jobs/worker.py"),
        needs="lexical: plain-English behaviour; the docstrings carry the words.",
    ),
    RetrievalQuestion(
        id="plain-throttle",
        text="What stops a client from sending too many requests?",
        gold=("app/middleware/ratelimit.py",),
        needs="lexical: plain-English behaviour; the class docstring says it in these words.",
    ),
    RetrievalQuestion(
        id="plain-webhook",
        text="How do we verify the signature on payment webhooks?",
        gold=("app/billing/webhooks.py",),
        needs="lexical: plain-English behaviour; docstrings and the signature symbol.",
    ),
    RetrievalQuestion(
        id="plain-total",
        text="How is the invoice total computed?",
        gold=("app/billing/pricing.py",),
        needs=(
            "lexical: plain-English behaviour, and a known miss. The 'simple' text-search "
            "configuration does not stem 'computed' to 'compute', so the answer only matches "
            "on 'total' and lands just outside the top 10."
        ),
    ),
)


# --- seeds for the expansion channels -----------------------------------------


def file_seed(
    seeded: SeededRepo, path: str, *, fused_score: float | None = None, symbol: str | None = None
) -> Candidate:
    """A fused candidate standing for a file, as the first fusion pass would hand over.

    Args:
        seeded: The repository the file belongs to.
        path: The file's path.
        fused_score: The fused score, or ``None`` for an unscored seed.
        symbol: When given, the candidate is that symbol of the file rather than the file.
    """
    file = seeded.files[path]
    reference = SourceReference(
        source_type="symbol" if symbol else "file",
        chunk_text=symbol or path,
        file_path=path,
        symbol_name=symbol,
    )
    return Candidate(
        key=f"seed:{path}:{symbol}",
        reference=reference,
        text=reference.chunk_text,
        source_id=file.id,
        file_id=file.id,
        fused_score=fused_score,
    )


def non_file_seed(key: str = "C:abc123", *, fused_score: float | None = 1.0) -> Candidate:
    """A seed with no file, like a commit or a README section."""
    reference = SourceReference(source_type="commit", chunk_text="a commit", commit_hash="abc123")
    return Candidate(key=key, reference=reference, text="a commit", fused_score=fused_score)


# --- shared assertions -------------------------------------------------------


def assert_channel_contract(candidates, *, channel: str, variant: int, k: int) -> None:
    """Checks what every channel promises about its list, whatever it found.

    At most ``k`` candidates, one hit each for this channel and variant, ranks
    counting up from 1 with no gaps, and no repeated key.
    """
    assert len(candidates) <= k
    assert [c.channel_hits[0].rank for c in candidates] == list(range(1, len(candidates) + 1))
    for candidate in candidates:
        assert len(candidate.channel_hits) == 1
        hit = candidate.channel_hits[0]
        assert hit.channel == channel
        assert hit.variant == variant
    assert len({c.key for c in candidates}) == len(candidates)
