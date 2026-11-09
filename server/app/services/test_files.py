"""Work out which source files have tests.

A test is matched to the file it covers by name and place. The name rule
strips the usual test markers (``test_foo.py``, ``foo_test.go``,
``foo.test.ts``, ``Foo.spec.tsx``, ``FooTest.java``, ``foo_spec.rb``) to get
the subject, which must equal the source file's stem; ``test_agent_planner.py``
also counts for ``agent/planner.py``. The place rule allows the layouts real
projects use: beside the source, in a ``__tests__``/``tests`` folder next to it,
or in a separate test tree that mirrors the source tree. Concretely, the test's
folders, once test-only folders such as ``tests`` and ``unit`` are dropped,
must appear in order within the source file's folders. That accepts
``server/tests/unit/services/test_criticality.py`` for
``server/app/services/criticality.py`` and ``src/test/java/x/FooTest.java``
for ``src/main/java/x/Foo.java``, and rejects a test in an unrelated package.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from pathlib import PurePosixPath

# Folders that hold tests but say nothing about what is being tested.
TEST_DIRS = frozenset(
    {
        "test",
        "tests",
        "__tests__",
        "spec",
        "specs",
        "testing",
        "unit",
        "integration",
        "functional",
        "e2e",
    }
)

# Folder names that by themselves make a file a test. Narrower than
# ``TEST_DIRS``: an application package may well be called ``integration``.
_TEST_ONLY_DIRS = frozenset({"test", "tests", "__tests__", "spec", "specs", "e2e"})

# Languages whose test may be written in a sibling extension.
_LANGUAGE_FAMILIES = {
    ".py": "py",
    ".pyi": "py",
    ".js": "js",
    ".jsx": "js",
    ".mjs": "js",
    ".cjs": "js",
    ".ts": "js",
    ".tsx": "js",
    ".mts": "js",
    ".cts": "js",
    ".vue": "js",
    ".svelte": "js",
    ".java": "jvm",
    ".kt": "jvm",
    ".kts": "jvm",
    ".scala": "jvm",
    ".groovy": "jvm",
}

# Each pattern captures the subject out of a test file's name (no extension).
_SUBJECT_PATTERNS = [
    re.compile(r"^test_(?P<s>.+)$"),
    re.compile(r"^(?P<s>.+?)[._](?:test|spec)s?$", re.IGNORECASE),
    re.compile(r"^(?P<s>.*?[a-z0-9])(?:Tests?|Spec|IT)$"),
]


def _family(suffix: str) -> str:
    return _LANGUAGE_FAMILIES.get(suffix.lower(), suffix.lower())


def _split_name(path: PurePosixPath) -> tuple[str, str]:
    """Return (name without extension, extension), keeping ``.test`` in the name."""
    return path.name[: -len(path.suffix)] if path.suffix else path.name, path.suffix


def subject_of_test(path: str) -> str | None:
    """The name of what a test file covers, or ``None`` if it is not one by name."""
    name, _ = _split_name(PurePosixPath(path))
    for pattern in _SUBJECT_PATTERNS:
        match = pattern.match(name)
        if match and match.group("s"):
            return match.group("s")
    return None


def is_test_path(path: str) -> bool:
    """Whether a path is a test file, by its name or by the folder it is in."""
    p = PurePosixPath(path.replace("\\", "/"))
    if subject_of_test(str(p)) is not None:
        return True
    return any(part.lower() in _TEST_ONLY_DIRS for part in p.parts[:-1])


def _is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    it = iter(haystack)
    return all(any(part == item for item in it) for part in needle)


def detect_tested_files(source_paths: Iterable[str], all_paths: Iterable[str]) -> dict[str, bool]:
    """Map each source path to whether some test in ``all_paths`` covers it.

    Args:
        source_paths: Repository-relative paths to check.
        all_paths: Every file in the repository, tests included.

    Returns:
        ``{path: has_tests}`` for every source path. Test files themselves map
        to ``False``; callers that score risk should skip them via
        :func:`is_test_path`.
    """
    index: dict[str, list[tuple[list[str], str]]] = defaultdict(list)
    for raw in all_paths:
        p = PurePosixPath(raw.replace("\\", "/"))
        subject = subject_of_test(str(p))
        if subject is None:
            continue
        folders = [part.lower() for part in p.parts[:-1] if part.lower() not in TEST_DIRS]
        index[subject.lower()].append((folders, _family(p.suffix)))

    result: dict[str, bool] = {}
    for raw in source_paths:
        p = PurePosixPath(raw.replace("\\", "/"))
        if is_test_path(str(p)):
            result[raw] = False
            continue
        stem, suffix = _split_name(p)
        folders = [part.lower() for part in p.parts[:-1]]
        family = _family(suffix)
        subjects = {stem.lower()}
        if folders:
            subjects.add(f"{folders[-1]}_{stem.lower()}")
        result[raw] = any(
            test_family == family and _is_subsequence(test_folders, folders)
            for subject in subjects
            for test_folders, test_family in index.get(subject, ())
        )
    return result
