"""Structural gold against a hand-computed import graph in a rolled-back session."""

from dataclasses import replace

import pytest

from evals.gold.schema import write_jsonl
from evals.gold.structural import build_structural_items, reaches, shortest_unique_paths
from tests.factories import make_user
from tests.fixtures.retrieval import FileSpec, ImportSpec, RepoSpec, SymbolSpec, seed_repo

pytestmark = pytest.mark.integration

BASE = "b" * 40

# A -> B, X -> B, Y -> B, B -> C -> D -> E <- F. G reaches J two equally short ways, and
# K -> L -> M -> K is a cycle, so K, L and M reach each other in both directions.
EDGES = [
    ("A", "B"),
    ("X", "B"),
    ("Y", "B"),
    ("B", "C"),
    ("C", "D"),
    ("D", "E"),
    ("F", "E"),
    ("G", "H"),
    ("G", "I"),
    ("H", "J"),
    ("I", "J"),
    ("K", "L"),
    ("L", "M"),
    ("M", "K"),
]


def _path(name: str) -> str:
    return f"app/{name.lower()}.py"


SPEC = RepoSpec(
    files=tuple(
        FileSpec(path=_path(name), symbols=(SymbolSpec(name=f"fn_{name.lower()}"),))
        for name in "ABCDEFGHIJKLMXY"
    ),
    imports=tuple(ImportSpec(_path(a), _path(b)) for a, b in EDGES),
)

IMPORTERS = {
    _path("B"): tuple(sorted(_path(n) for n in "AXY")),
    _path("E"): tuple(sorted(_path(n) for n in "DF")),
    _path("J"): tuple(sorted(_path(n) for n in "HI")),
}
# Source, target and the files on the one shortest chain between them.
CHAINS = {
    ("A", "C"): "ABC",
    ("A", "D"): "ABCD",
    ("A", "E"): "ABCDE",
    ("X", "C"): "XBC",
    ("X", "D"): "XBCD",
    ("X", "E"): "XBCDE",
    ("Y", "C"): "YBC",
    ("Y", "D"): "YBCD",
    ("Y", "E"): "YBCDE",
    ("B", "D"): "BCD",
    ("B", "E"): "BCDE",
    ("C", "E"): "CDE",
}
PATH_GOLD = {tuple(sorted(_path(n) for n in chain)) for chain in CHAINS.values()}


async def _build(db_session, **kw):
    seeded = await seed_repo(db_session, await make_user(db_session), SPEC)
    return await build_structural_items(
        db_session,
        repo_name="graph",
        repo_id=seeded.repo.id,
        base_commit=BASE,
        seed=0,
        **kw,
    )


async def test_importer_gold_is_the_set_of_files_that_import_the_file(db_session):
    items = await _build(db_session, n_importers=5, n_paths=0)
    assert {item.template for item in items} == {"structural.importers"}
    by_file = {item.question_seed: item.gold_files for item in items}
    assert len(items) == 3
    for path, gold in IMPORTERS.items():
        assert by_file[f"What breaks if `{path}` changes? Which files depend on it?"] == gold


async def test_path_gold_is_the_unique_shortest_chain_including_endpoints(db_session):
    items = await _build(db_session, n_importers=0, n_paths=100)
    assert {item.template for item in items} == {"structural.path"}
    assert {item.gold_files for item in items} == PATH_GOLD
    assert all(3 <= len(item.gold_files) <= 5 for item in items)


async def test_a_pair_with_two_shortest_chains_or_a_shorter_way_back_is_never_used(db_session):
    items = await _build(db_session, n_importers=0, n_paths=100)
    questions = " ".join(item.question_seed for item in items)
    for banned in ("app/j.py", "app/k.py", "app/l.py", "app/m.py"):
        assert banned not in questions


async def test_every_structural_item_is_circular_with_the_graph(db_session):
    items = await _build(db_session, n_importers=5, n_paths=3)
    assert len(items) == 6
    assert all(item.family == "structural" for item in items)
    assert all(item.circular_with == ("graph",) for item in items)
    assert all(item.anchor_file is None and item.cluster is None for item in items)


async def test_the_choice_is_deterministic(db_session, tmp_path):
    first = await _build(db_session, n_importers=1, n_paths=2)
    second = await _build(db_session, n_importers=1, n_paths=2)
    assert len(first) == 3
    assert (
        write_jsonl(tmp_path / "a.jsonl", first).read_bytes()
        == write_jsonl(tmp_path / "b.jsonl", second).read_bytes()
    )


async def test_a_file_with_one_importer_is_not_asked_about(db_session):
    spec = replace(SPEC, imports=(ImportSpec(_path("A"), _path("B")),))
    seeded = await seed_repo(db_session, await make_user(db_session), spec, name="single")
    items = await build_structural_items(
        db_session, repo_name="single", repo_id=seeded.repo.id, base_commit=BASE, seed=0
    )
    assert items == []


def test_the_search_helpers_on_a_plain_mapping():
    deps = {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": ["e"]}
    assert shortest_unique_paths(deps, "a", 4) == {"b": ["a", "b"], "c": ["a", "c"]}
    assert shortest_unique_paths({"a": ["b"], "b": ["c"]}, "a", 1) == {"b": ["a", "b"]}
    assert reaches(deps, "a", "e", 3) and not reaches(deps, "a", "e", 2)
