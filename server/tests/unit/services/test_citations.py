"""Citation keys: rendering, parsing, and finding them in an answer.

A key that parses differently from how it was rendered would make a correct
citation look unresolved, so every builder is checked against the parser, and
the prose scanner is checked on the shapes models actually write.
"""

from __future__ import annotations

import pytest

from app.services.retrieval.citations import (
    CitationKey,
    code_key,
    commit_key,
    document_key,
    find_keys,
    normalize_path,
    parse_key,
    pull_request_key,
    slugify_heading,
)

pytestmark = pytest.mark.unit


class TestBuilders:
    def test_code_range(self):
        assert code_key("server/app/core/security.py", 48, 67) == (
            "F:server/app/core/security.py:48-67"
        )

    def test_whole_file(self):
        assert code_key("server/app/main.py") == "F:server/app/main.py"

    def test_path_is_normalised(self):
        assert code_key("./server\\app//main.py") == "F:server/app/main.py"

    @pytest.mark.parametrize(("start", "end"), [(5, None), (None, 5), (0, 3), (9, 3)])
    def test_bad_ranges_are_refused(self, start, end):
        with pytest.raises(ValueError):
            code_key("a.py", start, end)

    def test_commit_is_shortened_and_lowercased(self):
        assert commit_key("A1B2C3D4E5F60718293a") == "C:a1b2c3d4"

    def test_commit_must_be_hex(self):
        with pytest.raises(ValueError):
            commit_key("not-a-hash")

    def test_pull_request(self):
        assert pull_request_key(142) == "PR:142"
        with pytest.raises(ValueError):
            pull_request_key(0)

    def test_document_section(self):
        assert document_key("## Getting Started!") == "D:README#getting-started"
        assert document_key("") == "D:README#top"


class TestRoundTrip:
    @pytest.mark.parametrize(
        "key",
        [
            code_key("server/app/core/security.py", 48, 67),
            code_key("server/app/main.py"),
            code_key("client/src/app/repo/[id]/page.tsx", 1, 9),
            commit_key("deadbeefcafe"),
            pull_request_key(7),
            document_key("Installation"),
        ],
    )
    def test_every_built_key_parses_back_to_itself(self, key):
        parsed = parse_key(key)
        assert parsed is not None
        assert parsed.render() == key
        assert parse_key(f"[{key}]") == parsed


class TestParse:
    def test_single_line_becomes_a_one_line_range(self):
        assert parse_key("F:a.py:12") == CitationKey(kind="F", path="a.py", start=12, end=12)

    def test_pull_request_accepts_a_hash_sign(self):
        assert parse_key("PR:#9") == CitationKey(kind="PR", pr_number=9)

    def test_long_commit_is_canonicalised(self):
        parsed = parse_key("C:ABCDEF0123456789")
        assert parsed is not None
        assert parsed.render() == "C:abcdef01"

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "F:",
            "F::1-2",
            "F:a.py:0-3",
            "F:a.py:9-3",
            "C:zzzz",
            "PR:abc",
            "PR:0",
            "D:README",
            "X:1",
        ],
    )
    def test_malformed_keys_parse_to_none(self, text):
        assert parse_key(text) is None

    def test_a_path_with_a_colon_keeps_the_colon(self):
        assert parse_key("F:docs/a:b.md:3-4") == CitationKey(
            kind="F", path="docs/a:b.md", start=3, end=4
        )


class TestNormalizePath:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("app/main.py", "app/main.py"),
            ("./app/main.py", "app/main.py"),
            ("/app/main.py", "app/main.py"),
            ("app\\core\\auth.py", "app/core/auth.py"),
            ("app//core///auth.py", "app/core/auth.py"),
            ("  app/main.py ", "app/main.py"),
        ],
    )
    def test_forms_ingestion_would_store(self, raw, expected):
        assert normalize_path(raw) == expected

    def test_parent_segments_are_left_visible(self):
        """A key is matched, never opened, so hiding ``..`` would only mask a bad key."""
        assert normalize_path("../secrets.py") == "../secrets.py"


class TestFindKeys:
    def test_keys_in_order_of_appearance(self):
        prose = "Login is in [F:app/auth.py:3-9], added in [C:a1b2c3d4] via [PR:12]."
        assert [raw for raw, _ in find_keys(prose)] == [
            "F:app/auth.py:3-9",
            "C:a1b2c3d4",
            "PR:12",
        ]

    def test_several_keys_in_one_bracket(self):
        found = find_keys("See [F:a.py:1-2; F:b.py, PR:4].")
        assert [parsed.render() for _, parsed in found if parsed] == [
            "F:a.py:1-2",
            "F:b.py",
            "PR:4",
        ]

    def test_brackets_inside_a_path(self):
        """Next.js route folders put brackets in paths; this repository has them."""
        found = find_keys("The page is [F:client/src/app/repo/[id]/page.tsx:10-20].")
        assert len(found) == 1
        raw, parsed = found[0]
        assert raw == "F:client/src/app/repo/[id]/page.tsx:10-20"
        assert parsed == CitationKey(
            kind="F", path="client/src/app/repo/[id]/page.tsx", start=10, end=20
        )

    def test_non_key_brackets_are_ignored(self):
        prose = "A [markdown link](http://x) and [an aside] and [F:a.py]."
        assert [raw for raw, _ in find_keys(prose)] == ["F:a.py"]

    def test_a_malformed_key_is_reported_not_dropped(self):
        assert find_keys("Broken [F:a.py:9-3] here.") == [("F:a.py:9-3", None)]

    def test_an_unclosed_bracket_does_not_swallow_the_rest(self):
        prose = "Starts [F:a.py:1-2\nand later [PR:3]."
        assert [raw for raw, _ in find_keys(prose)] == []
        assert [raw for raw, _ in find_keys("ok [PR:3] then [F:a.py")] == ["PR:3"]


class TestSlug:
    @pytest.mark.parametrize(
        ("heading", "slug"),
        [
            ("Installation", "installation"),
            ("## Getting Started", "getting-started"),
            ("API: v2 (beta)", "api-v2-beta"),
            ("snake_case and kebab-case", "snake_case-and-kebab-case"),
        ],
    )
    def test_github_style(self, heading, slug):
        assert slugify_heading(heading) == slug
