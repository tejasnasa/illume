import pytest

from app.services.test_files import detect_tested_files, is_test_path, subject_of_test


@pytest.mark.parametrize(
    ("path", "subject"),
    [
        ("tests/test_parser.py", "parser"),
        ("pkg/parser_test.py", "parser"),
        ("cmd/server_test.go", "server"),
        ("src/__tests__/Select.test.tsx", "Select"),
        ("src/utils/timeAgo.spec.ts", "timeAgo"),
        ("src/test/java/x/FooTest.java", "Foo"),
        ("src/test/java/x/FooTests.java", "Foo"),
        ("src/test/java/x/FooIT.java", "Foo"),
        ("spec/models/user_spec.rb", "user"),
        ("app/latest.py", None),
        ("app/manifest.ts", None),
        ("app/AUDIT.py", None),
        ("app/contest.py", None),
    ],
)
def test_subject_is_read_from_the_test_name(path, subject):
    assert subject_of_test(path) == subject


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("server/tests/conftest.py", True),
        ("client/e2e/specs/chat.spec.ts", True),
        ("src/__tests__/helpers.ts", True),
        ("app/integration/stripe.py", False),
        ("app/unit/convert.py", False),
        ("app/services/parser.py", False),
    ],
)
def test_test_paths_are_recognised(path, expected):
    assert is_test_path(path) is expected


ALL = [
    "server/app/services/criticality.py",
    "server/app/services/agent/planner.py",
    "server/app/api/v1/guide.py",
    "server/tests/unit/services/test_criticality.py",
    "server/tests/unit/services/test_agent_planner.py",
    "client/src/utils/timeAgo.ts",
    "client/tests/unit/utils/timeAgo.test.ts",
    "client/src/components/Select.tsx",
    "client/src/components/__tests__/Select.test.tsx",
    "client/src/components/Card.tsx",
    "other/pkg/criticality.py",
    "src/main/java/x/Foo.java",
    "src/test/java/x/FooTest.java",
    "cmd/server.go",
    "cmd/server_test.go",
    "lib/parse.py",
    "tests/test_parse.py",
]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("server/app/services/criticality.py", True),
        ("server/app/services/agent/planner.py", True),
        ("server/app/api/v1/guide.py", False),
        ("client/src/utils/timeAgo.ts", True),
        ("client/src/components/Select.tsx", True),
        ("client/src/components/Card.tsx", False),
        ("other/pkg/criticality.py", False),
        ("src/main/java/x/Foo.java", True),
        ("cmd/server.go", True),
        ("lib/parse.py", True),
        ("server/tests/unit/services/test_criticality.py", False),
    ],
)
def test_sources_are_matched_to_their_tests(path, expected):
    assert detect_tested_files([path], ALL)[path] is expected


def test_a_test_in_another_language_does_not_count():
    result = detect_tested_files(["web/parse.ts"], ["web/parse.ts", "web/test_parse.py"])
    assert result["web/parse.ts"] is False


def test_windows_separators_are_accepted():
    result = detect_tested_files(
        ["server\\app\\services\\criticality.py"],
        ["server\\tests\\unit\\services\\test_criticality.py"],
    )
    assert result["server\\app\\services\\criticality.py"] is True
