"""Matching the keys an answer cites against the evidence that was retrieved."""

from __future__ import annotations

import pytest

from app.services.retrieval.citations import parse_key
from app.services.retrieval.single_shot import match_citation, split_by_citations
from tests.fixtures.retrieval import make_candidate

pytestmark = pytest.mark.unit


def code(path, start, end):
    return make_candidate(
        f"F:{path}:{start}-{end}",
        f"code of {path}",
        file_path=path,
        start_line=start,
        end_line=end,
    )


def whole_file(path):
    return make_candidate(f"F:{path}", f"file {path}", source_type="file", file_path=path)


def commit(full_hash):
    return make_candidate(
        f"C:{full_hash[:8]}", "a commit", source_type="commit", commit_hash=full_hash
    )


def pull_request(number):
    return make_candidate(f"PR:{number}", "a pr", source_type="pull_request", pr_number=number)


def readme(slug):
    return make_candidate(f"D:README#{slug}", "readme part", source_type="document")


POOL = [
    code("app/auth.py", 10, 30),
    code("app/auth.py", 50, 70),
    whole_file("app/main.py"),
    commit("a1b2c3d4e5f60718"),
    pull_request(12),
    readme("installation"),
    code("app/users.py", 5, 9),
]


def keys(candidates):
    return [c.key for c in candidates]


class TestSplit:
    def test_cited_and_context_are_split(self):
        answer = "Passwords are hashed [F:app/auth.py:10-30] as the PR says [PR:12]."
        split = split_by_citations(answer, POOL)

        assert keys(split.cited) == ["F:app/auth.py:10-30", "PR:12"]
        assert keys(split.context) == [
            "F:app/auth.py:50-70",
            "F:app/main.py",
            "C:a1b2c3d4",
            "D:README#installation",
            "F:app/users.py:5-9",
        ]
        assert split.unresolved == []

    def test_sources_follow_first_citation_order_not_retrieval_order(self):
        answer = "See [PR:12], then [F:app/users.py:5-9], then [PR:12] again, then [C:a1b2c3d4]."
        split = split_by_citations(answer, POOL)
        assert keys(split.cited) == ["PR:12", "F:app/users.py:5-9", "C:a1b2c3d4"]

    def test_an_unresolved_key_is_kept_and_reported_once(self):
        answer = "A [F:app/ghost.py:1-2] B [PR:999] C [F:app/ghost.py:1-2] D [C:ffffffff]"
        split = split_by_citations(answer, POOL)

        assert split.cited == []
        assert split.unresolved == ["F:app/ghost.py:1-2", "PR:999", "C:ffffffff"]
        # Nothing was cited, so all the evidence is context.
        assert keys(split.context) == keys(POOL)

    def test_a_malformed_key_is_reported_as_written(self):
        split = split_by_citations("Odd [PR:abc] and [F:] and [D:nothing].", POOL)
        assert split.unresolved == ["PR:abc", "F:", "D:nothing"]

    def test_several_keys_in_one_bracket(self):
        split = split_by_citations("Both [PR:12; C:a1b2c3d4, F:app/main.py].", POOL)
        assert keys(split.cited) == ["PR:12", "C:a1b2c3d4", "F:app/main.py"]

    def test_prose_without_keys_cites_nothing(self):
        split = split_by_citations("No citations, only [a markdown link](x) and [1].", POOL)
        assert split.cited == [] and split.unresolved == []
        assert keys(split.context) == keys(POOL)

    def test_two_keys_for_the_same_evidence_cite_it_once(self):
        answer = "[F:app/auth.py:10-30] and again [F:app/auth.py:12-14]."
        split = split_by_citations(answer, POOL)
        assert keys(split.cited) == ["F:app/auth.py:10-30"]
        assert split.unresolved == []


class TestMatching:
    def match(self, text, pool=POOL):
        by_key = {c.key: c for c in pool}
        parsed = parse_key(text)
        assert parsed is not None
        found = match_citation(parsed, by_key)
        return found.key if found else None

    def test_exact_key(self):
        assert self.match("F:app/auth.py:50-70") == "F:app/auth.py:50-70"
        assert self.match("PR:12") == "PR:12"
        assert self.match("D:README#installation") == "D:README#installation"

    def test_a_readme_slug_is_case_insensitive(self):
        assert self.match("D:README#Installation") == "D:README#installation"

    def test_a_path_only_key_matches_the_first_candidate_in_that_file(self):
        assert self.match("F:app/auth.py") == "F:app/auth.py:10-30"
        assert self.match("F:app/users.py") == "F:app/users.py:5-9"

    def test_a_range_overlapping_a_candidate_matches_it(self):
        assert self.match("F:app/auth.py:25-40") == "F:app/auth.py:10-30"
        assert self.match("F:app/auth.py:60-61") == "F:app/auth.py:50-70"

    def test_the_candidate_with_the_most_overlap_wins(self):
        pool = [code("a.py", 1, 10), code("a.py", 8, 40)]
        assert self.match("F:a.py:9-30", pool) == "F:a.py:8-40"

    def test_a_tie_in_overlap_goes_to_the_better_ranked(self):
        pool = [code("a.py", 1, 20), code("a.py", 1, 20)]
        pool[1] = make_candidate(
            "F:a.py:1-20#2", "dup", file_path="a.py", start_line=1, end_line=20
        )
        assert self.match("F:a.py:5-6", pool) == "F:a.py:1-20"

    def test_a_range_outside_every_candidate_is_unmatched(self):
        assert self.match("F:app/auth.py:31-49") is None

    def test_a_whole_file_candidate_covers_any_range(self):
        assert self.match("F:app/main.py:100-120") == "F:app/main.py"

    def test_a_different_path_never_matches(self):
        assert self.match("F:app/other.py") is None
        assert self.match("F:app/other.py:10-30") is None

    def test_paths_are_normalised_before_matching(self):
        assert self.match("F:./app/auth.py:12-14") == "F:app/auth.py:10-30"
        assert self.match("F:app\\auth.py") == "F:app/auth.py:10-30"

    def test_commits_match_by_short_hash(self):
        assert self.match("C:a1b2c3d4") == "C:a1b2c3d4"
        # A longer hash is cut to the short form; a shorter prefix still identifies it.
        assert self.match("C:a1b2c3d4e5f60718") == "C:a1b2c3d4"
        assert self.match("C:A1B2C3") == "C:a1b2c3d4"
        assert self.match("C:a1b2ffff") is None

    def test_pull_requests_and_documents_match_only_exactly(self):
        assert self.match("PR:13") is None
        assert self.match("D:README#usage") is None
        assert self.match("D:CHANGELOG#installation") is None
