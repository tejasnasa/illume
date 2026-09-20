"""Import-to-file matching.

The public entry points need a database, so they are covered by integration tests. What
is tested here is the matching logic, which decides whether an import resolves to the
right file at all. It is pure: `File`-shaped or plain ``(id, path, language)`` tuples
constructed in memory and never persisted.
"""

import typing
import uuid

import pytest

from app.services.dependency_resolver import (
    _build_stem_indexes,
    _disambiguate_candidates,
    _match_file,
)

pytestmark = pytest.mark.unit


class TestAnnotationIntegrity:
    """
    Guard against annotation-only names that are never imported.

    `uuid` was missing from this module's imports and `Path` from `scanner.py`. Python
    3.14 defers annotation evaluation (PEP 649), so the omission is invisible until
    something resolves the annotations -- which is what FastAPI, pydantic, and
    dataclasses do.
    """

    def test_public_annotations_resolve(self):
        from app.services.dependency_resolver import (
            compute_fan_metrics,
            resolve_dependencies,
        )

        for fn in (resolve_dependencies, compute_fan_metrics):
            typing.get_type_hints(fn)

    def test_scanner_annotations_resolve(self):
        """`scanner.py` was worse than latent: it called `Path()` at runtime."""
        from app.services.scanner import (
            process_repository_files,
            walk_source_files,
        )

        for fn in (process_repository_files, walk_source_files):
            typing.get_type_hints(fn)


def _row(path: str, language: str = "python") -> tuple[uuid.UUID, str, str]:
    """
    An in-memory triple carrying only the fields the matcher reads.

    The resolver used to project these out of ``File`` ORM rows. The matchers
    never needed anything else, so the tests were updated to assert against
    tuples directly -- the unit under test only cares about ``path`` and
    ``language``.
    """
    return (uuid.uuid4(), path, language)


def _map_by_path(items: list[tuple[uuid.UUID, str, str]]) -> dict[uuid.UUID, str]:
    return {fid: path for fid, path, _ in items}


def _map_by_lang(items: list[tuple[uuid.UUID, str, str]]) -> dict[uuid.UUID, str]:
    return {fid: lang for fid, _path, lang in items}


class TestStemIndexes:
    def test_indexes_by_full_stem(self):
        f = _row("src/app/core/config.py")
        full, _, _ = _build_stem_indexes([f])

        assert full["src/app/core/config"] == f[0]

    def test_indexes_without_the_top_level_directory(self):
        """Tolerates an unknown source root: `app/core/config` as well as the full path."""
        f = _row("src/app/core/config.py")
        full, _, _ = _build_stem_indexes([f])

        assert full["app/core/config"] == f[0]

    def test_indexes_by_bare_filename_stem(self):
        f = _row("src/deep/helpers.py")
        _, short, _ = _build_stem_indexes([f])

        assert short["helpers"] == [f[0]]

    def test_collects_every_file_sharing_a_filename(self):
        a = _row("src/a/utils.py")
        b = _row("src/b/utils.py")
        _, short, _ = _build_stem_indexes([a, b])

        assert set(short["utils"]) == {a[0], b[0]}

    def test_maps_a_package_directory_to_its_dunder_init(self):
        pkg = _row("src/pkg/__init__.py")
        _, _, index = _build_stem_indexes([pkg])

        assert index["src/pkg"] == pkg[0]

    def test_maps_a_package_directory_to_its_index_module(self):
        pkg = _row("src/pkg/index.ts", language="typescript")
        _, _, index = _build_stem_indexes([pkg])

        assert index["src/pkg"] == pkg[0]

    def test_index_entries_are_also_stripped_of_the_top_level(self):
        pkg = _row("src/pkg/__init__.py")
        _, _, index = _build_stem_indexes([pkg])

        assert index["pkg"] == pkg[0]

    def test_windows_separators_are_normalised(self):
        f = _row("src\\app.py")
        full, _, _ = _build_stem_indexes([f])

        assert full["src/app"] == f[0]

    def test_empty_input_produces_empty_indexes(self):
        full, short, index = _build_stem_indexes([])

        assert (full, short, index) == ({}, {}, {})


class TestMatchFile:
    def test_exact_stem_match_wins(self):
        target = _row("src/app/core/config.py")
        full, short, index = _build_stem_indexes([target])

        assert (
            _match_file(
                "src/app/core/config",
                "python",
                full,
                short,
                index,
                path_by_id=_map_by_path([target]),
                language_by_id=_map_by_lang([target]),
            )
            == target[0]
        )

    def test_package_directory_resolves_through_the_index_map(self):
        pkg = _row("src/pkg/__init__.py")
        full, short, index = _build_stem_indexes([pkg])

        assert (
            _match_file(
                "src/pkg",
                "python",
                full,
                short,
                index,
                path_by_id=_map_by_path([pkg]),
                language_by_id=_map_by_lang([pkg]),
            )
            == pkg[0]
        )

    def test_unique_bare_filename_resolves(self):
        target = _row("src/deep/helpers.py")
        full, short, index = _build_stem_indexes([target])

        assert (
            _match_file(
                "helpers",
                "python",
                full,
                short,
                index,
                path_by_id=_map_by_path([target]),
                language_by_id=_map_by_lang([target]),
            )
            == target[0]
        )

    def test_ambiguous_filename_is_resolved_by_language(self):
        py = _row("src/a/utils.py", language="python")
        ts = _row("src/b/utils.ts", language="typescript")
        items = [py, ts]
        full, short, index = _build_stem_indexes(items)

        matched = _match_file(
            "utils",
            "python",
            full,
            short,
            index,
            path_by_id=_map_by_path(items),
            language_by_id=_map_by_lang(items),
        )

        assert matched == py[0]

    def test_unresolvable_specifier_returns_none(self):
        target = _row("src/app.py")
        full, short, index = _build_stem_indexes([target])

        assert (
            _match_file(
                "nowhere/at/all",
                "python",
                full,
                short,
                index,
                path_by_id=_map_by_path([target]),
                language_by_id=_map_by_lang([target]),
            )
            is None
        )

    def test_no_files_at_all_returns_none(self):
        assert (
            _match_file(
                "anything",
                "python",
                {},
                {},
                {},
                path_by_id={},
                language_by_id={},
            )
            is None
        )


class TestDisambiguation:
    def test_language_family_narrows_candidates(self):
        py = _row("src/a/utils.py", language="python")
        ts = _row("src/b/utils.ts", language="typescript")

        assert (
            _disambiguate_candidates(
                [py[0], ts[0]],
                "typescript",
                "utils",
                _map_by_path([py, ts]),
                _map_by_lang([py, ts]),
            )
            == ts[0]
        )

    def test_exact_suffix_match_is_preferred(self):
        """A candidate whose stem ends with the specifier beats an arbitrary sibling."""
        near = _row("src/ui/components/button.py")
        exact = _row("src/other/button.py")
        deep = _row("src/ui/widgets/button.py")
        items = [near, exact, deep]

        matched = _disambiguate_candidates(
            [near[0], exact[0], deep[0]],
            "python",
            "components/button",
            _map_by_path(items),
            _map_by_lang(items),
        )

        assert matched == near[0]

    def test_longest_trailing_segment_overlap_wins(self):
        """
        Scoring only runs when no candidate ends with the specifier -- an `endswith`
        hit returns immediately. These two both fail that check, so the reversed
        segment walk decides: `button/x` shares two trailing segments, `a/x` only one.
        """
        shallow = _row("src/a/x.py")
        deep = _row("src/button/x.py")
        items = [shallow, deep]

        matched = _disambiguate_candidates(
            [shallow[0], deep[0]],
            "python",
            "ui/button/x",
            _map_by_path(items),
            _map_by_lang(items),
        )

        assert matched == deep[0]

    def test_an_endswith_match_wins_before_scoring(self):
        """Order matters: the first candidate ending with the specifier is taken."""
        ends_with = _row("src/other/a/b/thing.py")
        longer_path = _row("src/a/b/thing.py")
        items = [ends_with, longer_path]

        matched = _disambiguate_candidates(
            [ends_with[0], longer_path[0]],
            "python",
            "a/b/thing",
            _map_by_path(items),
            _map_by_lang(items),
        )

        assert matched == ends_with[0]

    def test_no_overlap_at_all_returns_none(self):
        left = _row("src/x/thing.py")
        right = _row("src/y/thing.py")
        items = [left, right]

        assert (
            _disambiguate_candidates(
                [left[0], right[0]],
                "python",
                "zzz",
                _map_by_path(items),
                _map_by_lang(items),
            )
            is None
        )

    def test_a_single_candidate_is_returned_directly(self):
        only = _row("src/x/thing.py")

        assert (
            _disambiguate_candidates(
                [only[0]],
                "python",
                "anything",
                _map_by_path([only]),
                _map_by_lang([only]),
            )
            == only[0]
        )

    def test_falls_back_to_all_candidates_when_the_language_filter_empties_them(self):
        """A python importer matching only ts files should still resolve something."""
        ts = _row("src/x/thing.ts", language="typescript")

        assert (
            _disambiguate_candidates(
                [ts[0]],
                "python",
                "thing",
                _map_by_path([ts]),
                _map_by_lang([ts]),
            )
            == ts[0]
        )

    def test_unknown_language_does_not_filter(self):
        py = _row("src/a/thing.py", language="python")
        go = _row("src/b/thing.go", language="go")
        items = [py, go]

        matched = _disambiguate_candidates(
            [py[0], go[0]],
            "ruby",
            "thing",
            _map_by_path(items),
            _map_by_lang(items),
        )

        assert matched in {py[0], go[0]}
