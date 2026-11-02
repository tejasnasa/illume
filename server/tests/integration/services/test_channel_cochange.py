"""The co-change channel: files that change with the seed files."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.retrieval.channels import get_expansion_channel
from app.services.retrieval.channels.cochange import cochanged_files
from app.services.retrieval.config import CochangeChannel
from tests.factories import make_user
from tests.fixtures.retrieval import (
    DEFAULT_SPEC,
    CochangeSpec,
    assert_channel_contract,
    file_seed,
    make_context,
    non_file_seed,
    seed_repo,
)

pytestmark = pytest.mark.integration

SECURITY = "app/auth/security.py"
SERVICE = "app/users/service.py"
ROUTES = "app/users/routes.py"
INVOICE = "app/billing/invoice.py"

# jaccard: security-service 0.5, security-routes 0.25, service-routes 2/3, invoice-routes 0.2
COCHANGE_SPEC = replace(
    DEFAULT_SPEC,
    cochange=(
        CochangeSpec(SECURITY, SERVICE, together=2, a_count=3, b_count=3),
        CochangeSpec(SECURITY, ROUTES, together=2, a_count=5, b_count=5),
        CochangeSpec(SERVICE, ROUTES, together=4, a_count=5, b_count=5),
        CochangeSpec(INVOICE, ROUTES, together=2, a_count=5, b_count=7),
    ),
)


async def _expand(db, seeded, seeds, spec=None):
    return await get_expansion_channel("cochange").expand(
        make_context(db, seeded.repo), seeds, spec or CochangeChannel()
    )


def _paths(found):
    return [c.file_path for c in found]


def _score(candidate):
    return candidate.channel_hits[0].raw_score


async def test_partners_are_found_whichever_column_the_seed_is_stored_in(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), COCHANGE_SPEC)

    # Each file is the smaller id in some pairs and the larger in others; whichever
    # it is, all of its partners must come back.
    for path, expected in {
        SECURITY: {SERVICE, ROUTES},
        SERVICE: {SECURITY, ROUTES},
        ROUTES: {SECURITY, SERVICE, INVOICE},
        INVOICE: {ROUTES},
    }.items():
        found = await _expand(db_session, seeded, [file_seed(seeded, path, fused_score=1.0)])
        assert set(_paths(found)) == expected, path
        assert_channel_contract(found, channel="cochange", variant=0, k=50)


async def test_the_score_is_the_seed_score_times_jaccard(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), COCHANGE_SPEC)

    found = await _expand(db_session, seeded, [file_seed(seeded, ROUTES, fused_score=0.6)])

    scores = {c.file_path: _score(c) for c in found}
    assert scores[SERVICE] == pytest.approx(0.6 * 4 / 6)
    assert scores[SECURITY] == pytest.approx(0.6 * 2 / 8)
    assert scores[INVOICE] == pytest.approx(0.6 * 2 / 10)
    assert _paths(found) == [SERVICE, SECURITY, INVOICE]


async def test_a_partner_of_several_seeds_keeps_its_best_score(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), COCHANGE_SPEC)
    seeds = [
        file_seed(seeded, SECURITY, fused_score=1.0),
        file_seed(seeded, SERVICE, fused_score=0.1),
    ]

    found = await _expand(db_session, seeded, seeds)

    # routes: 1.0 * 0.25 from security, 0.1 * (2/3) from service.
    assert {c.file_path: _score(c) for c in found} == {ROUTES: pytest.approx(0.25)}


async def test_seed_files_are_never_returned_and_the_seed_limit_applies(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), COCHANGE_SPEC)
    seeds = [
        file_seed(seeded, SECURITY, fused_score=1.0),
        file_seed(seeded, SERVICE, fused_score=0.9),
        file_seed(seeded, INVOICE, fused_score=0.8),
    ]

    both = await _expand(db_session, seeded, seeds, CochangeChannel(seeds=2))
    one = await _expand(db_session, seeded, seeds, CochangeChannel(seeds=1))

    assert _paths(both) == [ROUTES]
    assert set(_paths(one)) == {SERVICE, ROUTES}


async def test_seeds_without_a_file_are_skipped(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), COCHANGE_SPEC)

    found = await _expand(
        db_session,
        seeded,
        [non_file_seed(), file_seed(seeded, INVOICE, fused_score=1.0)],
        CochangeChannel(seeds=1),
    )

    assert _paths(found) == [ROUTES]
    assert await _expand(db_session, seeded, [non_file_seed()]) == []


async def test_k_limits_the_list(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), COCHANGE_SPEC)

    found = await _expand(
        db_session, seeded, [file_seed(seeded, ROUTES, fused_score=1.0)], CochangeChannel(k=2)
    )

    assert _paths(found) == [SERVICE, SECURITY]


async def test_candidates_are_built_like_the_graph_channels(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), COCHANGE_SPEC)

    found = await _expand(db_session, seeded, [file_seed(seeded, ROUTES, fused_score=1.0)])

    security = next(c for c in found if c.file_path == SECURITY)
    service = next(c for c in found if c.file_path == SERVICE)
    assert security.text == DEFAULT_SPEC.files[0].file_chunk
    assert service.text.startswith("# app/users/service.py\nLanguage: python")
    assert security.key == f"F:{SECURITY}"
    assert security.file_id == security.source_id == seeded.files[SECURITY].id


async def test_cochanged_files_lists_partners_strongest_first(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), COCHANGE_SPEC)

    partners = await cochanged_files(db_session, seeded.repo.id, seeded.files[ROUTES].id, 10)

    assert [(p.path, p.together) for p in partners] == [(SERVICE, 4), (SECURITY, 2), (INVOICE, 2)]
    assert [p.jaccard for p in partners] == pytest.approx([4 / 6, 2 / 8, 2 / 10])
    # A file that is the larger id in a pair still finds it.
    assert {
        p.path
        for p in await cochanged_files(db_session, seeded.repo.id, seeded.files[INVOICE].id, 10)
    } == {ROUTES}


async def test_cochanged_files_honours_the_limit_and_the_repository(db_session):
    user = await make_user(db_session)
    first = await seed_repo(db_session, user, COCHANGE_SPEC, name="first")
    second = await seed_repo(db_session, user, COCHANGE_SPEC, name="second")

    limited = await cochanged_files(db_session, first.repo.id, first.files[ROUTES].id, 1)
    # Asking for the first repository's file through the second returns nothing.
    crossed = await cochanged_files(db_session, second.repo.id, first.files[ROUTES].id, 10)

    assert [p.path for p in limited] == [SERVICE]
    assert crossed == []
