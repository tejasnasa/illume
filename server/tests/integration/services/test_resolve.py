"""Batched source resolution matches the per-hit path, order included."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import AstSymbol, Commit, PullRequest
from app.services.rag import _resolve_source
from app.services.retrieval.resolve import resolve_sources
from tests.factories import make_embedding, make_ingested_repo, make_user

pytestmark = pytest.mark.integration


async def test_batched_resolution_matches_the_per_hit_path(db_session):
    """Every source type resolves to the same citation either way, in input order."""
    user = await make_user(db_session)
    repo, files = await make_ingested_repo(db_session, user, file_count=2)

    symbol = (
        await db_session.execute(select(AstSymbol).where(AstSymbol.file_id == files[0].id))
    ).scalar_one()

    commit = Commit(
        repository_id=repo.id,
        hash="a1b2c3d4e5f6",
        author_name="Ada Lovelace",
        author_email="ada@example.com",
        message="feat: add the first module",
        files_changed=1,
        changed_files_list=[files[0].path],
        authored_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    pull_request = PullRequest(
        repository_id=repo.id,
        number=142,
        title="Add the first module",
        description="Adds it.",
        author="Ada Lovelace",
        files_changed=1,
    )
    db_session.add_all([commit, pull_request])
    await db_session.flush()

    embeddings = [
        await make_embedding(
            db_session,
            repo,
            source_id=symbol.id,
            source_type="symbol",
            file_id=files[0].id,
            chunk_text="symbol chunk",
        ),
        await make_embedding(
            db_session,
            repo,
            source_id=uuid4(),
            source_type="file",
            file_id=files[1].id,
            chunk_text="file chunk",
        ),
        await make_embedding(
            db_session,
            repo,
            source_id=commit.id,
            source_type="commit",
            chunk_text="commit chunk",
        ),
        await make_embedding(
            db_session,
            repo,
            source_id=pull_request.id,
            source_type="pull_request",
            chunk_text="pr chunk",
        ),
        await make_embedding(
            db_session,
            repo,
            source_id=uuid4(),
            source_type="document",
            chunk_text="readme chunk",
        ),
        # A hit whose backing row is gone: both paths must return a citation
        # with the detail fields left empty rather than dropping the hit.
        await make_embedding(
            db_session,
            repo,
            source_id=uuid4(),
            source_type="symbol",
            file_id=files[0].id,
            chunk_text="orphan chunk",
        ),
    ]

    batched = await resolve_sources(db_session, embeddings)
    per_hit = [await _resolve_source(db_session, embedding) for embedding in embeddings]

    assert batched == per_hit
    assert [reference.source_type for reference in batched] == [
        "symbol",
        "file",
        "commit",
        "pull_request",
        "document",
        "symbol",
    ]
    assert batched[0].symbol_name == symbol.name
    assert batched[1].file_path == files[1].path
    assert batched[2].commit_hash == commit.hash
    assert batched[3].pr_number == pull_request.number
    assert batched[5].symbol_name is None
