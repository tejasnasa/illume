"""Import-to-file matching.

The public entry points need a database, so they are covered by integration tests. What
is tested here is the matching logic, which decides whether an import resolves to the
right file at all. It is pure: `File` and `AstSymbol` instances are constructed in memory
and never persisted.
"""

import typing

import pytest

from app.models import File
from app.services.dependency_resolver import (
    _build_stem_indexes,
    _disambiguate_candidates,
    _match_file,
)

pytestmark = pytest.mark.unit


def make_file(path: str, language: str = "python") -> File:
    """An unsaved File carrying only the fields the matcher reads."""
    return File(path=path, language=language)


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


class TestStemIndexes:
    def test_indexes_by_full_stem(self):
        f = make_file("src/app/core/config.py")
        full, _, _ = _build_stem_indexes([f])

        assert full["src/app/core/config"] is f

    def test_indexes_without_the_top_level_directory(self):
        """Tolerates an unknown source root: `app/core/config` as well as the full path."""
        f = make_file("src/app/core/config.py")
        full, _, _ = _build_stem_indexes([f])

        assert full["app/core/config"] is f

    def test_indexes_by_bare_filename_stem(self):
        f = make_file("src/deep/helpers.py")
        _, short, _ = _build_stem_indexes([f])

        assert short["helpers"] == [f]

    def test_collects_every_file_sharing_a_filename(self):
        a = make_file("src/a/utils.py")
        b = make_file("src/b/utils.py")
        _, short, _ = _build_stem_indexes([a, b])

        assert set(short["utils"]) == {a, b}

    def test_maps_a_package_directory_to_its_dunder_init(self):
        pkg = make_file("src/pkg/__init__.py")
        _, _, index = _build_stem_indexes([pkg])

        assert index["src/pkg"] is pkg

    def test_maps_a_package_directory_to_its_index_module(self):
        pkg = make_file("src/pkg/index.ts", language="typescript")
        _, _, index = _build_stem_indexes([pkg])

        assert index["src/pkg"] is pkg

    def test_index_entries_are_also_stripped_of_the_top_level(self):
        pkg = make_file("src/pkg/__init__.py")
        _, _, index = _build_stem_indexes([pkg])

        assert index["pkg"] is pkg

    def test_windows_separators_are_normalised(self):
        f = make_file("src\\app.py")
        full, _, _ = _build_stem_indexes([f])

        assert full["src/app"] is f

    def test_empty_input_produces_empty_indexes(self):
        full, short, index = _build_stem_indexes([])

        assert (full, short, index) == ({}, {}, {})


class TestMatchFile:
    def test_exact_stem_match_wins(self):
        target = make_file("src/app/core/config.py")
        full, short, index = _build_stem_indexes([target])

        assert _match_file("src/app/core/config", "python", full, short, index) is target

    def test_package_directory_resolves_through_the_index_map(self):
        pkg = make_file("src/pkg/__init__.py")
        full, short, index = _build_stem_indexes([pkg])

        assert _match_file("src/pkg", "python", full, short, index) is pkg

    def test_unique_bare_filename_resolves(self):
        target = make_file("src/deep/helpers.py")
        full, short, index = _build_stem_indexes([target])

        assert _match_file("helpers", "python", full, short, index) is target

    def test_ambiguous_filename_is_resolved_by_language(self):
        py = make_file("src/a/utils.py", language="python")
        ts = make_file("src/b/utils.ts", language="typescript")
        full, short, index = _build_stem_indexes([py, ts])

        matched = _match_file("utils", "python", full, short, index)

        assert matched is py

    def test_unresolvable_specifier_returns_none(self):
        full, short, index = _build_stem_indexes([make_file("src/app.py")])

        assert _match_file("nowhere/at/all", "python", full, short, index) is None

    def test_no_files_at_all_returns_none(self):
        assert _match_file("anything", "python", {}, {}, {}) is None


class TestDisambiguation:
    def test_language_family_narrows_candidates(self):
        py = make_file("src/a/utils.py", language="python")
        ts = make_file("src/b/utils.ts", language="typescript")

        assert _disambiguate_candidates([py, ts], "typescript", "utils") is ts

    def test_exact_suffix_match_is_preferred(self):
        """A candidate whose stem ends with the specifier beats an arbitrary sibling."""
        near = make_file("src/ui/components/button.py")
        exact = make_file("src/other/button.py")
        deep = make_file("src/ui/components/button.py".replace("components", "widgets"))

        matched = _disambiguate_candidates([near, exact, deep], "python", "components/button")

        assert matched is near

    def test_longest_trailing_segment_overlap_wins(self):
        """
        Scoring only runs when no candidate ends with the specifier -- an `endswith`
        hit returns immediately. These two both fail that check, so the reversed
        segment walk decides: `button/x` shares two trailing segments, `a/x` only one.
        """
        shallow = make_file("src/a/x.py")
        deep = make_file("src/button/x.py")

        matched = _disambiguate_candidates([shallow, deep], "python", "ui/button/x")

        assert matched is deep

    def test_an_endswith_match_wins_before_scoring(self):
        """Order matters: the first candidate ending with the specifier is taken."""
        ends_with = make_file("src/other/a/b/thing.py")
        longer_path = make_file("src/a/b/thing.py")

        matched = _disambiguate_candidates([ends_with, longer_path], "python", "a/b/thing")

        assert matched is ends_with

    def test_no_overlap_at_all_returns_none(self):
        left = make_file("src/x/thing.py")
        right = make_file("src/y/thing.py")

        assert _disambiguate_candidates([left, right], "python", "zzz") is None

    def test_a_single_candidate_is_returned_directly(self):
        only = make_file("src/x/thing.py")

        assert _disambiguate_candidates([only], "python", "anything") is only

    def test_falls_back_to_all_candidates_when_the_language_filter_empties_them(self):
        """A python importer matching only ts files should still resolve something."""
        ts = make_file("src/x/thing.ts", language="typescript")

        assert _disambiguate_candidates([ts], "python", "thing") is ts

    def test_unknown_language_does_not_filter(self):
        py = make_file("src/a/thing.py", language="python")
        go = make_file("src/b/thing.go", language="go")

        matched = _disambiguate_candidates([py, go], "ruby", "thing")

        assert matched in {py, go}
