"""Golden-file comparison for payloads that are easier to freeze than to assert field by field.

Used for the `.illume` export, whose whole value is its exact text: it is a file a user
downloads and reads, so its layout is the feature. Asserting it field by field would be an
enormous amount of code that still missed anything nobody thought to assert, and an
*additive* change -- a new section, a reordered header -- would pass unnoticed.

Regenerate with `pytest --update-golden`, then read the diff before committing it. That
review step is the whole point: the file records what the output is, and a change to it is
a decision rather than an accident.
"""

import difflib
import re
from pathlib import Path

import pytest

GOLDEN_DIR = Path(__file__).parent

# Volatile spans, replaced with a placeholder rather than deleted -- a line that vanished
# entirely should still show up as a difference, which dropping it would hide.
_VOLATILE: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^generated=.*$", re.MULTILINE), "generated=<date>"),
)


def normalise(text: str) -> str:
    """Replace the parts of the output that cannot be stable between runs."""
    for pattern, replacement in _VOLATILE:
        text = pattern.sub(replacement, text)
    return text


def assert_matches_golden(name: str, actual: str, update: bool) -> None:
    """Compare `actual` against the golden file `name`, or rewrite it under `--update-golden`.

    Args:
        name: File name inside this package, e.g. ``illume_export.txt``.
        actual: The output as produced this run.
        update: True when ``--update-golden`` was passed.

    Raises:
        AssertionError: If the output differs, carrying a unified diff; or if no golden file
            exists and updating was not requested.
    """
    path = GOLDEN_DIR / name
    actual = normalise(actual)

    if update:
        path.write_text(actual, encoding="utf-8")
        pytest.skip(f"golden file rewritten: {name}")

    if not path.exists():
        raise AssertionError(
            f"no golden file at {path}. Create it with `pytest --update-golden` and read "
            "the diff before committing."
        )

    expected = path.read_text(encoding="utf-8")
    if expected != actual:
        diff = "\n".join(
            difflib.unified_diff(
                expected.splitlines(),
                actual.splitlines(),
                fromfile=f"{name} (committed)",
                tofile=f"{name} (actual)",
                lineterm="",
            )
        )
        raise AssertionError(
            "the export no longer matches its golden file. If the change is intended, "
            f"run `pytest --update-golden` and review the diff.\n\n{diff}"
        )
