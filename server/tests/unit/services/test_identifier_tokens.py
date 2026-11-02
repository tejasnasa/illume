"""Pulling identifier-like tokens and quoted strings out of a question."""

from __future__ import annotations

import pytest

from app.services.retrieval.channels.grep import escape_like
from app.services.retrieval.identifiers import identifier_tokens, quoted_strings

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("what does verify_password do?", ["verify_password"]),
        ("where is getUserById defined", ["getUserById"]),
        ("explain HTTPServer", ["HTTPServer"]),
        ("explain the PasswordPolicy class", ["PasswordPolicy"]),
        ("what is `config` for", ["config"]),
        ("call `get_user()` first", ["get_user"]),
        ("see getUser(id) and parse_config()", ["getUser", "parse_config"]),
        ("(see verify_password), then hash_password.", ["verify_password", "hash_password"]),
        ("how does login work", []),
        ("What is the Plan? Please explain.", []),
        ("e.g. something, i.e. nothing", []),
        ("version 3.14 is required", []),
        ("ends with a full stop config.", []),
        ("", []),
    ],
)
def test_identifier_tokens(question, expected):
    assert identifier_tokens(question) == expected


def test_a_dotted_name_also_yields_its_last_segment():
    assert identifier_tokens("what does auth.verify_password do") == [
        "auth.verify_password",
        "verify_password",
    ]


def test_a_file_name_does_not_yield_its_extension():
    assert identifier_tokens("open security.py and config.json") == [
        "security.py",
        "config.json",
    ]


def test_a_path_is_kept_whole():
    assert identifier_tokens("look in app/core/security.py") == ["app/core/security.py"]


def test_tokens_are_distinct_and_keep_first_seen_order():
    assert identifier_tokens("`b_one` a_two b_one a_two `c_three`") == ["b_one", "a_two", "c_three"]


def test_a_backticked_phrase_is_not_a_name():
    assert identifier_tokens("run `uv run pytest` now") == []


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ('where is "Invalid credentials" raised', ["Invalid credentials"]),
        ("the message 'token expired' appears", ["token expired"]),
        ("what is the user's id", []),
        ('say "ab" and "abc"', ["abc"]),
        ('both "same text" and "same text"', ["same text"]),
        ("no quotes here", []),
    ],
)
def test_quoted_strings(question, expected):
    assert quoted_strings(question) == expected


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ("plain", "plain"),
        ("50%", "50\\%"),
        ("user_id", "user\\_id"),
        ("a\\b", "a\\\\b"),
        ("%_\\", "\\%\\_\\\\"),
    ],
)
def test_escape_like(raw, escaped):
    assert escape_like(raw) == escaped
