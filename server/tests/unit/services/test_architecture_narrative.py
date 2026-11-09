import pytest

from app.services.architecture_brief import _build_narrative_prompt, _strip_leading_title


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("# Architecture Summary: Illume\n\nIllume clones a repo.", "Illume clones a repo."),
        ("\n\n## Overview\n### Illume\nIllume clones a repo.", "Illume clones a repo."),
        ("#\nIllume clones a repo.", "Illume clones a repo."),
        (
            "Illume clones a repo.\n\n## Flow\nThen it parses.",
            "Illume clones a repo.\n\n## Flow\nThen it parses.",
        ),
        ("#hashtag is not a heading", "#hashtag is not a heading"),
        ("  Plain text.  ", "Plain text."),
    ],
)
def test_strips_only_the_opening_headings(raw, expected):
    assert _strip_leading_title(raw) == expected


def test_prompt_asks_for_no_headings():
    prompt = _build_narrative_prompt(
        repo_name="demo",
        detected_stack={},
        entry_points=[],
        key_modules=[],
        module_edges=[],
        module_symbols={},
        external_integrations=[],
        data_flow=[],
        total_files=0,
    )
    assert "Do not add a title or any markdown headings" in prompt
