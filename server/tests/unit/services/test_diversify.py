"""Diversification gives the same selection as the chat endpoint's long-standing function."""

from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from app.services.rag import TYPE_CAPS, _apply_diversity_caps
from app.services.retrieval.candidate import Candidate
from app.services.retrieval.config import DiversifyConfig
from app.services.retrieval.diversify import diversify
from app.services.retrieval.resolve import SourceReference

pytestmark = pytest.mark.unit

TYPES = ["symbol", "commit", "pull_request", "document", "file"]


def _candidate(index: int, source_type: str) -> Candidate:
    return Candidate(
        key=f"k{index}",
        reference=SourceReference(source_type=source_type, chunk_text=str(index)),
        text=str(index),
    )


def _sequence(rng: random.Random, length: int, types: list[str]) -> list[Candidate]:
    return [_candidate(i, rng.choice(types)) for i in range(length)]


def test_defaults_are_the_chat_endpoints_caps():
    assert DiversifyConfig().caps() == TYPE_CAPS


@pytest.mark.parametrize("seed", range(50))
def test_selection_matches_the_existing_function(seed):
    rng = random.Random(seed)
    # Skew the type pool some runs so one type overflows its cap and exercises the backfill.
    pool = TYPES + ["unknown"] if seed % 3 else ["symbol", "symbol", "symbol", "commit"]
    candidates = _sequence(rng, rng.randint(0, 40), pool)
    total = rng.randint(1, 25)

    # The old function reads ``source_type`` off the embedding row; the same
    # attribute name on a stand-in keeps the comparison about the algorithm.
    rows = [SimpleNamespace(source_type=c.source_type, key=c.key) for c in candidates]
    expected = [row.key for row in _apply_diversity_caps(rows, total)]

    config = DiversifyConfig(total=total)
    assert [c.key for c in diversify(candidates, config)] == expected


def test_caps_come_from_the_config():
    candidates = [_candidate(i, "symbol") for i in range(3)] + [_candidate(9, "commit")]
    tight = DiversifyConfig(total=3, symbol=1, commit=1)
    # Pass 1 takes one symbol and the commit; pass 2 backfills the next symbol.
    assert [c.key for c in diversify(candidates, tight)] == ["k0", "k9", "k1"]


def test_unknown_types_use_the_other_cap():
    candidates = [_candidate(i, "mystery") for i in range(4)] + [_candidate(8, "symbol")]
    config = DiversifyConfig(total=3, other=1)
    assert [c.key for c in diversify(candidates, config)] == ["k0", "k8", "k1"]


def test_caps_are_soft_so_one_type_can_fill_the_list():
    candidates = [_candidate(i, "symbol") for i in range(10)]
    config = DiversifyConfig(total=8, symbol=2)
    assert [c.key for c in diversify(candidates, config)] == [f"k{i}" for i in range(8)]


def test_stops_at_total_and_returns_fewer_when_short():
    candidates = [_candidate(i, "symbol") for i in range(3)]
    assert len(diversify(candidates, DiversifyConfig(total=2))) == 2
    assert len(diversify(candidates, DiversifyConfig(total=10))) == 3
    assert diversify([], DiversifyConfig()) == []


def test_the_input_is_not_modified():
    candidates = [_candidate(i, "symbol") for i in range(5)]
    before = list(candidates)
    diversify(candidates, DiversifyConfig(total=2))
    assert candidates == before
