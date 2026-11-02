"""The dense channel: nearest chunks by cosine distance, one repository at a time."""

from __future__ import annotations

import math

import pytest

from app.services.retrieval.candidate import QueryVariant
from app.services.retrieval.channels import get_channel
from app.services.retrieval.config import DenseChannel
from tests.factories import make_embedding, make_file, make_repo, make_symbol, make_user
from tests.fixtures.retrieval import (
    angled_vector,
    assert_channel_contract,
    axis_vector,
    make_context,
)

pytestmark = pytest.mark.integration

QUERY = "where are passwords checked"


async def _seed_by_angle(db, repo, angles: dict[str, float]):
    """One symbol chunk per label, at a known angle from the query vector."""
    rows = {}
    for label, theta in angles.items():
        file = await make_file(db, repo, path=f"src/{label}.py")
        symbol = await make_symbol(db, file, name=f"fn_{label}")
        rows[label] = await make_embedding(
            db,
            repo,
            source_id=symbol.id,
            source_type="symbol",
            file_id=file.id,
            chunk_text=f"chunk {label}",
            vector=angled_vector(theta),
        )
    return rows


async def test_the_nearest_chunk_comes_first_with_its_distance(db_session):
    user = await make_user(db_session)
    repo = await make_repo(db_session, user)
    rows = await _seed_by_angle(db_session, repo, {"far": 0.8, "near": 0.1, "mid": 0.4})
    ctx = make_context(db_session, repo, {QUERY: axis_vector(0)})

    found = await get_channel("dense").search(ctx, QueryVariant(QUERY), DenseChannel())

    assert [c.text for c in found] == ["chunk near", "chunk mid", "chunk far"]
    assert found[0].source_id == rows["near"].source_id
    assert found[0].channel_hits[0].raw_score == pytest.approx(1 - math.cos(0.1), abs=1e-6)
    assert_channel_contract(found, channel="dense", variant=0, k=50)


async def test_k_limits_the_list(db_session):
    user = await make_user(db_session)
    repo = await make_repo(db_session, user)
    await _seed_by_angle(db_session, repo, {f"c{i}": 0.05 * (i + 1) for i in range(6)})
    ctx = make_context(db_session, repo, {QUERY: axis_vector(0)})

    found = await get_channel("dense").search(ctx, QueryVariant(QUERY), DenseChannel(k=3))

    assert [c.text for c in found] == ["chunk c0", "chunk c1", "chunk c2"]
    assert_channel_contract(found, channel="dense", variant=0, k=3)


async def test_chunks_beyond_max_distance_are_dropped(db_session):
    user = await make_user(db_session)
    repo = await make_repo(db_session, user)
    # Distances: 1 - cos(0.5) = 0.12, 1 - cos(1.2) = 0.64, 1 - cos(1.5) = 0.93.
    await _seed_by_angle(db_session, repo, {"in": 0.5, "edge": 1.2, "out": 1.5})
    ctx = make_context(db_session, repo, {QUERY: axis_vector(0)})
    dense = get_channel("dense")

    default = await dense.search(ctx, QueryVariant(QUERY), DenseChannel())
    tight = await dense.search(ctx, QueryVariant(QUERY), DenseChannel(max_distance=0.3))

    assert [c.text for c in default] == ["chunk in", "chunk edge"]
    assert [c.text for c in tight] == ["chunk in"]


async def test_the_variant_index_is_recorded_and_hyde_is_searched(db_session):
    user = await make_user(db_session)
    repo = await make_repo(db_session, user)
    await _seed_by_angle(db_session, repo, {"a": 0.1})
    snippet = "def check(): ..."
    ctx = make_context(db_session, repo, {snippet: axis_vector(0)})

    found = await get_channel("dense").search(
        ctx, QueryVariant(snippet, kind="hyde", index=2), DenseChannel()
    )

    assert len(found) == 1
    assert_channel_contract(found, channel="dense", variant=2, k=50)


async def test_an_unrelated_query_returns_nothing(db_session):
    user = await make_user(db_session)
    repo = await make_repo(db_session, user)
    await _seed_by_angle(db_session, repo, {"a": 0.1})
    ctx = make_context(db_session, repo, {QUERY: axis_vector(5)})

    assert await get_channel("dense").search(ctx, QueryVariant(QUERY), DenseChannel()) == []
