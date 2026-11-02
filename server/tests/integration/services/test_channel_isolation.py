"""No channel returns another repository's rows, even when paths and names are identical.

Both repositories are seeded from the same spec, so they share every path and
every symbol name and differ only in ids. A channel that joined on a path or a
name instead of ``file_id`` and ``repository_id`` would return the other copy.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.retrieval.candidate import QueryVariant
from app.services.retrieval.channels import get_channel, get_expansion_channel
from app.services.retrieval.config import (
    CochangeChannel,
    DenseChannel,
    GraphChannel,
    GrepChannel,
    HistoryChannel,
    LexicalChannel,
    SymbolChannel,
)
from tests.factories import make_user
from tests.fixtures.retrieval import (
    DEFAULT_SPEC,
    CochangeSpec,
    ImportSpec,
    file_seed,
    make_context,
    render_symbol_chunk,
    seed_repo,
)

pytestmark = pytest.mark.integration

_VERIFY_CHUNK = render_symbol_chunk("app/auth/security.py", DEFAULT_SPEC.files[0].symbols[0])

# (channel kind, spec, query text, a path the answer must come from)
CASES = [
    ("dense", DenseChannel(max_distance=0.1), _VERIFY_CHUNK, "app/auth/security.py"),
    ("lexical", LexicalChannel(), "bcrypt checkpw verify_password", "app/auth/security.py"),
    ("symbol", SymbolChannel(), "where is getUserById", "app/users/service.py"),
    ("grep", GrepChannel(), "who uses `bcrypt.checkpw`", "app/auth/security.py"),
    ("history", HistoryChannel(), "switch password hashing to bcrypt", None),
]


@pytest.mark.parametrize(("kind", "spec", "query", "path"), CASES, ids=[c[0] for c in CASES])
@pytest.mark.parametrize("asked_about", ["first", "second"])
async def test_a_channel_never_returns_the_other_repository(
    db_session, kind, spec, query, path, asked_about
):
    user = await make_user(db_session)
    first = await seed_repo(db_session, user, name="first")
    second = await seed_repo(db_session, user, name="second")
    asked, other = (first, second) if asked_about == "first" else (second, first)

    found = await get_channel(kind).search(
        make_context(db_session, asked.repo), QueryVariant(query), spec
    )

    # An empty list would pass the checks below trivially.
    assert found, f"{kind} found nothing for {query!r}"
    if path is not None:
        assert found[0].file_path == path
    for candidate in found:
        assert candidate.source_id in asked.source_ids()
        assert candidate.source_id not in other.source_ids()
        if candidate.file_id is not None:
            assert candidate.file_id in asked.file_ids()
            assert candidate.file_id not in other.file_ids()


async def test_the_other_repository_is_found_when_asked_about_directly(db_session):
    """The fixture really has two searchable copies, so the tests above are not vacuous."""
    user = await make_user(db_session)
    first = await seed_repo(db_session, user, name="first")
    second = await seed_repo(db_session, user, name="second")

    one = await get_channel("symbol").search(
        make_context(db_session, first.repo), QueryVariant("verify_password"), SymbolChannel()
    )
    two = await get_channel("symbol").search(
        make_context(db_session, second.repo), QueryVariant("verify_password"), SymbolChannel()
    )

    assert one[0].key == two[0].key
    assert one[0].source_id == first.symbol_named("verify_password").id
    assert two[0].source_id == second.symbol_named("verify_password").id


SECURITY = "app/auth/security.py"
SERVICE = "app/users/service.py"
ROUTES = "app/users/routes.py"

LINKED_SPEC = replace(
    DEFAULT_SPEC,
    imports=(ImportSpec(ROUTES, SERVICE), ImportSpec(SERVICE, SECURITY)),
    cochange=(CochangeSpec(SERVICE, SECURITY), CochangeSpec(SERVICE, ROUTES)),
)

EXPANSIONS = [("graph", GraphChannel()), ("cochange", CochangeChannel())]


@pytest.mark.parametrize(("kind", "spec"), EXPANSIONS, ids=[e[0] for e in EXPANSIONS])
@pytest.mark.parametrize("asked_about", ["first", "second"])
async def test_an_expansion_channel_never_returns_the_other_repository(
    db_session, kind, spec, asked_about
):
    user = await make_user(db_session)
    first = await seed_repo(db_session, user, LINKED_SPEC, name="first")
    second = await seed_repo(db_session, user, LINKED_SPEC, name="second")
    asked, other = (first, second) if asked_about == "first" else (second, first)

    found = await get_expansion_channel(kind).expand(
        make_context(db_session, asked.repo), [file_seed(asked, SERVICE, fused_score=1.0)], spec
    )

    # Both copies have the same paths, so an empty list would pass trivially.
    assert {c.file_path for c in found} == {SECURITY, ROUTES}
    for candidate in found:
        assert candidate.file_id in asked.file_ids()
        assert candidate.file_id not in other.file_ids()
        assert candidate.source_id not in other.source_ids()


@pytest.mark.parametrize(("kind", "spec"), EXPANSIONS, ids=[e[0] for e in EXPANSIONS])
async def test_seeds_from_another_repository_expand_nothing(db_session, kind, spec):
    user = await make_user(db_session)
    first = await seed_repo(db_session, user, LINKED_SPEC, name="first")
    second = await seed_repo(db_session, user, LINKED_SPEC, name="second")

    # The seed belongs to the second repository but the context to the first.
    found = await get_expansion_channel(kind).expand(
        make_context(db_session, first.repo), [file_seed(second, SERVICE, fused_score=1.0)], spec
    )

    assert found == []
