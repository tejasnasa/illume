"""Glossary selection: one entry per name, and no placeholder-named symbols.

``build_glossary`` writes one row per selected symbol, so it can emit several
rows for a name shared across files, and a row titled ``<anonymous>`` for a
symbol the parser could not name. Both are asserted here against a real
database and the shared OpenAI stub.

The sync session is a committed one, built the same way ``test_sync_llm.py``
builds it, because the builder takes a sync ``Session`` and the async
``db_session`` fixture's rows would not be visible to it.
"""

from __future__ import annotations

import itertools
import uuid

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.models.ast_symbol import AstSymbol
from app.models.file import File as FileModel
from app.models.glossary_entry import GlossaryEntry
from app.models.repository import Repository
from app.models.user import User
from app.services.glossary_builder import build_glossary
from tests.conftest import TEST_SYNC_DB_URL
from tests.fixtures import openai_stub
from tests.helpers import committed_repo_number_base

pytestmark = pytest.mark.integration

_repo_numbers = itertools.count(committed_repo_number_base(985_000))


@pytest.fixture
def stubbed_openai(monkeypatch):
    """The shared deterministic OpenAI stand-in."""
    return openai_stub.install(monkeypatch)


@pytest.fixture
def glossary_db(migrated_db):
    """A committed sync session plus a repository factory and teardown."""
    engine = create_engine(TEST_SYNC_DB_URL)
    session = sessionmaker(bind=engine)()
    created: list[Repository] = []

    def _make_repo() -> Repository:
        user = User(
            id=uuid.uuid4(),
            github_id=str(uuid.uuid4().int)[:20],
            email=f"glossary-{uuid.uuid4().int}@example.test",
            name="Glossary Builder Test User",
        )
        session.add(user)
        session.flush()
        repo = Repository(
            id=uuid.uuid4(),
            user_id=user.id,
            github_url=f"https://github.com/example/{uuid.uuid4().hex[:8]}",
            name=f"glossary-{uuid.uuid4().hex[:8]}",
            status="ready",
            ingested_branch="main",
            ingested_commit_sha="0" * 40,
            repo_number=next(_repo_numbers),
        )
        session.add(repo)
        session.commit()
        created.append(repo)
        return repo

    yield _make_repo, session

    session.execute(delete(Repository).where(Repository.id.in_([r.id for r in created])))
    session.execute(delete(User).where(User.id.in_([r.user_id for r in created])))
    session.commit()
    session.close()
    engine.dispose()


def _add_symbol(session, repo, *, path: str, name: str, fan_in: int = 0) -> None:
    """Insert one file containing one function symbol."""
    file = FileModel(
        repository_id=repo.id,
        path=path,
        language="python",
        loc=10,
        fan_in=fan_in,
        fan_out=0,
        has_tests=False,
    )
    session.add(file)
    session.flush()
    session.add(
        AstSymbol(
            file_id=file.id,
            kind="function",
            name=name,
            start_line=1,
            end_line=5,
            source_code=f"def {name}():\n    pass\n",
            cyclomatic_complexity=1,
        )
    )
    session.commit()


def _entries(session, repo) -> list[GlossaryEntry]:
    return list(
        session.execute(
            select(GlossaryEntry).where(GlossaryEntry.repository_id == repo.id)
        ).scalars()
    )


def _prompts(fake) -> str:
    """Every prompt the stub was asked to answer, as one string."""
    return "\n".join(str(call.get("input")) for call in fake.calls if call["kind"] == "responses")


class TestPlaceholderSymbols:
    def test_a_symbol_the_parser_could_not_name_is_never_selected(
        self, glossary_db, stubbed_openai
    ):
        """It outranks the real symbol, so it would be first without the filter."""
        make_repo, session = glossary_db
        repo = make_repo()
        _add_symbol(session, repo, path="src/a.py", name="<anonymous>", fan_in=99)
        _add_symbol(session, repo, path="src/b.py", name="real_name", fan_in=1)

        created = build_glossary(session, repo)

        assert created == 1
        assert {entry.name for entry in _entries(session, repo)} == {"real_name"}
        # Not merely absent from the table -- never sent to the model at all.
        assert "<anonymous>" not in _prompts(stubbed_openai)


class TestOneEntryPerName:
    def test_same_named_symbols_collapse_to_the_highest_fan_in_site(
        self, glossary_db, stubbed_openai
    ):
        make_repo, session = glossary_db
        repo = make_repo()
        _add_symbol(session, repo, path="src/low.py", name="__init__", fan_in=1)
        _add_symbol(session, repo, path="src/high.py", name="__init__", fan_in=50)
        _add_symbol(session, repo, path="src/mid.py", name="__init__", fan_in=10)

        created = build_glossary(session, repo)

        entries = _entries(session, repo)
        assert created == 1
        assert len(entries) == 1
        assert entries[0].file_path == "src/high.py"
        # The name reached the prompt once, so the model's name-keyed reply
        # cannot collapse three symbols onto one shared definition.
        assert _prompts(stubbed_openai).count("Name: __init__") == 1


class TestIncremental:
    def test_a_new_symbol_sharing_a_stored_name_is_not_defined_again(
        self, glossary_db, stubbed_openai
    ):
        """The anti-join matches on name, not only on ``symbol_id``."""
        make_repo, session = glossary_db
        repo = make_repo()
        _add_symbol(session, repo, path="src/one.py", name="handler", fan_in=5)
        assert build_glossary(session, repo) == 1

        # A different file gains a same-named symbol and outranks the original.
        _add_symbol(session, repo, path="src/two.py", name="handler", fan_in=99)
        stubbed_openai.calls.clear()

        created = build_glossary(session, repo, mode="incremental")

        assert created == 0
        entries = _entries(session, repo)
        assert len(entries) == 1
        assert entries[0].file_path == "src/one.py"
        assert _prompts(stubbed_openai) == ""

    def test_a_genuinely_new_name_is_still_defined(self, glossary_db, stubbed_openai):
        """The counterweight: the name filter must not suppress new terms."""
        make_repo, session = glossary_db
        repo = make_repo()
        _add_symbol(session, repo, path="src/one.py", name="handler", fan_in=5)
        assert build_glossary(session, repo) == 1

        _add_symbol(session, repo, path="src/two.py", name="fresh_name", fan_in=99)

        created = build_glossary(session, repo, mode="incremental")

        assert created == 1
        assert {entry.name for entry in _entries(session, repo)} == {"handler", "fresh_name"}
