"""The graph channel: files one import away from the seed files."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest
from sqlalchemy import text

from app.services.file_graph import iter_file_edges, query_neighbours_async
from app.services.retrieval.channels import get_expansion_channel
from app.services.retrieval.config import GraphChannel
from tests.factories import make_user
from tests.fixtures.retrieval import (
    DEFAULT_SPEC,
    FileSpec,
    ImportSpec,
    RepoSpec,
    SymbolSpec,
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

# routes -> service -> security <- invoice
GRAPH_SPEC = replace(
    DEFAULT_SPEC,
    imports=(
        ImportSpec(ROUTES, SERVICE, weight=1),
        ImportSpec(SERVICE, SECURITY, weight=3),
        ImportSpec(INVOICE, SECURITY, weight=1),
    ),
)


async def _expand(db, seeded, seeds, spec=None):
    return await get_expansion_channel("graph").expand(
        make_context(db, seeded.repo), seeds, spec or GraphChannel()
    )


def _paths(found):
    return [c.file_path for c in found]


def _score(candidate):
    return candidate.channel_hits[0].raw_score


async def test_expansion_follows_imports_in_both_directions(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), GRAPH_SPEC)

    found = await _expand(db_session, seeded, [file_seed(seeded, SERVICE, fused_score=1.0)])

    # service imports security and is imported by routes.
    assert set(_paths(found)) == {SECURITY, ROUTES}
    assert_channel_contract(found, channel="graph", variant=0, k=50)
    for candidate in found:
        assert candidate.source_type == "file"
        assert candidate.source_id == candidate.file_id == seeded.files[candidate.file_path].id
        assert candidate.key == f"F:{candidate.file_path}"


async def test_a_seed_file_is_never_returned(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), GRAPH_SPEC)
    seeds = [
        file_seed(seeded, SERVICE, fused_score=1.0),
        file_seed(seeded, SECURITY, fused_score=0.9),
    ]

    found = await _expand(db_session, seeded, seeds)

    assert SERVICE not in _paths(found)
    assert SECURITY not in _paths(found)
    assert set(_paths(found)) == {ROUTES, INVOICE}


async def test_the_score_is_seed_times_decay_times_a_weight_lift(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), GRAPH_SPEC)

    found = await _expand(
        db_session,
        seeded,
        [file_seed(seeded, SERVICE, fused_score=0.8)],
        GraphChannel(decay=0.5),
    )

    by_path = {c.file_path: _score(c) for c in found}
    assert by_path[SECURITY] == pytest.approx(0.8 * 0.5 * (1 + 0.1 * math.log(1 + 3)))
    assert by_path[ROUTES] == pytest.approx(0.8 * 0.5 * (1 + 0.1 * math.log(1 + 1)))
    # The heavier edge ranks first.
    assert _paths(found) == [SECURITY, ROUTES]


async def test_decay_scales_every_score(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), GRAPH_SPEC)
    seeds = [file_seed(seeded, SERVICE, fused_score=1.0)]

    half = await _expand(db_session, seeded, seeds, GraphChannel(decay=0.5))
    full = await _expand(db_session, seeded, seeds, GraphChannel(decay=1.0))

    assert _score(full[0]) == pytest.approx(2 * _score(half[0]))


async def test_a_neighbour_of_several_seeds_keeps_its_best_score(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), GRAPH_SPEC)
    # security is a neighbour of both service (weight 3) and invoice (weight 1).
    seeds = [
        file_seed(seeded, SERVICE, fused_score=0.2),
        file_seed(seeded, INVOICE, fused_score=0.9),
    ]

    found = await _expand(db_session, seeded, seeds, GraphChannel(decay=0.5))

    by_path = {c.file_path: _score(c) for c in found}
    via_invoice = 0.9 * 0.5 * (1 + 0.1 * math.log(2))
    via_service = 0.2 * 0.5 * (1 + 0.1 * math.log(4))
    assert via_invoice > via_service
    assert by_path[SECURITY] == pytest.approx(via_invoice)
    assert _paths(found).count(SECURITY) == 1


async def test_spec_seeds_limits_how_many_files_are_expanded(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), GRAPH_SPEC)
    seeds = [
        file_seed(seeded, SERVICE, fused_score=1.0),
        file_seed(seeded, INVOICE, fused_score=0.9),
    ]

    one = await _expand(db_session, seeded, seeds, GraphChannel(seeds=1))
    two = await _expand(db_session, seeded, seeds, GraphChannel(seeds=2))

    assert set(_paths(one)) == {SECURITY, ROUTES}
    # With invoice expanded too, security is still found and invoice stays a seed.
    assert INVOICE not in _paths(two)


async def test_several_candidates_of_one_file_count_once_towards_the_limit(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), GRAPH_SPEC)
    seeds = [
        file_seed(seeded, SERVICE, fused_score=1.0, symbol="create_user"),
        file_seed(seeded, SERVICE, fused_score=0.7, symbol="getUserById"),
        file_seed(seeded, INVOICE, fused_score=0.5),
    ]

    found = await _expand(db_session, seeded, seeds, GraphChannel(seeds=2))

    assert INVOICE not in _paths(found)
    assert set(_paths(found)) == {SECURITY, ROUTES}


async def test_seeds_without_a_file_are_skipped(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), GRAPH_SPEC)
    seeds = [non_file_seed(), file_seed(seeded, SERVICE, fused_score=1.0)]

    # The commit does not take the only seed slot.
    found = await _expand(db_session, seeded, seeds, GraphChannel(seeds=1))

    assert set(_paths(found)) == {SECURITY, ROUTES}
    assert await _expand(db_session, seeded, [non_file_seed()]) == []
    assert await _expand(db_session, seeded, []) == []


async def test_an_unscored_seed_uses_its_position(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), GRAPH_SPEC)
    seeds = [non_file_seed(), file_seed(seeded, SERVICE)]

    found = await _expand(db_session, seeded, seeds, GraphChannel(decay=0.5))

    # The file is second in the list.
    expected = (1 / 62) * 0.5 * (1 + 0.1 * math.log(4))
    assert {c.file_path: _score(c) for c in found}[SECURITY] == pytest.approx(expected)


async def test_k_limits_the_list_and_ties_break_by_path(db_session):
    spec = replace(
        GRAPH_SPEC,
        imports=(
            ImportSpec(ROUTES, SECURITY),
            ImportSpec(INVOICE, SECURITY),
            ImportSpec(SERVICE, SECURITY),
        ),
    )
    seeded = await seed_repo(db_session, await make_user(db_session), spec)

    found = await _expand(db_session, seeded, [file_seed(seeded, SECURITY, fused_score=1.0)])
    limited = await _expand(
        db_session, seeded, [file_seed(seeded, SECURITY, fused_score=1.0)], GraphChannel(k=2)
    )

    assert _paths(found) == sorted(_paths(found))
    assert _paths(limited) == _paths(found)[:2]


# --- barrels -----------------------------------------------------------------

APP = "src/app.py"
BARREL = "src/pkg/__init__.py"
INNER_BARREL = "src/pkg/sub/__init__.py"
REAL = "src/pkg/real.py"
DEEP = "src/pkg/sub/deep.py"
CONSUMER = "src/consumer.py"

_BARREL_SPEC = RepoSpec(
    files=(
        FileSpec(APP, symbols=(SymbolSpec("main"),)),
        FileSpec(CONSUMER, symbols=(SymbolSpec("consume"),)),
        FileSpec(BARREL, symbols=(SymbolSpec("reexport", kind="import", embed=False),)),
        FileSpec(INNER_BARREL, symbols=(SymbolSpec("reexport", kind="import", embed=False),)),
        FileSpec(REAL, symbols=(SymbolSpec("real_fn"),)),
        FileSpec(DEEP, symbols=(SymbolSpec("deep_fn"),)),
    ),
    imports=(
        ImportSpec(APP, BARREL, weight=2),
        ImportSpec(BARREL, REAL),
        ImportSpec(BARREL, INNER_BARREL),
        ImportSpec(INNER_BARREL, DEEP),
        # A cycle between barrels must not loop.
        ImportSpec(INNER_BARREL, BARREL),
        ImportSpec(CONSUMER, BARREL),
    ),
)


async def test_a_seed_that_imports_a_barrel_reaches_the_files_behind_it(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), _BARREL_SPEC)

    found = await _expand(db_session, seeded, [file_seed(seeded, APP, fused_score=1.0)])

    # The barrel itself is not a result; both real files behind it, one barrel deep and two, are.
    assert set(_paths(found)) == {REAL, DEEP}
    by_path = {c.file_path: _score(c) for c in found}
    expected = 1.0 * 0.5 * (1 + 0.1 * math.log(1 + 2))
    assert by_path[REAL] == pytest.approx(expected)


async def test_a_file_that_imports_a_seed_through_a_barrel_is_an_importer(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), _BARREL_SPEC)

    found = await _expand(db_session, seeded, [file_seed(seeded, REAL, fused_score=1.0)])

    # real is re-exported by the barrel, which app and consumer import.
    assert BARREL not in _paths(found)
    assert set(_paths(found)) == {APP, CONSUMER}


async def test_neighbours_without_walking_report_the_barrel(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), _BARREL_SPEC)

    rows = await query_neighbours_async(
        db_session, seeded.repo.id, [seeded.files[APP].id], through_barrels=False
    )

    assert rows == [(seeded.files[APP].id, seeded.files[BARREL].id, 2)]


async def test_a_barrel_with_nothing_behind_it_is_kept(db_session):
    spec = RepoSpec(
        files=(
            FileSpec(APP, symbols=(SymbolSpec("main"),)),
            FileSpec("src/types.py", symbols=(SymbolSpec("Shape", kind="variable", embed=False),)),
        ),
        imports=(ImportSpec(APP, "src/types.py"),),
    )
    seeded = await seed_repo(db_session, await make_user(db_session), spec)

    found = await _expand(db_session, seeded, [file_seed(seeded, APP, fused_score=1.0)])

    assert _paths(found) == ["src/types.py"]


# --- candidate text ------------------------------------------------------------


async def test_the_indexed_file_chunk_is_the_text_when_there_is_one(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), GRAPH_SPEC)

    found = await _expand(db_session, seeded, [file_seed(seeded, SERVICE, fused_score=1.0)])

    security = next(c for c in found if c.file_path == SECURITY)
    # DEFAULT_SPEC gives security.py a file chunk and routes.py none.
    assert security.text == DEFAULT_SPEC.files[0].file_chunk
    assert security.reference.chunk_text == security.text


async def test_the_header_is_rendered_when_there_is_no_chunk(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session), GRAPH_SPEC)

    found = await _expand(db_session, seeded, [file_seed(seeded, SERVICE, fused_score=1.0)])

    routes = next(c for c in found if c.file_path == ROUTES)
    assert routes.text == (
        "# app/users/routes.py\nLanguage: python\nImported by 1 files\nDefines: list_users"
    )


async def test_the_header_lists_at_most_fifteen_names_of_the_searchable_kinds(db_session):
    many = tuple(SymbolSpec(f"fn_{i:02d}", start_line=i + 1, embed=False) for i in range(20))
    spec = RepoSpec(
        files=(
            FileSpec(APP, symbols=(SymbolSpec("main"),)),
            FileSpec(
                "src/big.py", symbols=many + (SymbolSpec("CONST", kind="variable", embed=False),)
            ),
        ),
        imports=(ImportSpec(APP, "src/big.py"),),
    )
    seeded = await seed_repo(db_session, await make_user(db_session), spec)

    found = await _expand(db_session, seeded, [file_seed(seeded, APP, fused_score=1.0)])

    defines = found[0].text.splitlines()[-1]
    assert defines == "Defines: " + ", ".join(f"fn_{i:02d}" for i in range(15))
    assert "CONST" not in found[0].text


# --- the neighbour query agrees with the edge iterator ---------------------------


async def test_neighbours_agree_with_iter_file_edges_for_every_file(db_session, engine):
    seeded = await seed_repo(db_session, await make_user(db_session), GRAPH_SPEC)
    all_ids = [file.id for file in seeded.files.values()]

    neighbours = await query_neighbours_async(
        db_session, seeded.repo.id, all_ids, through_barrels=False
    )

    # ``iter_file_edges`` is the sync iterator over the same join. Its rows are read
    # through the async session's connection, so the uncommitted fixture is visible.
    def collect(sync_session):
        return list(iter_file_edges(sync_session, seeded.repo.id))

    edges = await db_session.run_sync(collect)
    expected: dict[tuple, int] = {}
    for src, tgt in edges:
        if src == tgt:
            continue
        expected[(src, tgt)] = expected.get((src, tgt), 0) + 1
        expected[(tgt, src)] = expected.get((tgt, src), 0) + 1

    assert {(seed, other): weight for seed, other, weight in neighbours} == expected
    assert expected, "the fixture must have edges or the comparison is vacuous"


async def test_a_dependency_into_another_repository_is_not_a_neighbour(db_session):
    user = await make_user(db_session)
    first = await seed_repo(db_session, user, GRAPH_SPEC, name="first")
    second = await seed_repo(db_session, user, GRAPH_SPEC, name="second")
    await db_session.execute(
        text(
            "INSERT INTO dependencies (source_symbol_id, target_symbol_id, dep_type) "
            "SELECT s.id, t.id, 'imports' FROM ast_symbols s, ast_symbols t "
            "WHERE s.file_id = :src AND s.kind = 'function' AND s.name = 'list_users' "
            "AND t.file_id = :tgt AND t.name = 'compute_total'"
        ),
        {"src": first.files[ROUTES].id, "tgt": second.files[INVOICE].id},
    )

    rows = await query_neighbours_async(db_session, first.repo.id, [first.files[ROUTES].id])

    assert {other for _, other, _ in rows} == {first.files[SERVICE].id}
