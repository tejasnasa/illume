"""The ``search_tsv`` generated column agrees with its Python twin.

The lexical channel builds its query with ``split_identifiers``; the index was
built by SQL in the migration. If the two disagree on what a word is, a query
silently misses chunks it should match, and nothing else would notice.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text, update

from app.models import Embedding
from app.services.retrieval.identifiers import lexical_text
from tests.factories import make_embedding, make_repo, make_user

pytestmark = pytest.mark.integration

SAMPLES = [
    "def getUserById(user_id): return db.get(user_id)",
    "class HTTPServerConfig: parse_HTTPResponse(raw)",
    "app/core/security.py verify_password",
    "os.path.join(BASE_DIR, 'static') v2Api kebab-case-name __init__",
    "Merge pull request #12 from feature/LoginFlow",
    "plain prose with no identifiers at all",
]


@pytest.mark.parametrize("chunk", SAMPLES)
async def test_the_column_matches_the_python_transform(db_session, chunk):
    user = await make_user(db_session)
    repo = await make_repo(db_session, user)
    embedding = await make_embedding(db_session, repo, chunk_text=chunk)

    stored, expected = (
        await db_session.execute(
            text(
                "SELECT search_tsv::text, to_tsvector('simple', :lexical)::text "
                "FROM embeddings WHERE id = :id"
            ),
            {"lexical": lexical_text(chunk), "id": embedding.id},
        )
    ).one()

    assert stored == expected


async def test_an_identifier_matches_whole_and_as_words(db_session):
    user = await make_user(db_session)
    repo = await make_repo(db_session, user)
    embedding = await make_embedding(db_session, repo, chunk_text="def getUserById(user_id): ...")

    async def matches(query: str) -> bool:
        row = (
            await db_session.execute(
                text(
                    "SELECT 1 FROM embeddings "
                    "WHERE id = :id AND search_tsv @@ plainto_tsquery('simple', :q)"
                ),
                {"id": embedding.id, "q": query},
            )
        ).first()
        return row is not None

    assert await matches("getUserById")
    assert await matches("get user by id")
    assert await matches("GETUSERBYID")
    assert not await matches("delete user")


async def test_the_column_follows_an_update(db_session):
    """The sync path rewrites ``chunk_text`` in place; the index has to follow."""
    user = await make_user(db_session)
    repo = await make_repo(db_session, user)
    embedding = await make_embedding(db_session, repo, chunk_text="def oldName(): ...")

    await db_session.execute(
        update(Embedding)
        .where(Embedding.id == embedding.id)
        .values(chunk_text="def newName(): ...")
    )
    stored = (
        await db_session.execute(select(Embedding.search_tsv).where(Embedding.id == embedding.id))
    ).scalar_one()

    assert "'new'" in stored
    assert "'old'" not in stored
