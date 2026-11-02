"""The symbol channel: identifiers in the question matched against symbol names."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.services.retrieval.candidate import QueryVariant
from app.services.retrieval.channels import get_channel
from app.services.retrieval.config import SymbolChannel
from tests.factories import make_file, make_repo, make_symbol, make_user
from tests.fixtures.retrieval import assert_channel_contract, make_context, seed_repo

pytestmark = pytest.mark.integration


async def _search(db, repo, question, spec=None, **variant):
    ctx = make_context(db, repo)
    return await get_channel("symbol").search(
        ctx, QueryVariant(question, **variant), spec or SymbolChannel()
    )


async def test_a_snake_case_name_is_found_exactly(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    found = await _search(db_session, seeded.repo, "what does verify_password do?")

    assert found[0].reference.symbol_name == "verify_password"
    assert found[0].reference.file_path == "app/auth/security.py"
    assert found[0].source_id == seeded.symbol_named("verify_password").id
    assert found[0].file_id == seeded.files["app/auth/security.py"].id
    assert found[0].channel_hits[0].raw_score == 1.0
    assert_channel_contract(found, channel="symbol", variant=0, k=50)


async def test_a_camel_case_name_is_found_and_the_key_carries_the_line_range(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    found = await _search(db_session, seeded.repo, "where is getUserById defined")

    assert [c.reference.symbol_name for c in found] == ["getUserById"]
    assert found[0].key == "F:app/users/service.py:5-6"
    assert (found[0].reference.start_line, found[0].reference.end_line) == (5, 6)


async def test_an_exact_name_beats_fuzzy_ones(db_session):
    user = await make_user(db_session)
    repo = await make_repo(db_session, user)
    file = await make_file(db_session, repo, path="a.py", fan_in=0)
    busy = await make_file(db_session, repo, path="b.py", fan_in=99)
    await make_symbol(db_session, busy, name="parse_configs", start_line=1, end_line=2)
    await make_symbol(db_session, busy, name="parse_config_file", start_line=3, end_line=4)
    exact = await make_symbol(db_session, file, name="parse_config", start_line=1, end_line=2)

    found = await _search(db_session, repo, "see parse_config", SymbolChannel(min_similarity=0.3))

    # The exact name wins despite living in the file nothing imports.
    assert found[0].source_id == exact.id
    scores = [c.channel_hits[0].raw_score for c in found]
    assert scores[0] == 1.0
    assert all(0.3 < score < 1.0 for score in scores[1:])
    assert scores[1:] == sorted(scores[1:], reverse=True)


async def test_a_typo_still_matches_above_the_threshold(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    found = await _search(db_session, seeded.repo, "what does verify_pasword do")

    assert found[0].reference.symbol_name == "verify_password"
    assert 0.3 < found[0].channel_hits[0].raw_score < 1.0


async def test_the_threshold_decides_what_counts_as_a_match(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    loose = await _search(db_session, seeded.repo, "verify_pasword", SymbolChannel())
    strict = await _search(
        db_session, seeded.repo, "verify_pasword", SymbolChannel(min_similarity=0.95)
    )

    assert loose
    assert strict == []


async def test_the_session_threshold_is_put_back(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))
    await db_session.execute(text("SELECT set_config('pg_trgm.similarity_threshold', '0.5', true)"))

    await _search(db_session, seeded.repo, "verify_pasword", SymbolChannel(min_similarity=0.9))

    after = (
        await db_session.execute(text("SELECT current_setting('pg_trgm.similarity_threshold')"))
    ).scalar_one()
    assert float(after) == pytest.approx(0.5)


async def test_only_functions_classes_and_methods_come_back(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    # ``getUserById`` is also an import in routes.py; MAX_PAGE_SIZE is a variable.
    imports = await _search(db_session, seeded.repo, "getUserById")
    variable = await _search(db_session, seeded.repo, "MAX_PAGE_SIZE")

    assert [c.file_path for c in imports] == ["app/users/service.py"]
    assert variable == []


async def test_a_method_and_a_class_are_both_searchable(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    method = await _search(db_session, seeded.repo, "delete_user")
    klass = await _search(db_session, seeded.repo, "`PasswordPolicy`")

    assert method[0].reference.symbol_name == "delete_user"
    assert klass[0].reference.symbol_name == "PasswordPolicy"


async def test_the_embedded_chunk_is_the_text_when_there_is_one(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))
    embedding = seeded.symbol_embeddings[("app/auth/security.py", "verify_password")]

    found = await _search(db_session, seeded.repo, "verify_password")

    assert found[0].text == embedding.chunk_text
    assert found[0].reference.chunk_text == embedding.chunk_text


async def test_a_rendered_header_is_the_text_when_there_is_no_embedding(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    # ``delete_user`` is seeded without an embedding row.
    found = await _search(db_session, seeded.repo, "delete_user")

    assert found[0].text == (
        "# app/users/service.py\n## method: delete_user\n"
        "def delete_user(self, user_id):\n    self.db.delete(user_id)\n"
    )


async def test_a_long_body_is_truncated_in_the_rendered_text(db_session):
    user = await make_user(db_session)
    repo = await make_repo(db_session, user)
    file = await make_file(db_session, repo, path="big.py")
    await make_symbol(
        db_session, file, name="huge_function", source_code="x = 1\n" * 5000, end_line=5000
    )

    found = await _search(db_session, repo, "huge_function")

    assert len(found[0].text) == 8192
    assert found[0].text.startswith("# big.py\n## function: huge_function\n")


async def test_k_limits_the_list_and_the_variant_is_recorded(db_session):
    user = await make_user(db_session)
    repo = await make_repo(db_session, user)
    file = await make_file(db_session, repo, path="many.py")
    for index in range(5):
        await make_symbol(
            db_session,
            file,
            name=f"load_item_{index}",
            start_line=index * 10 + 1,
            end_line=index * 10 + 5,
        )

    found = await _search(db_session, repo, "load_item_1", SymbolChannel(k=3), index=4)

    assert len(found) == 3
    assert found[0].reference.symbol_name == "load_item_1"
    assert_channel_contract(found, channel="symbol", variant=4, k=3)


async def test_a_question_with_no_identifier_finds_nothing(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    assert await _search(db_session, seeded.repo, "how does login work") == []


async def test_hyde_text_is_left_to_the_dense_channel(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    assert await _search(db_session, seeded.repo, "verify_password", kind="hyde") == []
