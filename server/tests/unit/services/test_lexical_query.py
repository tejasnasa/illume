"""Building the OR query the lexical channel sends to ``to_tsquery``."""

from __future__ import annotations

import pytest

from app.services.retrieval.channels.lexical import MAX_QUERY_TOKENS, or_query, query_tokens

pytestmark = pytest.mark.unit


def test_a_question_keeps_its_content_words_only():
    assert query_tokens("where is the user defined") == ["user", "defined"]


def test_an_identifier_yields_its_words_and_the_whole_name():
    assert query_tokens("getUserById") == ["get", "user", "id", "getuserbyid"]


def test_terms_are_lowercased_and_deduplicated_in_order():
    assert query_tokens("Parse parse PARSE config") == ["parse", "config"]


def test_snake_case_and_paths_are_split():
    tokens = query_tokens("app/core/security.py verify_password")
    assert tokens[:3] == ["app", "core", "security"]
    assert "verify" in tokens and "password" in tokens


def test_only_stop_words_leave_nothing():
    assert query_tokens("what is the where of a how does it") == []
    assert or_query("what is the") is None


def test_punctuation_is_dropped_so_the_query_is_injection_safe():
    assert or_query("a:* & (b) | !c ' ; --") == "b | c"
    assert or_query("foo & bar | 'baz'") == "foo | bar | baz"


def test_terms_are_joined_with_or():
    assert or_query("bcrypt hashing") == "bcrypt | hashing"


def test_a_huge_query_is_capped():
    assert len(query_tokens(" ".join(f"term{i}" for i in range(500)))) == MAX_QUERY_TOKENS
