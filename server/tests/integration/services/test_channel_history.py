"""The history channel: dense and lexical search over commits and pull requests only."""

from __future__ import annotations

import dataclasses

import pytest

from app.services.retrieval.candidate import QueryVariant
from app.services.retrieval.channels import get_channel
from app.services.retrieval.channels.history import INTERNAL_RRF_K
from app.services.retrieval.config import HistoryChannel
from tests.factories import make_user
from tests.fixtures.retrieval import (
    DEFAULT_SPEC,
    angled_vector,
    assert_channel_contract,
    axis_vector,
    make_context,
    seed_repo,
)

pytestmark = pytest.mark.integration

QUESTION = "why was password hashing changed to bcrypt"


def _spec_with_vectors():
    """The default repository with the first PR and the first commit near axis 0, PR nearest."""
    commits = list(DEFAULT_SPEC.commits)
    commits[0] = dataclasses.replace(commits[0], vector=angled_vector(0.3))
    pulls = list(DEFAULT_SPEC.pull_requests)
    pulls[0] = dataclasses.replace(pulls[0], vector=angled_vector(0.1))
    return dataclasses.replace(DEFAULT_SPEC, commits=tuple(commits), pull_requests=tuple(pulls))


async def _search(db, seeded, question=QUESTION, spec=None, **variant):
    ctx = make_context(db, seeded.repo, {question: axis_vector(0)})
    return await get_channel("history").search(
        ctx, QueryVariant(question, **variant), spec or HistoryChannel()
    )


async def test_only_commits_and_pull_requests_come_back(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), _spec_with_vectors())

    # "bcrypt" and "password" also appear in symbol, file and README chunks.
    found = await _search(db_session, seeded)

    assert found
    assert {c.source_type for c in found} <= {"commit", "pull_request"}
    assert {c.provenance for c in found} == {"history"}
    assert_channel_contract(found, channel="history", variant=0, k=50)


async def test_a_chunk_found_by_both_halves_outranks_one_found_by_one(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), _spec_with_vectors())

    found = await _search(db_session, seeded)

    # PR 12 is first in both halves. The first commit is second in both (it
    # mentions verify_password, so it shares the word "password").
    assert found[0].reference.pr_number == 12
    assert found[0].channel_hits[0].raw_score == pytest.approx(2 / (INTERNAL_RRF_K + 1))
    assert found[1].reference.commit_hash == "a1b2c3d4e5f60718"
    assert found[1].channel_hits[0].raw_score == pytest.approx(2 / (INTERNAL_RRF_K + 2))


async def test_the_dense_half_alone_can_surface_a_chunk(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), _spec_with_vectors())

    found = await _search(db_session, seeded, "unrelated words qqq")

    # No term matches, so only the vector-near rows come back, nearest first.
    assert [c.reference.pr_number or c.reference.commit_hash for c in found] == [
        12,
        "a1b2c3d4e5f60718",
    ]
    assert found[0].channel_hits[0].raw_score == pytest.approx(1 / (INTERNAL_RRF_K + 1))


async def test_the_lexical_half_alone_can_surface_a_chunk(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))

    # Default vectors are hashes, far from the query, so the dense half is empty.
    found = await _search(db_session, seeded, "invoice discounts")

    assert found[0].reference.pr_number == 13
    assert found[0].channel_hits[0].raw_score == pytest.approx(1 / (INTERNAL_RRF_K + 1))


async def test_k_limits_the_fused_list(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), _spec_with_vectors())

    found = await _search(db_session, seeded, spec=HistoryChannel(k=1), index=2)

    assert len(found) == 1
    assert_channel_contract(found, channel="history", variant=2, k=1)


async def test_max_distance_applies_to_the_dense_half(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), _spec_with_vectors())

    found = await _search(
        db_session, seeded, "unrelated words qqq", HistoryChannel(max_distance=0.001)
    )

    assert found == []


async def test_hyde_text_uses_only_the_dense_half(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), _spec_with_vectors())

    # "invoice discounts" would match PR 13 by keyword; as hyde it must not.
    found = await _search(db_session, seeded, "invoice discounts", kind="hyde")

    assert [c.reference.pr_number or c.reference.commit_hash for c in found] == [
        12,
        "a1b2c3d4e5f60718",
    ]
