"""Blame through whitespace, moves and mechanical commits, and pull request lookup."""

from pathlib import Path

import pytest

from evals.mining import blame
from evals.mining.blame import (
    MechanicalVerdict,
    blame_file,
    blame_line,
    is_mechanical,
    pr_for_commit,
)
from evals.mining.clones import default_tip, ensure_clone, git
from tests.fixtures import sample_repo


@pytest.fixture
def clone(tmp_path, history):
    return ensure_clone(str(history.root), tmp_path / "clones", slug="fixture/sample")


def _line_of(clone: Path, rev: str, path: str, text: str) -> int:
    matches = [item.line for item in blame_file(clone, rev, path) if text in item.content]
    assert len(matches) == 1, (text, matches)
    return matches[0]


def _repo(root: Path) -> Path:
    root.mkdir(parents=True)
    sample_repo._git(root, "init", "-b", "main")
    return root


def _commit(root: Path, files: dict[str, str], message: str) -> str:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
    sample_repo.commit_all(root, message)
    return sample_repo.head_sha(root)


@pytest.mark.integration
class TestBlameOnHistory:
    def test_an_untouched_line_is_attributed_to_the_commit_that_wrote_it(self, clone, history):
        line = _line_of(clone, history.base, "src/util.py", "def slugify")
        result = blame_line(clone, history.base, "src/util.py", line)
        assert result is not None
        assert result.commit == history.first
        assert result.path == "src/util.py"
        assert result.skipped == ()

    def test_a_whitespace_only_commit_is_looked_through(self, clone, history):
        line = _line_of(clone, history.base, "src/util.py", "return text.strip()")
        result = blame_line(clone, history.base, "src/util.py", line)
        assert result is not None
        assert result.commit == history.first
        assert history.whitespace not in {entry.commit for entry in result.skipped}

    def test_a_moved_function_is_attributed_to_the_commit_that_wrote_it(self, clone, history):
        line = _line_of(clone, history.base, history.moved_to, "return 42")
        result = blame_line(clone, history.base, history.moved_to, line)
        assert result is not None
        assert result.commit == history.second
        assert result.path == history.moved_from
        assert result.commit != history.moved

    def test_blame_file_returns_every_line(self, clone, history):
        lines = blame_file(clone, history.base, "src/util.py")
        assert [item.line for item in lines] == list(range(1, len(lines) + 1))
        assert all(len(item.commit) == 40 for item in lines)
        assert blame_file(clone, history.base, "no/such/file.py") == []

    def test_a_missing_file_or_line_gives_none(self, clone, history):
        assert blame_line(clone, history.base, "no/such/file.py", 1) is None
        assert blame_line(clone, history.base, "src/util.py", 9999) is None


@pytest.mark.integration
class TestHopWalk:
    @pytest.fixture
    def chain(self, tmp_path):
        root = _repo(tmp_path / "chain")
        c1 = _commit(root, {"a.txt": "one\ntwo\nthree\n"}, "feat: first")
        c2 = _commit(root, {"a.txt": "one\ntwo-b\nthree\n"}, "feat: second")
        c3 = _commit(root, {"a.txt": "zero\none\ntwo-b\nthree\n"}, "feat: third")
        c4 = _commit(root, {"a.txt": "zero\none\ntwo-c\nthree\n"}, "feat: fourth")
        return root, (c1, c2, c3, c4)

    @staticmethod
    def _predicate(mechanical_commits):
        def decide(_clone, sha):
            return MechanicalVerdict("test" if sha in mechanical_commits else None)

        return decide

    def test_an_ordinary_commit_needs_no_hops(self, chain):
        root, (_, _, _, c4) = chain
        result = blame_line(root, "HEAD", "a.txt", 3, mechanical=self._predicate(set()))
        assert result is not None and result.commit == c4 and result.skipped == ()

    def test_a_mechanical_commit_sends_the_walk_one_hop_further(self, chain):
        root, (_, c2, _, c4) = chain
        result = blame_line(root, "HEAD", "a.txt", 3, mechanical=self._predicate({c4}))
        assert result is not None
        assert result.commit == c2
        assert [entry.commit for entry in result.skipped] == [c4]
        assert result.skipped[0].reason == "test"
        assert result.line == 2

    def test_two_mechanical_commits_reach_the_origin(self, chain):
        root, (c1, c2, _, c4) = chain
        result = blame_line(root, "HEAD", "a.txt", 3, mechanical=self._predicate({c4, c2}))
        assert result is not None
        assert result.commit == c1
        assert [entry.commit for entry in result.skipped] == [c4, c2]
        assert (result.path, result.line) == ("a.txt", 2)

    def test_max_hops_bounds_the_walk(self, chain):
        root, (_, c2, _, c4) = chain
        predicate = self._predicate({c4, c2})
        assert blame_line(root, "HEAD", "a.txt", 3, max_hops=2, mechanical=predicate) is not None
        assert blame_line(root, "HEAD", "a.txt", 3, max_hops=1, mechanical=predicate) is None
        only_c4 = self._predicate({c4})
        assert blame_line(root, "HEAD", "a.txt", 3, max_hops=0, mechanical=only_c4) is None

    def test_reaching_the_root_while_still_mechanical_gives_none(self, chain):
        root, (c1, c2, _, c4) = chain
        predicate = self._predicate({c4, c2, c1})
        assert blame_line(root, "HEAD", "a.txt", 3, max_hops=10, mechanical=predicate) is None

    def test_a_shifted_line_is_followed_by_its_text(self, chain):
        root, (_, _, c3, _) = chain
        # c3 inserted a line above "one", so "one" sits at line 2 there but line 1 before it.
        result = blame_line(root, "HEAD", "a.txt", 2, mechanical=self._predicate({c3}))
        assert result is not None
        assert result.commit != c3
        assert result.line == 1


@pytest.mark.integration
class TestIsMechanical:
    def test_more_than_thirty_files_is_mechanical(self, tmp_path):
        root = _repo(tmp_path / "r")
        _commit(root, {"seed.txt": "x\n"}, "feat: seed")
        many = _commit(root, {f"f{i}.txt": "x\n" for i in range(31)}, "feat: add many files")
        verdict = is_mechanical(root, many)
        assert verdict.mechanical
        assert verdict.reason == "31 files changed"

    def test_exactly_thirty_files_is_not(self, tmp_path):
        root = _repo(tmp_path / "r")
        _commit(root, {"seed.txt": "x\n"}, "feat: seed")
        thirty = _commit(root, {f"f{i}.txt": "x\n" for i in range(30)}, "feat: add files")
        assert not is_mechanical(root, thirty).mechanical

    def test_a_root_commit_is_compared_with_the_empty_tree(self, tmp_path):
        big = _repo(tmp_path / "big")
        first = _commit(big, {f"f{i}.txt": "x\n" for i in range(31)}, "feat: import")
        assert is_mechanical(big, first).mechanical
        small = _repo(tmp_path / "small")
        only = _commit(small, {"a.txt": "x\n"}, "feat: import")
        assert not is_mechanical(small, only).mechanical

    @pytest.mark.parametrize(
        "message",
        [
            "bump lodash from 4.17.20 to 4.17.21",
            "Bump version to 2.0",
            "chore(deps): update requests",
            "format code",
            "Reformat with black",
            "lint: fix warnings",
            "style: tidy",
            "prettier all the things",
            "ruff fixes",
        ],
    )
    def test_the_message_patterns_are_mechanical(self, tmp_path, message):
        root = _repo(tmp_path / "r")
        _commit(root, {"a.txt": "x\n"}, "feat: seed")
        sha = _commit(root, {"a.txt": "y\n"}, message)
        verdict = is_mechanical(root, sha)
        assert verdict.mechanical
        assert verdict.reason == f"message: {message}"

    def test_a_similar_word_inside_the_message_is_not(self, tmp_path):
        root = _repo(tmp_path / "r")
        _commit(root, {"a.txt": "x\n"}, "feat: seed")
        sha = _commit(root, {"a.txt": "y\n"}, "feat: support formatting options")
        assert not is_mechanical(root, sha).mechanical

    def test_a_whitespace_dominated_diff_is_mechanical(self, tmp_path):
        root = _repo(tmp_path / "r")
        body = "".join(f"line {i}\n" for i in range(20))
        _commit(root, {"a.txt": body}, "feat: seed")
        spaced = "".join(f"line {i}   \n" for i in range(20))
        sha = _commit(root, {"a.txt": spaced}, "tidy things up")
        assert is_mechanical(root, sha).reason == "whitespace-only changes"

    def test_the_fixture_whitespace_commit_is_mechanical(self, clone, history):
        assert is_mechanical(clone, history.whitespace).mechanical
        assert not is_mechanical(clone, history.moved).mechanical

    def test_a_real_edit_is_not_mechanical(self, tmp_path):
        root = _repo(tmp_path / "r")
        _commit(root, {"a.txt": "".join(f"line {i}\n" for i in range(20))}, "feat: seed")
        sha = _commit(root, {"a.txt": "".join(f"row {i}\n" for i in range(20))}, "feat: rename")
        assert not is_mechanical(root, sha).mechanical

    def test_the_pattern_list_is_a_module_constant(self):
        assert blame.MECHANICAL_MESSAGE.match("Bump x")


@pytest.mark.integration
class TestPrForCommit:
    @staticmethod
    def _commit_adding(clone: Path, name: str) -> str:
        out = git(clone, "log", "--all", "--no-merges", "--format=%H", f"--grep=add {name}")
        return out.stdout.split()[0]

    def test_a_squash_merge_maps_directly(self, clone, history):
        tip = default_tip(clone)
        assert pr_for_commit(clone, history.second, {history.second: 7}, tip) == 7

    def test_a_commit_on_a_merged_branch_maps_through_the_merge_commit(self, clone, history):
        tip = default_tip(clone)
        mapping = {sha: number for number, sha in history.prs.items()}
        feature_a = self._commit_adding(clone, "docs/feature_a.md")
        feature_b = self._commit_adding(clone, "docs/feature_b.md")
        assert pr_for_commit(clone, feature_a, mapping, tip) == 101
        assert pr_for_commit(clone, feature_b, mapping, tip) == 102

    def test_a_commit_made_directly_on_main_belongs_to_no_pull_request(self, clone, history):
        tip = default_tip(clone)
        mapping = {sha: number for number, sha in history.prs.items()}
        assert pr_for_commit(clone, history.moved, mapping, tip) is None
        assert pr_for_commit(clone, history.whitespace, mapping, tip) is None

    def test_a_commit_that_never_reached_the_tip_gives_none(self, clone, history):
        tip = default_tip(clone)
        mapping = {sha: number for number, sha in history.prs.items()}
        side = self._commit_adding(clone, "docs/side.md")
        assert pr_for_commit(clone, side, mapping, tip) is None
        assert pr_for_commit(clone, "f" * 40, mapping, tip) is None
