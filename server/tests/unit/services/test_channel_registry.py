"""The channel registry."""

from __future__ import annotations

import pytest

from app.services.retrieval.channels import get_channel, get_expansion_channel

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("kind", ["dense", "lexical", "symbol", "grep", "history"])
def test_each_searching_channel_is_registered_under_its_own_kind(kind):
    assert get_channel(kind).kind == kind


@pytest.mark.parametrize("kind", ["graph", "cochange", "nonsense"])
def test_unregistered_kinds_raise_a_readable_error(kind):
    with pytest.raises(KeyError, match="no channel registered"):
        get_channel(kind)


@pytest.mark.parametrize("kind", ["graph", "cochange"])
def test_each_expansion_channel_is_registered_under_its_own_kind(kind):
    assert get_expansion_channel(kind).kind == kind


@pytest.mark.parametrize("kind", ["dense", "history", "nonsense"])
def test_searching_kinds_are_not_expansion_channels(kind):
    with pytest.raises(KeyError, match="no expansion channel registered"):
        get_expansion_channel(kind)
