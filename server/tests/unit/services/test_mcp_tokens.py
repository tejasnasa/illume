"""The pure parts of the MCP token service: the token shape and its hash."""

from __future__ import annotations

import re

import pytest

from app.services.mcp_tokens import TOKEN_PREFIX, hash_token

pytestmark = pytest.mark.unit


def test_a_hash_is_a_deterministic_sha256_hex_digest():
    first = hash_token("ilm_example")

    assert first == hash_token("ilm_example")
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert first != hash_token("ilm_example2")


def test_the_prefix_is_the_documented_marker():
    assert TOKEN_PREFIX == "ilm_"
