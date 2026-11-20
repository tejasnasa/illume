"""Path normalisation and the base-commit existence split."""

import pytest

from evals.mining.github_cache import CachedPRFile
from evals.mining.paths import normalise_path, rename_map, resolve_pr_paths, split_by_existence


@pytest.mark.unit
class TestNormalisePath:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("src/app.py", "src/app.py"),
            (r"src\pkg\app.py", "src/pkg/app.py"),
            ("./src/app.py", "src/app.py"),
            (r".\src\app.py", "src/app.py"),
            ("/src/app.py", "src/app.py"),
            ("a/src/app.py", "src/app.py"),
            ("b/src/app.py", "src/app.py"),
            ("src//app.py", "src/app.py"),
            ("src/./app.py", "src/app.py"),
            ("  src/app.py\n", "src/app.py"),
            ("", ""),
            (".", ""),
        ],
    )
    def test_cases(self, raw, expected):
        assert normalise_path(raw) == expected

    def test_only_one_diff_prefix_is_removed(self):
        assert normalise_path("a/a/x.py") == "a/x.py"

    def test_a_real_directory_named_a_survives_when_prefix_stripping_is_off(self):
        assert normalise_path("a/x.py", strip_diff_prefix=False) == "a/x.py"

    def test_an_absolute_path_under_the_repo_root_becomes_relative(self):
        assert normalise_path(r"C:\work\repo\src\app.py", "C:/work/repo") == "src/app.py"
        assert normalise_path("/work/repo/src/app.py", "/work/repo/") == "src/app.py"


@pytest.mark.unit
class TestSplitByExistence:
    def test_present_and_absent_are_separated_in_order(self):
        present, absent = split_by_existence(
            ["b.py", "new.py", "a.py", "b.py", "newer.py"], {"a.py", "b.py"}
        )
        assert present == ["b.py", "a.py"]
        assert absent == ["new.py", "newer.py"]

    def test_empty_input(self):
        assert split_by_existence([], {"a.py"}) == ([], [])


@pytest.mark.unit
class TestResolvePrPaths:
    def test_a_rename_of_a_file_that_existed_resolves_to_the_old_path(self):
        files = [
            CachedPRFile("src/new_name.py", "renamed", "src/old_name.py", 0, 0),
            CachedPRFile("src/keep.py", "modified", None, 2, 1),
            CachedPRFile("src/brand_new.py", "added", None, 9, 0),
        ]
        present, absent = resolve_pr_paths(files, {"src/old_name.py", "src/keep.py"})
        assert present == ["src/old_name.py", "src/keep.py"]
        assert absent == ["src/brand_new.py"]

    def test_a_rename_from_a_file_that_did_not_exist_is_checked_at_the_new_path(self):
        files = [CachedPRFile("src/b.py", "renamed", "src/a.py", 0, 0)]
        assert resolve_pr_paths(files, {"src/b.py"}) == (["src/b.py"], [])
        assert resolve_pr_paths(files, set()) == ([], ["src/b.py"])

    def test_paths_are_normalised_first(self):
        files = [CachedPRFile(r"src\x.py", "modified", None, 1, 1)]
        assert resolve_pr_paths(files, {"src/x.py"}) == (["src/x.py"], [])

    def test_rename_map(self):
        files = [
            CachedPRFile("n.py", "renamed", "o.py", 0, 0),
            CachedPRFile("m.py", "modified", None, 1, 0),
        ]
        assert rename_map(files) == {"n.py": "o.py"}
