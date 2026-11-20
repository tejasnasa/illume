"""Harness clones and the git queries run against them."""

import pytest

from evals.mining import clones
from evals.mining.clones import (
    default_tip,
    ensure_clone,
    files_at,
    is_ancestor,
    rev_exists,
    show_file,
)
from tests.fixtures import sample_repo

UNKNOWN_SHA = "f" * 40


@pytest.fixture
def clone(tmp_path, history):
    return ensure_clone(str(history.root), tmp_path / "clones", slug="fixture/sample")


@pytest.mark.integration
class TestEnsureClone:
    def test_a_local_path_is_cloned_without_a_checkout(self, tmp_path, history):
        target = ensure_clone(str(history.root), tmp_path / "clones", slug="fixture/sample")
        assert target == tmp_path / "clones" / "fixture__sample"
        assert (target / ".git").exists()
        assert not (target / "src").exists()
        assert rev_exists(target, history.base)

    def test_every_branch_is_fetched(self, clone, history):
        assert rev_exists(clone, history.pr_early_merge)

    def test_an_existing_clone_is_refreshed_with_new_commits(self, tmp_path, history):
        target = ensure_clone(str(history.root), tmp_path / "clones", slug="fixture/sample")
        before = default_tip(target)
        (history.root / "NEW.md").write_text("new\n", encoding="utf-8")
        sample_repo.commit_all(history.root, "docs: add NEW")
        again = ensure_clone(str(history.root), tmp_path / "clones", slug="fixture/sample")
        assert again == target
        assert default_tip(target) == sample_repo.head_sha(history.root) != before

    def test_a_bad_url_raises(self, tmp_path):
        with pytest.raises(RuntimeError, match="git clone failed"):
            ensure_clone(str(tmp_path / "missing"), tmp_path / "clones", slug="x/y")


@pytest.mark.integration
class TestQueries:
    def test_is_ancestor(self, clone, history):
        assert is_ancestor(clone, history.first, history.base)
        assert is_ancestor(clone, history.base, history.base)
        assert not is_ancestor(clone, history.pr_b_merge, history.base)
        assert not is_ancestor(clone, history.pr_early_merge, history.base)

    def test_an_unknown_or_empty_sha_is_not_an_ancestor(self, clone, history):
        assert not is_ancestor(clone, UNKNOWN_SHA, history.base)
        assert not is_ancestor(clone, "", history.base)

    def test_rev_exists(self, clone, history):
        assert rev_exists(clone, history.first)
        assert not rev_exists(clone, UNKNOWN_SHA)
        assert not rev_exists(clone, "")

    def test_default_tip_is_the_main_branch_head(self, clone, history):
        assert default_tip(clone) == history.pr_b_merge

    def test_files_at_lists_the_tree(self, clone, history):
        at_base = files_at(clone, history.base)
        assert "src/util.py" in at_base
        assert "src/pkg/nested.py" in at_base
        assert "docs/feature_b.md" not in at_base
        assert "docs/feature_b.md" in files_at(clone, history.pr_b_merge)
        assert files_at(clone, UNKNOWN_SHA) == set()

    def test_a_non_ascii_path_is_listed_verbatim(self, clone, history):
        assert "src/café.py" in files_at(clone, history.base)

    def test_show_file_reads_a_file_at_a_revision(self, clone, history):
        assert "def slugify" in (show_file(clone, history.first, "src/util.py") or "")
        assert "def later" not in (show_file(clone, history.first, "src/util.py") or "")
        assert "def later" in (show_file(clone, history.base, "src/util.py") or "")

    def test_show_file_is_none_when_the_file_is_absent(self, clone, history):
        assert show_file(clone, history.first, "docs/feature_b.md") is None
        assert show_file(clone, UNKNOWN_SHA, "src/util.py") is None

    def test_git_helper_never_raises_on_failure(self, clone):
        result = clones.git(clone, "rev-parse", "--verify", "no-such-ref")
        assert result.returncode != 0
