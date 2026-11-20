"""Retrieval metrics: key-to-file mapping and ranking properties."""

import random

import pytest

from app.services.retrieval.citations import (
    code_key,
    commit_key,
    document_key,
    pull_request_key,
)
from evals.metrics.retrieval import (
    Ranking,
    first_touch_ranking,
    key_file,
    mrr,
    ndcg_at_k,
    ranked_files,
    recall_at_k,
)
from tests.evals.metric_helpers import make_candidate, make_step

pytestmark = pytest.mark.unit

KS = (1, 2, 3, 5, 10, 20)


@pytest.mark.parametrize(
    ("key", "path"),
    [
        (code_key("server/app/main.py", 3, 9), "server/app/main.py"),
        (code_key("server/app/main.py"), "server/app/main.py"),
        ("[F:app/main.py:3-9]", "app/main.py"),
        ("F:app/main.py:7", "app/main.py"),
        ("F:./app\\main.py", "app/main.py"),
        ("F:app/repo/[id]/page.tsx:1-4", "app/repo/[id]/page.tsx"),
    ],
)
def test_every_code_key_form_maps_to_its_file(key, path):
    assert key_file(key) == (path, False)


@pytest.mark.parametrize(
    "key",
    [commit_key("a1b2c3d4e5"), pull_request_key(142), document_key("Installation"), "PR:#9"],
)
def test_keys_without_a_file_are_unmapped_not_malformed(key):
    assert key_file(key) == (None, False)
    assert ranked_files([make_candidate(key, 1)]) == Ranking(files=(), unmapped=1, malformed=0)


@pytest.mark.parametrize(
    "key", ["", "garbage", "F:", "F::3-4", "PR:0", "C:zzz", "D:nohash", "X:a:b"]
)
def test_a_malformed_key_is_counted_and_never_raises(key):
    assert key_file(key) == (None, True)
    assert ranked_files([make_candidate(key, 1)]) == Ranking(files=(), unmapped=0, malformed=1)


def test_a_candidate_file_path_places_a_non_code_key():
    assert ranked_files([make_candidate("PR:7", 1, file_path="a.py")]).files == ("a.py",)


def test_the_anchor_can_be_left_out_of_a_ranking():
    candidates = [make_candidate("F:a.py", 1), make_candidate("F:b.py", 2)]
    assert ranked_files(candidates, exclude={"a.py"}).files == ("b.py",)


def test_first_touch_counts_non_file_evidence():
    steps = [make_step(0, "seed", evidence_keys=["C:abcd1234", "F:a.py:1-2", "nonsense"])]
    assert first_touch_ranking(steps) == Ranking(files=("a.py",), unmapped=1, malformed=1)


def test_read_arguments_given_as_a_python_repr_are_understood():
    steps = [make_step(0, tool="read_file", arguments="{'path': 'src/a.py', 'start_line': 3}")]
    assert first_touch_ranking(steps).files == ("src/a.py",)


def _random_case(rng: random.Random):
    universe = [f"f{i}.py" for i in range(30)]
    ranking = rng.sample(universe, rng.randint(0, 30))
    gold = set(rng.sample(universe, rng.randint(1, 8)))
    return ranking, gold


def test_recall_never_falls_as_k_rises():
    rng = random.Random(20260101)
    for _ in range(400):
        ranking, gold = _random_case(rng)
        values = [recall_at_k(ranking, gold, k) for k in range(1, 31)]
        assert all(v is not None and 0.0 <= v <= 1.0 for v in values)
        assert values == sorted(values)


def test_a_perfect_ranking_has_ndcg_one():
    rng = random.Random(7)
    universe = [f"f{i}.py" for i in range(30)]
    for _ in range(300):
        gold = set(rng.sample(universe, rng.randint(1, 8)))
        others = [f for f in universe if f not in gold]
        rng.shuffle(others)
        ranking = sorted(gold, key=lambda _: rng.random()) + others
        for k in KS:
            assert ndcg_at_k(ranking, gold, k) == pytest.approx(1.0)
            assert recall_at_k(ranking, gold, k) == pytest.approx(min(k, len(gold)) / len(gold))


def test_mrr_and_ndcg_stay_in_the_unit_interval():
    rng = random.Random(99)
    for _ in range(400):
        ranking, gold = _random_case(rng)
        value = mrr(ranking, gold)
        assert value is not None and 0.0 <= value <= 1.0
        for k in KS:
            ndcg = ndcg_at_k(ranking, gold, k)
            assert ndcg is not None and 0.0 <= ndcg <= 1.0 + 1e-12


def test_moving_a_gold_file_earlier_never_lowers_ndcg():
    rng = random.Random(5)
    for _ in range(300):
        ranking, gold = _random_case(rng)
        hits = [i for i, f in enumerate(ranking) if f in gold and i > 0]
        if not hits:
            continue
        i = rng.choice(hits)
        better = ranking[:]
        better[i - 1], better[i] = better[i], better[i - 1]
        for k in KS:
            assert ndcg_at_k(better, gold, k) >= ndcg_at_k(ranking, gold, k) - 1e-12
