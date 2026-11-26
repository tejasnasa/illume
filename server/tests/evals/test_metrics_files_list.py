"""The ``Files:`` list parser."""

import pytest

from evals.metrics.files_list import parse_files_list

pytestmark = pytest.mark.unit


def paths(text: str) -> tuple[str, ...]:
    return parse_files_list(text).paths


def test_bullets_of_every_kind():
    text = "Files:\n- a.py\n* b.py\n• c.py\n1. d.py\n2) e.py"
    assert paths(text) == ("a.py", "b.py", "c.py", "d.py", "e.py")


def test_backticks():
    assert paths("Files:\n- `src/a.py`\n- `b.py` handles auth") == ("src/a.py", "b.py")


def test_a_bare_path_wins_over_backticked_symbols_in_its_description():
    text = (
        "Files:\n- pvlib/clearsky.py (`lookup_linke_turbidity`, `_interpolate`)\n"
        "- the module `src/b.py`"
    )
    assert paths(text) == ("pvlib/clearsky.py", "src/b.py")


@pytest.mark.parametrize(
    "item",
    [
        "a.py:10-20",
        "a.py#L10-L20",
        "a.py (lines 3–9)",
        "[a.py](a.py)",
        "[a.py](./a.py#L3)",
        "[a.py](https://github.com/o/r/blob/main/a.py)",
        "`a.py:10-20`",
        "**a.py**",
        ".\\a.py",
        "a.py:12:4",
    ],
)
def test_decorations_reduce_to_the_path(item):
    assert paths(f"Files:\n- {item}") == ("a.py",)


def test_windows_separators_and_dot_slash():
    assert paths("Files:\n- src\\pkg\\a.py\n- ./b.py") == ("src/pkg/a.py", "b.py")


def test_comma_list_on_the_heading_line_and_inside_a_bullet():
    assert paths("Files: a.py, b.py; `c.py`") == ("a.py", "b.py", "c.py")
    assert paths("Files:\n- a.py, b.py (lines 1, 2)") == ("a.py", "b.py")


@pytest.mark.parametrize(
    "heading", ["**Files:**", "## Files:", "FILES:", "files:", "**Files**:", "> Files:"]
)
def test_heading_styles(heading):
    assert paths(f"{heading}\n- a.py") == ("a.py",)


def test_an_absent_list_is_a_format_failure():
    result = parse_files_list("I changed a.py and b.py. Files changed are listed above")
    assert result.found is False and result.paths == ()


def test_a_list_with_nothing_in_it_is_found_but_empty():
    result = parse_files_list("Files: none")
    assert result.found is True and result.paths == ()


def test_only_the_last_block_counts():
    text = "Files:\n- old.py\n\nActually, revised:\n\nFiles:\n- new.py"
    assert paths(text) == ("new.py",)


def test_the_list_stops_at_a_blank_line_followed_by_prose():
    assert paths("Files:\n- a.py\n\nThat is everything, thanks.") == ("a.py",)


def test_a_blank_line_between_bullets_does_not_end_the_list():
    assert paths("Files:\n- a.py\n\n- b.py") == ("a.py", "b.py")


def test_unbulleted_paths_directly_under_the_heading():
    assert paths("Files:\na.py\nb/c.py\nThen some prose.") == ("a.py", "b/c.py")


def test_duplicates_keep_their_first_position():
    assert paths("Files:\n- b.py\n- a.py\n- b.py:3-4") == ("b.py", "a.py")


def test_words_of_prose_are_not_paths():
    text = (
        "Files: none identifiable; the remaining files (routes, sitemap) are not shown, "
        "so I cannot name them"
    )
    assert parse_files_list(text) == parse_files_list("Files:")
    assert paths("Files:\n- The module exporting `ComputerAction` (not shown)") == ()


def test_a_symbol_name_is_not_a_path():
    assert paths("Files:\n- `handle_tool_message`\n- `src/agent.py`") == ("src/agent.py",)


def test_well_known_extensionless_files_are_paths():
    assert paths("Files:\n- Makefile\n- `Dockerfile`\n- docs") == ("Makefile", "Dockerfile")


def test_prose_after_a_path_drops_its_words_but_keeps_named_paths():
    text = "Files:\n- `apps/www/blog.ts` — lookup, TOC generation, see `apps/www/seo.ts`"
    assert paths(text) == ("apps/www/blog.ts", "apps/www/seo.ts")


def test_a_hyphenated_path_is_still_a_path():
    assert paths("Files:\n- `src/multi-agent-triage.py`") == ("src/multi-agent-triage.py",)
