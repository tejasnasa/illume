"""Grep over stored symbol bodies: the reusable function, and the channel built on it.

A timeout or an invalid pattern aborts a Postgres transaction. The request's
session is shared, so every refusal here is followed by a normal query on the
same session to show the savepoint contained the failure.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from sqlalchemy import select, text

from app.models import AstSymbol
from app.services.retrieval.candidate import QueryVariant
from app.services.retrieval.channels import get_channel
from app.services.retrieval.channels.grep import MAX_PATTERN_LENGTH, grep_symbols
from app.services.retrieval.config import GrepChannel
from tests.factories import make_file, make_repo, make_symbol, make_user
from tests.fixtures.retrieval import assert_channel_contract, make_context, seed_repo

pytestmark = pytest.mark.integration

# Backreferences make Postgres's regex engine backtrack; plain nested quantifiers
# such as ``(a+)+$`` finish at once, because the engine is automaton-based.
EXPENSIVE_REGEX = r"^(.*)(.*)(.*)(.*)(.*)\1\2\3\4\5$"


async def _assert_session_usable(db) -> None:
    await db.execute(select(AstSymbol.id).limit(1))
    assert (await db.execute(text("SELECT 1"))).scalar_one() == 1
    assert (await db.execute(text("SHOW statement_timeout"))).scalar_one() in {"0", "0ms"}


async def test_a_literal_match_reports_lines_with_file_line_numbers(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    result = await grep_symbols(db_session, seeded.repo.id, "bcrypt.checkpw", regex=False)

    assert result.ok
    assert result.total_symbols == 1
    assert not result.truncated
    (match,) = result.matches
    assert match.path == "app/auth/security.py"
    # verify_password starts at line 10; the call is on its third line.
    assert match.line == 12
    assert match.text == "    return bcrypt.checkpw(plain, hashed)"
    assert match.symbol_name == "verify_password"
    assert match.symbol_id == seeded.symbol_named("verify_password").id


async def test_every_matching_line_of_a_symbol_is_reported(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    result = await grep_symbols(db_session, seeded.repo.id, "plain", regex=False)

    lines = {(m.symbol_name, m.line) for m in result.matches}
    assert lines == {
        ("verify_password", 10),
        ("verify_password", 12),
        ("hash_password", 20),
        ("hash_password", 21),
    }
    assert result.total_symbols == 2


async def test_percent_and_underscore_are_matched_literally(db_session):
    user = await make_user(db_session)
    repo = await make_repo(db_session, user)
    file = await make_file(db_session, repo, path="a.py")
    await make_symbol(
        db_session, file, name="literal", source_code='label = "50% off"\nuser_id = 1\n'
    )
    await make_symbol(
        db_session, file, name="decoy", source_code='label = "50 dollars off"\nuserXid = 1\n'
    )

    percent = await grep_symbols(db_session, repo.id, "50% off", regex=False)
    wildcard_percent = await grep_symbols(db_session, repo.id, "50%off", regex=False)
    underscore = await grep_symbols(db_session, repo.id, "user_id", regex=False)
    backslash = await grep_symbols(db_session, repo.id, "\\", regex=False)

    assert {m.symbol_name for m in percent.matches} == {"literal"}
    assert wildcard_percent.matches == ()
    assert {m.symbol_name for m in underscore.matches} == {"literal"}
    assert backslash.matches == ()


async def test_regex_mode_uses_the_pattern_as_a_regex(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    result = await grep_symbols(db_session, seeded.repo.id, r"bcrypt\.(check|hash)pw", regex=True)

    assert {m.symbol_name for m in result.matches} == {"verify_password", "hash_password"}
    assert result.total_symbols == 2
    literal = await grep_symbols(db_session, seeded.repo.id, r"bcrypt\.(check|hash)pw", regex=False)
    assert literal.matches == ()


async def test_a_pattern_over_the_length_cap_is_refused(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    result = await grep_symbols(
        db_session, seeded.repo.id, "a" * (MAX_PATTERN_LENGTH + 1), regex=False
    )

    assert not result.ok
    assert result.refusal.reason == "pattern_too_long"
    assert str(MAX_PATTERN_LENGTH) in result.refusal.message
    assert result.matches == ()
    exact = await grep_symbols(db_session, seeded.repo.id, "a" * MAX_PATTERN_LENGTH, regex=False)
    assert exact.ok


async def test_an_empty_pattern_is_refused(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    result = await grep_symbols(db_session, seeded.repo.id, "", regex=False)

    assert result.refusal is not None and result.refusal.reason == "empty_pattern"


async def test_an_invalid_regex_is_refused_and_the_session_survives(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    result = await grep_symbols(db_session, seeded.repo.id, "foo(", regex=True)

    assert not result.ok
    assert result.refusal.reason == "invalid_regex"
    assert "regular expression" in result.refusal.message
    await _assert_session_usable(db_session)
    again = await grep_symbols(db_session, seeded.repo.id, "bcrypt", regex=True)
    assert again.ok and again.total_symbols == 2


async def test_an_expensive_pattern_times_out_and_the_session_survives(db_session):
    user = await make_user(db_session)
    repo = await make_repo(db_session, user)
    file = await make_file(db_session, repo, path="long.py")
    await make_symbol(db_session, file, name="long_line", source_code="a" * 3000 + "!")

    result = await grep_symbols(db_session, repo.id, EXPENSIVE_REGEX, regex=True, timeout_ms=150)

    assert not result.ok
    assert result.refusal.reason == "timeout"
    assert "too expensive" in result.refusal.message
    await _assert_session_usable(db_session)
    # The timeout was lifted with the savepoint, so a later search is not cut short.
    later = await grep_symbols(db_session, repo.id, "a{100}", regex=True)
    assert later.ok and later.total_symbols == 1


async def test_a_successful_search_does_not_leave_its_timeout_behind(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    result = await grep_symbols(db_session, seeded.repo.id, "bcrypt", regex=False, timeout_ms=1500)

    assert result.ok
    await _assert_session_usable(db_session)


async def test_results_stop_at_max_results_and_report_the_total(db_session):
    user = await make_user(db_session)
    repo = await make_repo(db_session, user)
    popular = await make_file(db_session, repo, path="popular.py", fan_in=9)
    quiet = await make_file(db_session, repo, path="quiet.py", fan_in=0)
    for index in range(5):
        await make_symbol(
            db_session,
            popular,
            name=f"hit_{index}",
            start_line=index * 10 + 1,
            source_code="needle\n",
        )
    for index in range(5):
        await make_symbol(
            db_session,
            quiet,
            name=f"low_{index}",
            start_line=index * 10 + 1,
            source_code="needle\n",
        )

    result = await grep_symbols(db_session, repo.id, "needle", regex=False, max_results=7)

    assert result.total_symbols == 10
    assert result.truncated
    assert len({m.symbol_id for m in result.matches}) == 7
    # The most widely imported file's symbols are kept first.
    assert [m.path for m in result.matches[:5]] == ["popular.py"] * 5

    complete = await grep_symbols(db_session, repo.id, "needle", regex=False, max_results=10)
    assert not complete.truncated


async def test_only_functions_classes_and_methods_are_searched(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    # MAX_PAGE_SIZE is a stored variable and the import line is a stored import.
    assert (
        await grep_symbols(db_session, seeded.repo.id, "MAX_PAGE_SIZE", regex=False)
    ).matches == ()
    assert (
        await grep_symbols(db_session, seeded.repo.id, "import getUserById", regex=False)
    ).matches == ()


async def test_a_regex_that_spans_lines_still_reports_the_symbol(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    result = await grep_symbols(db_session, seeded.repo.id, r"hashed\):.*checkpw", regex=True)

    (match,) = result.matches
    assert match.symbol_name == "verify_password"
    assert match.line == 10


# --- the channel -----------------------------------------------------------


async def _search(db, repo, question, spec=None, **variant):
    ctx = make_context(db, repo)
    return await get_channel("grep").search(
        ctx, QueryVariant(question, **variant), spec or GrepChannel()
    )


async def test_the_channel_greps_identifier_tokens_literally(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    found = await _search(db_session, seeded.repo, "who calls hash_password?")

    # Only hash_password's own signature contains its name in a body.
    assert [c.reference.symbol_name for c in found] == ["hash_password"]
    assert found[0].channel_hits[0].raw_score == 1.0
    assert_channel_contract(found, channel="grep", variant=0, k=50)


async def test_the_channel_ranks_by_matching_lines_then_fan_in(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    # ``plain`` is not an identifier, so quote it. verify_password and
    # hash_password both have two matching lines; the first sits in the same file.
    found = await _search(db_session, seeded.repo, 'where is "plain" used')

    assert {c.reference.symbol_name for c in found} == {"verify_password", "hash_password"}
    assert [c.channel_hits[0].raw_score for c in found] == [2.0, 2.0]
    assert [c.channel_hits[0].rank for c in found] == [1, 2]


async def test_the_channel_merges_terms_per_symbol(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    found = await _search(db_session, seeded.repo, "`bcrypt.checkpw` and `bcrypt.hashpw`")

    by_name = {c.reference.symbol_name: c for c in found}
    assert set(by_name) == {"verify_password", "hash_password"}
    # ``checkpw`` and ``hashpw`` (the dotted tokens' last segments) add to the whole-token hits.
    assert by_name["verify_password"].channel_hits[0].raw_score >= 2.0


async def test_the_channel_takes_quoted_strings(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    found = await _search(db_session, seeded.repo, "where does it print '% off'?")

    assert [c.reference.symbol_name for c in found] == ["format_discount"]


async def test_a_question_without_a_token_or_quote_finds_nothing(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    assert await _search(db_session, seeded.repo, "how does login work") == []


async def test_k_limits_the_channel_and_the_variant_is_recorded(db_session):
    user = await make_user(db_session)
    repo = await make_repo(db_session, user)
    file = await make_file(db_session, repo, path="many.py")
    for index in range(5):
        await make_symbol(
            db_session,
            file,
            name=f"fn_{index}",
            start_line=index * 10 + 1,
            end_line=index * 10 + 2,
            source_code="call shared_helper()\n",
        )

    found = await _search(db_session, repo, "shared_helper", GrepChannel(k=2), index=5)

    assert len(found) == 2
    assert_channel_contract(found, channel="grep", variant=5, k=2)


async def test_the_channel_uses_the_embedded_chunk_when_there_is_one(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))
    embedding = seeded.symbol_embeddings[("app/auth/security.py", "hash_password")]

    found = await _search(db_session, seeded.repo, "hash_password")

    assert found[0].text == embedding.chunk_text
    assert found[0].source_id == seeded.symbol_named("hash_password").id


async def test_hyde_text_is_left_to_the_dense_channel(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    assert await _search(db_session, seeded.repo, "hash_password", kind="hyde") == []


async def test_a_backtracking_pattern_over_a_long_line_cannot_block_the_event_loop(db_session):
    user = await make_user(db_session)
    repo = await make_repo(db_session, user)
    file = await make_file(db_session, repo, path="hostile.py")
    # In a backtracking engine the first line takes exponential time to reject;
    # the second makes Postgres report the symbol as a match.
    await make_symbol(
        db_session,
        file,
        name="hostile",
        start_line=5,
        source_code="x" * 60 + "\nxxy\n",
    )

    started = time.monotonic()
    result = await asyncio.wait_for(
        grep_symbols(db_session, repo.id, "(x+x+)+y", regex=True), timeout=10
    )

    assert time.monotonic() - started < 5
    assert result.ok
    assert [(m.line, m.text) for m in result.matches] == [(6, "xxy")]
    await _assert_session_usable(db_session)


async def test_regex_matches_report_every_matching_line_with_file_line_numbers(db_session):
    user = await make_user(db_session)
    repo = await make_repo(db_session, user)
    file = await make_file(db_session, repo, path="lines.py")
    await make_symbol(
        db_session,
        file,
        name="lines",
        start_line=20,
        source_code="def lines():\n    a = 1\n    b = 22\n    return a + b\n",
    )

    result = await grep_symbols(db_session, repo.id, r"= \d+", regex=True)

    assert [(m.line, m.text) for m in result.matches] == [(21, "    a = 1"), (22, "    b = 22")]
