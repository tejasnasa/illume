"""Claim splitting: where a reader would end a sentence, and what counts as a claim."""

from __future__ import annotations

import pytest

from app.services.agent.claims import (
    ClaimSpan,
    extract_marks,
    looks_factual,
    mark_answer,
    mark_for,
    split_claims,
)
from app.services.agent.state import ClaimVerdict

pytestmark = pytest.mark.unit


def texts(answer: str) -> list[str]:
    return [claim.text for claim in split_claims(answer)]


class TestSplitting:
    def test_a_sentence_with_a_citation_is_a_claim(self):
        answer = "Passwords are hashed with bcrypt [F:app/auth/security.py:4-8]."

        [claim] = split_claims(answer)

        assert claim.text == answer
        assert claim.keys == ("F:app/auth/security.py:4-8",)
        assert claim.uncited is False

    def test_a_code_span_does_not_end_a_sentence(self):
        answer = "The call `foo.bar()` returns a value. It is safe."

        assert texts(answer) == ["The call `foo.bar()` returns a value."]

    def test_an_inline_key_does_not_end_a_sentence(self):
        answer = (
            "`verify_password` lives in app/auth/security.py "
            "[F:app/auth/security.py:4-8]. It returns a bool."
        )

        [claim] = split_claims(answer)

        assert claim.text.startswith("`verify_password`")
        assert claim.keys == ("F:app/auth/security.py:4-8",)

    def test_a_file_path_with_dots_does_not_end_a_sentence(self):
        answer = "See app/main.py for the setup. It uses FastAPI."

        assert texts(answer) == ["See app/main.py for the setup.", "It uses FastAPI."]

    def test_an_abbreviation_does_not_end_a_sentence(self):
        answer = "Use e.g. app/auth/security.py for hashing. It is safe."

        assert texts(answer) == ["Use e.g. app/auth/security.py for hashing."]

    def test_a_decimal_does_not_end_a_sentence(self):
        answer = "Version 1.5 is used. It is new."

        assert texts(answer) == ["Version 1.5 is used."]

    def test_list_items_are_separate_claims(self):
        answer = (
            "- `verify_password` lives in app/auth/security.py.\n- `hash_password` lives nearby."
        )

        claims = split_claims(answer)

        assert [claim.text for claim in claims] == [
            "`verify_password` lives in app/auth/security.py.",
            "`hash_password` lives nearby.",
        ]
        assert [claim.index for claim in claims] == [1, 2]

    def test_a_heading_is_not_a_claim(self):
        answer = "## How it works\n\nThere are 3 modules."

        assert texts(answer) == ["There are 3 modules."]

    def test_plain_prose_without_a_key_path_symbol_or_number_is_skipped(self):
        answer = "The server starts quickly and stays reliable."

        assert split_claims(answer) == ()


class TestClaimDetection:
    @pytest.mark.parametrize(
        "sentence",
        [
            "The entry point is app/main.py.",
            "`verify_password` does the work.",
            "It has 12 lines.",
            "The helper is `create_user`.",
        ],
    )
    def test_a_fact_names_a_path_symbol_or_number(self, sentence):
        assert looks_factual(sentence)

    @pytest.mark.parametrize(
        "sentence",
        [
            "The server starts quickly.",
            "It is reliable.",
            "This paragraph explains the idea in ordinary words.",
        ],
    )
    def test_plain_prose_is_not_a_fact(self, sentence):
        assert not looks_factual(sentence)


class TestMarks:
    def test_the_mark_names_the_verdict(self):
        assert mark_for(ClaimVerdict.SUPPORTED) == "[[verify:supported]]"
        assert mark_for(ClaimVerdict.PARTIALLY_SUPPORTED) == "[[verify:partially_supported]]"
        assert mark_for(ClaimVerdict.UNSUPPORTED) == "[[verify:unsupported]]"
        assert mark_for(ClaimVerdict.CONTRADICTED) == "[[verify:contradicted]]"
        assert mark_for(ClaimVerdict.UNRESOLVED_KEY) == "[[verify:unresolved_key]]"
        assert mark_for(None) == "[[verify:uncited]]"

    def test_marks_are_readable_back(self):
        answer = "One [F:a.py:1-2]. [[verify:supported]] Two. [[verify:uncited]]"

        assert [verdict for _, verdict in extract_marks(answer)] == ["supported", "uncited"]

    def test_marking_adds_text_and_deletes_nothing(self):
        answer = "Passwords use bcrypt [F:a.py:1-2]."
        claims = split_claims(answer)

        marked = mark_answer(answer, claims, {1: "[[verify:supported]]"})

        assert marked == "Passwords use bcrypt [F:a.py:1-2]. [[verify:supported]]"
        assert answer in marked
        assert isinstance(claims[0], ClaimSpan)
