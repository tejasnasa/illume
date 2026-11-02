"""Weighted reciprocal rank fusion: the arithmetic, the merge rules, and ``none``."""

from __future__ import annotations

import pytest

from app.services.retrieval.candidate import Candidate, ChannelHit
from app.services.retrieval.fusion import (
    RankedList,
    fuse,
    reciprocal_rank_fusion,
    rrf_score,
    single_list,
)
from app.services.retrieval.resolve import SourceReference

pytestmark = pytest.mark.unit

K = 60


def _candidate(key: str, channel: str, variant: int, rank: int, **fields) -> Candidate:
    """A candidate as a channel returns it: one hit, text naming its origin."""
    reference = SourceReference(
        source_type="file", chunk_text=f"{key} via {channel}/{variant}", file_path=key
    )
    return Candidate(
        key=key,
        reference=reference,
        text=f"{key} via {channel}/{variant}",
        channel_hits=(ChannelHit(channel, variant, rank, raw_score=float(rank)),),
        **fields,
    )


def _list(channel: str, keys: list[str], *, variant: int = 0, weight: float = 1.0) -> RankedList:
    return RankedList(
        channel,
        variant,
        weight,
        tuple(_candidate(key, channel, variant, rank) for rank, key in enumerate(keys, start=1)),
    )


def _scores(merged: list[Candidate]) -> dict[str, float]:
    return {candidate.key: candidate.fused_score for candidate in merged}


class TestArithmetic:
    def test_one_list_scores_by_rank(self):
        merged = reciprocal_rank_fusion([_list("dense", ["a", "b", "c"])], rrf_k=K)
        assert [c.key for c in merged] == ["a", "b", "c"]
        assert _scores(merged) == pytest.approx({"a": 1 / 61, "b": 1 / 62, "c": 1 / 63})

    def test_a_candidate_found_by_three_lists_sums_all_three(self):
        lists = [
            _list("dense", ["x", "a"]),
            _list("lexical", ["b", "x"]),
            _list("symbol", ["c", "d", "x"]),
        ]
        scores = _scores(reciprocal_rank_fusion(lists, rrf_k=K))
        assert scores["x"] == pytest.approx(1 / 61 + 1 / 62 + 1 / 63)
        # x outranks every candidate that only one list found, at any rank.
        assert max(score for key, score in scores.items() if key != "x") < scores["x"]

    def test_weights_scale_each_lists_contribution(self):
        lists = [_list("dense", ["a"], weight=2.0), _list("lexical", ["b"], weight=0.5)]
        scores = _scores(reciprocal_rank_fusion(lists, rrf_k=K))
        assert scores == pytest.approx({"a": 2.0 / 61, "b": 0.5 / 61})

    def test_variants_of_one_channel_are_separate_equally_weighted_lists(self):
        lists = [
            _list("dense", ["a", "b"], variant=0, weight=3.0),
            _list("dense", ["b", "a"], variant=1, weight=3.0),
        ]
        scores = _scores(reciprocal_rank_fusion(lists, rrf_k=K))
        assert scores["a"] == pytest.approx(3.0 / 61 + 3.0 / 62)
        assert scores["a"] == pytest.approx(scores["b"])

    def test_rrf_k_changes_the_offset(self):
        merged = reciprocal_rank_fusion([_list("dense", ["a"])], rrf_k=10)
        assert merged[0].fused_score == pytest.approx(rrf_score(1.0, 1, 10))

    def test_ties_are_broken_by_key(self):
        # a and b swap places across the lists, so their scores are exactly equal.
        lists = [_list("dense", ["b", "a"]), _list("lexical", ["a", "b"])]
        merged = reciprocal_rank_fusion(lists, rrf_k=K)
        assert merged[0].fused_score == merged[1].fused_score
        assert [c.key for c in merged] == ["a", "b"]

    def test_output_does_not_depend_on_the_order_of_the_lists(self):
        lists = [
            _list("dense", ["a", "b", "c"]),
            _list("lexical", ["c", "a", "d"], weight=1.5),
            _list("symbol", ["d", "e"], weight=0.7),
        ]
        forward = reciprocal_rank_fusion(lists, rrf_k=K)
        backward = reciprocal_rank_fusion(lists[::-1], rrf_k=K)
        assert [(c.key, c.fused_score) for c in forward] == [
            (c.key, c.fused_score) for c in backward
        ]
        assert [c.channel_hits for c in forward] == [c.channel_hits for c in backward]

    def test_a_key_repeated_inside_one_list_counts_once(self):
        ranked = RankedList(
            "dense",
            0,
            1.0,
            (
                _candidate("a", "dense", 0, 1),
                _candidate("a", "dense", 0, 2),
                _candidate("b", "dense", 0, 3),
            ),
        )
        scores = _scores(reciprocal_rank_fusion([ranked], rrf_k=K))
        assert scores["a"] == pytest.approx(1 / 61)

    def test_no_lists_is_empty(self):
        assert reciprocal_rank_fusion([], rrf_k=K) == []


class TestMerge:
    def test_channel_hits_are_unioned_in_a_stable_order(self):
        lists = [
            _list("symbol", ["x"]),
            _list("dense", ["a", "x"], variant=1),
            _list("dense", ["x"], variant=0),
        ]
        merged = {c.key: c for c in reciprocal_rank_fusion(lists, rrf_k=K)}["x"]
        assert [(h.channel, h.variant, h.rank) for h in merged.channel_hits] == [
            ("dense", 0, 1),
            ("dense", 1, 2),
            ("symbol", 0, 1),
        ]

    def test_the_best_ranked_appearance_supplies_the_text_and_fields(self):
        file_a = _candidate("x", "lexical", 0, 1, provenance="history")
        worse = _candidate("x", "dense", 0, 5, provenance="repo")
        merged = reciprocal_rank_fusion(
            [
                RankedList(
                    "dense",
                    0,
                    1.0,
                    (*[_candidate(f"f{i}", "dense", 0, i) for i in range(1, 5)], worse),
                ),
                RankedList("lexical", 0, 1.0, (file_a,)),
            ],
            rrf_k=K,
        )
        x = next(c for c in merged if c.key == "x")
        assert x.text == "x via lexical/0"
        assert x.provenance == "history"
        assert len(x.channel_hits) == 2

    def test_a_rank_tie_goes_to_the_channel_kind_then_the_variant(self):
        lists = [
            _list("lexical", ["x"], variant=0),
            _list("dense", ["x"], variant=1),
            _list("dense", ["x"], variant=0),
        ]
        assert reciprocal_rank_fusion(lists, rrf_k=K)[0].text == "x via dense/0"
        lists = [_list("lexical", ["x"]), _list("dense", ["x"], variant=2)]
        assert reciprocal_rank_fusion(lists, rrf_k=K)[0].text == "x via dense/2"

    def test_source_and_file_ids_follow_the_surviving_appearance(self):
        from uuid import uuid4

        winner, loser = uuid4(), uuid4()
        best = _candidate("x", "dense", 0, 1, file_id=winner, source_id=winner)
        other = _candidate("x", "lexical", 0, 2, file_id=loser, source_id=loser)
        merged = reciprocal_rank_fusion(
            [
                RankedList("dense", 0, 1.0, (best,)),
                RankedList("lexical", 0, 1.0, (_candidate("y", "lexical", 0, 1), other)),
            ],
            rrf_k=K,
        )
        x = next(c for c in merged if c.key == "x")
        assert (x.file_id, x.source_id) == (winner, winner)

    def test_the_inputs_are_not_modified(self):
        original = _candidate("x", "dense", 0, 1)
        reciprocal_rank_fusion([RankedList("dense", 0, 1.0, (original,))], rrf_k=K)
        assert original.fused_score is None


class TestNone:
    def test_passes_the_single_list_through_in_order_without_a_score(self):
        ranked = _list("dense", ["c", "a", "b"])
        merged = fuse([ranked], method="none", rrf_k=K)
        assert [c.key for c in merged] == ["c", "a", "b"]
        assert all(c.fused_score is None for c in merged)

    def test_a_failed_only_channel_gives_nothing(self):
        assert fuse([], method="none", rrf_k=K) == []

    def test_several_lists_are_refused(self):
        with pytest.raises(ValueError, match="single ranked list"):
            single_list([_list("dense", ["a"]), _list("lexical", ["b"])])

    def test_rrf_dispatch(self):
        merged = fuse([_list("dense", ["a"])], method="rrf", rrf_k=K)
        assert merged[0].fused_score == pytest.approx(1 / 61)
