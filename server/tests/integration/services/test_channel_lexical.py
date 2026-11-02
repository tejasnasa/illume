"""The lexical channel: full-text search that matches identifiers whole and as words."""

from __future__ import annotations

import pytest

from app.services.retrieval.candidate import QueryVariant
from app.services.retrieval.channels import get_channel
from app.services.retrieval.config import LexicalChannel
from tests.factories import make_user
from tests.fixtures.retrieval import assert_channel_contract, make_context, seed_repo

pytestmark = pytest.mark.integration


async def _search(db, seeded, text, spec=None, **variant):
    ctx = make_context(db, seeded.repo)
    return await get_channel("lexical").search(
        ctx, QueryVariant(text, **variant), spec or LexicalChannel()
    )


async def test_a_question_finds_the_chunk_naming_the_identifier(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    found = await _search(db_session, seeded, "where is getUserById defined")

    assert found[0].reference.symbol_name == "getUserById"
    assert found[0].reference.file_path == "app/users/service.py"
    assert_channel_contract(found, channel="lexical", variant=0, k=50)


async def test_the_whole_identifier_and_its_words_both_match(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    whole = await _search(db_session, seeded, "getUserById")
    words = await _search(db_session, seeded, "get user by id")

    assert whole[0].reference.symbol_name == "getUserById"
    assert "getUserById" in {c.reference.symbol_name for c in words}


async def test_snake_case_matches_as_words(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    found = await _search(db_session, seeded, "hash password")

    assert "hash_password" in {c.reference.symbol_name for c in found}


async def test_it_covers_commits_and_pull_requests(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    found = await _search(db_session, seeded, "bcrypt sha1 hashing")

    assert found[0].reference.pr_number == 12
    assert found[0].provenance == "history"


async def test_a_question_of_only_stop_words_finds_nothing(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    assert await _search(db_session, seeded, "what is the where of a how") == []


async def test_a_term_the_repository_never_mentions_finds_nothing(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    assert await _search(db_session, seeded, "xylophone") == []


async def test_k_limits_the_list_and_ranks_start_at_one(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    found = await _search(db_session, seeded, "password user", LexicalChannel(k=2), index=3)

    assert len(found) == 2
    assert_channel_contract(found, channel="lexical", variant=3, k=2)


async def test_hyde_text_is_left_to_the_dense_channel(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    assert await _search(db_session, seeded, "bcrypt checkpw", kind="hyde") == []


async def test_punctuation_in_the_query_cannot_break_the_tsquery(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    found = await _search(db_session, seeded, "bcrypt & (!checkpw) | 'x' :* <-> ;--")

    assert found
