"""Reading-order topology: deterministic sort + cycle handling.

Unit tests for :func:`app.services.onboarding._topological_sort`. The
integration suite (test_ingest_task.py) covers end-to-end persistence; this
file pins the algorithm itself, including the determinism invariant that
matters for the frontend click-through tour.
"""

import logging

import pytest

from app.services.onboarding import _FileInfo, _topological_sort

pytestmark = pytest.mark.unit


def _fi(path: str, fan_in: int = 0) -> _FileInfo:
    """Shorthand for building file metadata."""
    return _FileInfo(path=path, fan_in=fan_in)


def _ids(path_to_int: dict[str, int]) -> dict[int, _FileInfo]:
    """Inverse direction of the ``int_by_uuid`` map: build ``files_by_int``."""
    return {i: _FileInfo(path=p, fan_in=0) for p, i in path_to_int.items()}


class TestTopologicalSort:
    """Tier structure: each tier holds the files unblocked by the previous one."""

    def test_files_with_no_dependencies_share_the_first_tier(self):
        """An isolated file lands in tier 0 -- nothing depends on it, it depends on nothing."""
        files = _ids({"a": 0, "b": 1})
        deps: dict[int, set[int]] = {0: set(), 1: set()}
        rdeps: dict[int, set[int]] = {0: set(), 1: set()}

        tiers = _topological_sort(files, deps, rdeps)

        assert len(tiers) == 1
        assert set(tiers[0]) == {0, 1}

    def test_a_dependent_file_lands_in_a_later_tier(self):
        """b depends on a -> a in tier 0, b in tier 1."""
        files = _ids({"a": 0, "b": 1})
        deps = {0: set(), 1: {0}}
        rdeps = {0: {1}, 1: set()}

        tiers = _topological_sort(files, deps, rdeps)

        assert len(tiers) == 2
        assert tiers[0] == [0]
        assert tiers[1] == [1]

    def test_a_chain_orders_every_file_into_its_own_tier(self):
        """a -> b -> c -> d: each tier has exactly one file."""
        files = _ids({"a": 0, "b": 1, "c": 2, "d": 3})
        deps = {0: set(), 1: {0}, 2: {1}, 3: {2}}
        rdeps = {0: {1}, 1: {2}, 2: {3}, 3: set()}

        tiers = _topological_sort(files, deps, rdeps)

        assert tiers == [[0], [1], [2], [3]]

    def test_a_diamond_collapses_to_two_tiers(self):
        """
        a -> b, a -> c, b -> d, c -> d. b and c share tier 1 (both
        unblocked by a) and d lands in tier 2.
        """
        files = _ids({"a": 0, "b": 1, "c": 2, "d": 3})
        deps = {0: set(), 1: {0}, 2: {0}, 3: {1, 2}}
        rdeps = {0: {1, 2}, 1: {3}, 2: {3}, 3: set()}

        tiers = _topological_sort(files, deps, rdeps)

        assert tiers[0] == [0]
        assert sorted(tiers[1]) == [1, 2]
        assert tiers[2] == [3]


class TestCycleHandling:
    """A dependency cycle must not drop files from the guide."""

    def test_a_two_file_cycle_lands_in_the_final_tier(self):
        files = _ids({"a": 0, "b": 1})
        deps = {0: {1}, 1: {0}}
        rdeps = {0: {1}, 1: {0}}

        tiers = _topological_sort(files, deps, rdeps)

        # No file is ever dequeued, so the cycle catch-all is the only tier.
        assert len(tiers) == 1
        assert sorted(tiers[0]) == [0, 1]

    def test_a_cycle_alongside_a_dag(self, caplog):
        """
        x -> a -> b, and a <-> y. The DAG component (x) is dequeued
        normally; the cycle between a and y pulls a, b, and y into the
        catch-all, because b depends on a and a still has y on its
        outgoing list.

        The warning's count is what matters -- it should match the size
        of the catch-all tier.
        """
        files = _ids({"x": 0, "a": 1, "b": 2, "y": 3})
        deps = {0: set(), 1: {0, 3}, 2: {1}, 3: {1}}
        rdeps = {0: {1}, 1: {2, 3}, 2: set(), 3: {1}}

        with caplog.at_level(logging.WARNING, logger="app.services.onboarding"):
            tiers = _topological_sort(files, deps, rdeps)

        assert tiers[0] == [0]
        assert len(tiers) == 2
        assert sorted(tiers[1]) == [1, 2, 3]

        cycle_warnings = [r for r in caplog.records if "dependency cycle" in r.getMessage()]
        assert len(cycle_warnings) == 1
        assert "3 files" in cycle_warnings[0].getMessage()


class TestDeterminism:
    """The sort key is ``(-fan_in, path)`` so output is byte-identical across runs."""

    def test_within_a_tier_files_are_sorted_by_negative_fan_in(self):
        """Most-imported file first within a tier."""
        files = _ids({"low": 0, "high": 1, "mid": 2})
        # All in tier 0 (no dependencies). Different fan_in values.
        files[0] = _FileInfo(path="low", fan_in=1)
        files[1] = _FileInfo(path="high", fan_in=10)
        files[2] = _FileInfo(path="mid", fan_in=5)
        deps = {0: set(), 1: set(), 2: set()}
        rdeps = {0: set(), 1: set(), 2: set()}

        tiers = _topological_sort(files, deps, rdeps)

        assert tiers[0] == [1, 2, 0]  # high (10), mid (5), low (1)

    def test_within_a_tier_files_with_equal_fan_in_break_ties_by_path(self):
        """
        The nondeterminism regression. With every fan_in == 0 the
        previous code's sort was stable but the candidate set was a
        ``set`` -- so output varied across runs. The new code's
        ``(-fan_in, path)`` key makes it byte-identical.
        """
        files = _ids({"src/zebra.py": 0, "src/alpha.py": 1, "src/middle.py": 2})
        deps = {0: set(), 1: set(), 2: set()}
        rdeps = {0: set(), 1: set(), 2: set()}

        # Run twice and assert identical output.
        first = _topological_sort(files, deps, rdeps)
        second = _topological_sort(files, deps, rdeps)

        assert first == second
        # And the expected order: alpha, middle, zebra.
        assert first[0] == [1, 2, 0]

    def test_repeated_runs_are_byte_identical(self):
        """The full determinism guarantee: the whole tier list is stable."""
        files = _ids({f"src/m{i:02d}.py": i for i in range(20)})
        deps = {i: set() for i in range(20)}
        rdeps = {i: set() for i in range(20)}

        runs = [_topological_sort(files, deps, rdeps) for _ in range(5)]

        for run in runs[1:]:
            assert run == runs[0]
