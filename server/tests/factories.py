"""Row builders for tests.

Direct inserts rather than HTTP calls: a test about, say, graph rendering should not
depend on the registration endpoint working. When a test *is* about registration, it
calls the endpoint.

Everything here writes through the caller's session, which `db_session` rolls back, so
rows never outlive the test that created them.
"""

import itertools
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.ast_symbol import AstSymbol
from app.models.chat_message import ChatMessage
from app.models.code_owner import CodeOwner
from app.models.dependency import Dependency
from app.models.embedding import Embedding
from app.models.file import File
from app.models.glossary_entry import GlossaryEntry
from app.models.onboarding_guide import OnboardingGuide
from app.models.repository import Repository
from app.models.user import User
from tests.fixtures.openai_stub import RETRIEVABLE_VECTOR
from tests.helpers import committed_repo_number_base

_counter = itertools.count(1)

# Distinguishes "caller said nothing, use the default" from "caller explicitly wants
# NULL". A `None` default cannot express both, and several columns here are nullable in
# ways the endpoints have to handle.
UNSET: Any = object()

# Separate counter for repo_number. Starts high so a value never collides with a real
# row in a developer's database if the suite is ever pointed at one by mistake, and
# offset per xdist worker so two workers cannot allocate the same number -- see
# `committed_repo_number_base`.
#
# The E2E seed shares this database (both suites point at `illume_test`) and leaves its
# rows behind on purpose, so the two ranges must not overlap: the seed uses 800_000+ and
# passes an explicit number. A collision here surfaces as a `UniqueViolationError` in an
# unrelated test, several minutes into a run.
_repo_number = itertools.count(committed_repo_number_base(900_000))


def unique_email(prefix: str = "user") -> str:
    """
    An email no other test in this session will have used.

    Uses a real TLD deliberately. `email-validator` (behind pydantic's `EmailStr`)
    rejects the reserved special-use domains -- `.test`, `.example`, `.invalid`,
    `.localhost` -- unless it is constructed in test mode, which the app does not do. A
    `@example.test` address posts fine to a direct-insert factory but fails request
    validation with a 422.
    """
    return f"{prefix}-{next(_counter)}-{uuid.uuid4().hex[:8]}@example.com"


async def make_user(
    db: AsyncSession,
    *,
    email: str | None = None,
    name: str = "Test User",
    password: str = "correct horse battery staple",
    github_access_token: str | None = None,
    github_id: str | None = None,
    avatar_url: str | None = None,
) -> User:
    """Insert a user and return it, flushed so `user.id` is populated."""
    user = User(
        email=email or unique_email(),
        name=name,
        password=hash_password(password),
        github_access_token=github_access_token,
        github_id=github_id,
        avatar_url=avatar_url,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def make_repo(
    db: AsyncSession,
    user: User,
    *,
    name: str = "example-repo",
    github_url: str = "https://github.com/example/example-repo",
    status: str = "ready",
    primary_language: str = "python",
    default_branch: str = "main",
    repo_number: int | None = None,
) -> Repository:
    """
    Insert a repository owned by `user`.

    `repo_number` is supplied explicitly. The model declares it as `Identity()`, so the
    ORM omits it and expects the database to generate one -- but no migration ever
    created a generator for the column, so omitting it violates NOT NULL. That defect is
    deliberately being left alone; supplying the value keeps direct inserts working so the
    read/update/delete routes can still be tested.

    Pass `repo_number` explicitly to control the value -- the E2E seed does, to stay out of
    the counter's range.
    """
    repo = Repository(
        user_id=user.id,
        github_url=github_url,
        name=name,
        status=status,
        primary_language=primary_language,
        default_branch=default_branch,
        ingested_branch=default_branch,
        ingested_commit_sha="0" * 40,
        repo_number=repo_number if repo_number is not None else next(_repo_number),
    )
    db.add(repo)
    await db.flush()
    await db.refresh(repo)
    return repo


async def make_file(
    db: AsyncSession,
    repo: Repository,
    *,
    path: str,
    language: str = "python",
    loc: int = 10,
    fan_in: int = 0,
    fan_out: int = 0,
    criticality: str | None = "safe",
    has_tests: bool = False,
) -> File:
    """Insert a File row belonging to `repo`."""
    file = File(
        repository_id=repo.id,
        path=path,
        language=language,
        loc=loc,
        fan_in=fan_in,
        fan_out=fan_out,
        criticality=criticality,
        has_tests=has_tests,
    )
    db.add(file)
    await db.flush()
    await db.refresh(file)
    return file


async def make_symbol(
    db: AsyncSession,
    file: File,
    *,
    name: str,
    kind: str = "function",
    start_line: int = 1,
    end_line: int = 5,
    source_code: str = "def f():\n    pass\n",
    cyclomatic_complexity: int = 1,
) -> AstSymbol:
    """Insert an AstSymbol row belonging to `file`."""
    symbol = AstSymbol(
        file_id=file.id,
        kind=kind,
        name=name,
        start_line=start_line,
        end_line=end_line,
        source_code=source_code,
        cyclomatic_complexity=cyclomatic_complexity,
    )
    db.add(symbol)
    await db.flush()
    await db.refresh(symbol)
    return symbol


async def make_dependency(
    db: AsyncSession,
    source: AstSymbol,
    target: AstSymbol,
    *,
    dep_type: str = "imports",
) -> Dependency:
    """Insert a Dependency edge between two symbols."""
    dependency = Dependency(
        source_symbol_id=source.id,
        target_symbol_id=target.id,
        dep_type=dep_type,
    )
    db.add(dependency)
    await db.flush()
    return dependency


async def make_glossary_entry(
    db: AsyncSession,
    repo: Repository,
    *,
    name: str,
    definition: str = "A thing the codebase does.",
    file_path: str | None = "src/module_0.py",
    line_number: int | None = 1,
    symbol_id: uuid.UUID | None = None,
) -> GlossaryEntry:
    """Insert a glossary term belonging to `repo`."""
    entry = GlossaryEntry(
        repository_id=repo.id,
        name=name,
        definition=definition,
        file_path=file_path,
        line_number=line_number,
        symbol_id=symbol_id,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return entry


async def make_code_owner(
    db: AsyncSession,
    file: File,
    *,
    primary_owner: str = "Ada Lovelace",
    contributors: Any = UNSET,
    bus_factor: int = 1,
    is_knowledge_silo: bool = False,
) -> CodeOwner:
    """
    Insert an ownership record for `file`.

    `file_id` is unique on the table, so each file gets at most one.

    `contributors` defaults to a single 100% entry for `primary_owner`. Pass an explicit
    `None` to store SQL NULL, which is a real state the column allows and the endpoint
    has to cope with -- hence the sentinel rather than `None` as the default.
    """
    owner = CodeOwner(
        file_id=file.id,
        primary_owner=primary_owner,
        contributors=(
            [{"name": primary_owner, "email": "ada@example.com", "percentage": 100.0}]
            if contributors is UNSET
            else contributors
        ),
        bus_factor=bus_factor,
        is_knowledge_silo=is_knowledge_silo,
    )
    db.add(owner)
    await db.flush()
    await db.refresh(owner)
    return owner


async def make_guide(
    db: AsyncSession,
    repo: Repository,
    *,
    reading_order: list[dict] | None = None,
    critical_files: list[dict] | None = None,
    architecture_brief: dict | None = None,
    pdf_path: str | None = None,
) -> OnboardingGuide:
    """
    Insert the onboarding guide for `repo`.

    `repository_id` is unique, so a repo has at most one guide.

    The `reading_order` and `critical_files` dicts are stored as JSONB and re-read by
    `app/api/v1/guide.py`, which expects a **`path`** key on each entry -- not
    `file_path`, which is what the API *returns*. A wrong key is not an error anywhere;
    it produces an entry with an empty path that silently matches no graph node.
    """
    guide = OnboardingGuide(
        repository_id=repo.id,
        reading_order=reading_order,
        critical_files=critical_files,
        architecture_brief=architecture_brief,
        pdf_path=pdf_path,
    )
    db.add(guide)
    await db.flush()
    await db.refresh(guide)
    return guide


async def make_chat_message(
    db: AsyncSession,
    repo: Repository,
    user: User,
    *,
    question: str = "What does this do?",
    answer: str = "It does the thing.",
    sources: list[dict] | None = None,
) -> ChatMessage:
    """
    Insert one persisted chat turn.

    `created_at` is server-generated, and the history endpoint orders on it, so tests
    that care about ordering insert in sequence and rely on `now()` advancing.
    """
    message = ChatMessage(
        repository_id=repo.id,
        user_id=user.id,
        question=question,
        answer=answer,
        sources=sources,
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)
    return message


def fake_vector(seed: float = 0.0, dimensions: int = 1536) -> list[float]:
    """
    A deterministic unit-ish vector for the pgvector column.

    All values equal, so cosine distance between two such vectors is the same
    regardless of index -- fine for exercising storage and the distance operator, not
    for asserting anything about ranking.
    """
    return [seed] * dimensions


async def make_embedding(
    db: AsyncSession,
    repo: Repository,
    *,
    source_id: uuid.UUID | None = None,
    source_type: str = "symbol",
    chunk_text: str = "def f(): pass",
    file_id: uuid.UUID | None = None,
    vector: list[float] | None = None,
) -> Embedding:
    """Insert one embedding row for `repo`."""
    embedding = Embedding(
        repository_id=repo.id,
        source_id=source_id or uuid.uuid4(),
        source_type=source_type,
        chunk_text=chunk_text,
        file_id=file_id,
        embedding=vector if vector is not None else fake_vector(),
    )
    db.add(embedding)
    await db.flush()
    await db.refresh(embedding)
    return embedding


async def make_ingested_repo(
    db: AsyncSession,
    user: User,
    *,
    name: str = "ingested-repo",
    file_count: int = 3,
    repo_number: int | None = None,
) -> tuple[Repository, list[File]]:
    """
    A repository populated the way a completed ingestion would leave it.

    Rows are inserted directly rather than driven through the pipeline: tests about
    reading a graph, a guide, or a glossary should not depend on the ingestion task
    working. The pipeline itself is covered separately, eagerly.

    Each file gets one symbol, and each file imports the next, so the graph has a
    deterministic chain shape: file 0 -> 1 -> 2.
    """
    repo = await make_repo(db, user, name=name, repo_number=repo_number)

    files: list[File] = []
    symbols: list[AstSymbol] = []
    for index in range(file_count):
        file = await make_file(
            db,
            repo,
            path=f"src/module_{index}.py",
            fan_in=1 if index > 0 else 0,
            fan_out=1 if index < file_count - 1 else 0,
        )
        files.append(file)
        symbols.append(
            await make_symbol(
                db,
                file,
                name=f"func_{index}",
                start_line=1,
                end_line=10 + index,
            )
        )

    for index in range(file_count - 1):
        await make_dependency(db, symbols[index], symbols[index + 1])

    await db.flush()
    return repo, files


async def make_fully_ingested_repo(
    db: AsyncSession,
    user: User,
    *,
    name: str = "ingested-repo",
    file_count: int = 3,
    repo_number: int | None = None,
) -> tuple[Repository, list[File]]:
    """
    A repository populated the way a *completed* ingestion leaves it, in full.

    `make_ingested_repo` covers the graph half -- files, symbols, and the dependency
    edges between them -- and stops there. This adds the rows the other pages read:
    glossary terms, code ownership, the onboarding guide, embeddings, and one persisted
    chat turn.

    It exists for the E2E seed (`scripts/seed_e2e.py`), which needs a repository every
    route can render. It builds on `make_ingested_repo` rather than duplicating it so
    there is still one definition of what the graph half looks like.
    """
    repo, files = await make_ingested_repo(
        db, user, name=name, file_count=file_count, repo_number=repo_number
    )

    # `architecture_summary` is a column on the repository, not part of the guide, and it
    # is what the overview page's "AI Architecture Overview" section renders. Without it
    # the page says "No architecture summary generated." even though the guide has a
    # brief -- two different fields that read alike.
    repo.architecture_summary = (
        "A small fixture repository used by the end-to-end suite. "
        "It contains a chain of modules, each importing the next."
    )

    for index, file in enumerate(files):
        file_name = file.path.rsplit("/", 1)[-1]
        await make_glossary_entry(
            db,
            repo,
            name=f"func_{index}",
            definition=f"Function number {index}, in {file_name}.",
            file_path=file.path,
            line_number=1,
        )
        await make_code_owner(
            db,
            file,
            primary_owner="Ada Lovelace",
            contributors=[
                {"name": "Ada Lovelace", "email": "ada@example.com", "percentage": 80.0},
                {"name": "Grace Hopper", "email": "grace@example.com", "percentage": 20.0},
            ],
            bus_factor=2,
        )
        await make_embedding(
            db,
            repo,
            source_type="symbol",
            chunk_text=f"file: {file.path}\nkind: function\nname: func_{index}",
            file_id=file.id,
        )

    await make_embedding(
        db,
        repo,
        source_type="commit",
        chunk_text="a1b2c3d | Ada Lovelace | feat: add module_0",
        vector=RETRIEVABLE_VECTOR,
    )

    await make_guide(
        db,
        repo,
        # The stored JSON uses `path`, not `file_path`: `onboarding.build_reading_order`
        # writes `{"path": f.path, ...}` and `guide._parse_reading_order` reads
        # `entry.get("path", "")`. `file_path` is the *response* field name, so seeding
        # with it yields an empty path and a reading order that silently joins to nothing.
        reading_order=[
            {"position": 1, "path": files[0].path, "annotation": "Start here.", "fan_in": 0},
            {"position": 2, "path": files[-1].path, "annotation": "Then this.", "fan_in": 1},
        ],
        critical_files=[{"path": files[0].path, "criticality": "critical", "reasons": []}],
        architecture_brief={"overview": "A small fixture repository."},
    )

    await make_chat_message(
        db,
        repo,
        user,
        question="What does func_0 do?",
        answer="It is the first function in the fixture.",
        sources=[
            {
                "source_type": "symbol",
                "chunk_text": f"file: {files[0].path}\nkind: function\nname: func_0",
                "file_path": files[0].path,
                "symbol_name": "func_0",
                "start_line": 1,
                "end_line": 10,
                "commit_hash": None,
                "author_name": None,
                "pr_number": None,
                "pr_title": None,
            }
        ],
    )

    await db.commit()
    return repo, files
