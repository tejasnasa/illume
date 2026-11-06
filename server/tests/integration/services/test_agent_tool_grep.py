"""``grep_code`` refusals, reached through the tool's own argument handling.

The searches themselves are covered with the channel; these show that a bad
pattern comes back to the model as a readable result and leaves the session usable.
"""

from __future__ import annotations

from functools import partial

import pytest

from app.services.agent.tools import REGISTRY
from app.services.agent.tools import search as search_tools
from app.services.retrieval.channels.grep import grep_symbols
from tests.factories import make_file, make_repo, make_symbol, make_user
from tests.fixtures.agent_tools import make_tool_context, session_factory_for
from tests.fixtures.retrieval import seed_repo

pytestmark = pytest.mark.integration


async def test_an_overlong_pattern_is_an_argument_error(db_session):
    repo = await make_repo(db_session, await make_user(db_session))
    ctx = make_tool_context(session_factory_for(db_session.bind), repo)

    result = await REGISTRY.call("grep_code", {"pattern": "a" * 201}, ctx)

    assert result.status == "invalid_arguments"
    assert "`pattern` must be at most 200 characters" in result.text


async def test_an_invalid_regex_is_reported_and_the_next_search_works(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))
    ctx = make_tool_context(session_factory_for(db_session.bind), seeded.repo)

    result = await REGISTRY.call("grep_code", {"pattern": "(unclosed"}, ctx)

    assert result.status == "ok"
    assert result.data["refusal_reason"] == "invalid_regex"
    assert "not a valid regular expression" in result.text
    later = await REGISTRY.call("grep_code", {"pattern": "bcrypt"}, ctx)
    assert later.data["total"] == 2


async def test_a_pathological_pattern_is_reported_as_too_expensive(db_session, monkeypatch):
    repo = await make_repo(db_session, await make_user(db_session))
    file = await make_file(db_session, repo, path="long.py")
    await make_symbol(db_session, file, name="long_line", source_code="a" * 3000 + "!")
    ctx = make_tool_context(session_factory_for(db_session.bind), repo)
    # The tool searches with the channel's two-second limit; a short one keeps the test quick.
    monkeypatch.setattr(search_tools, "grep_symbols", partial(grep_symbols, timeout_ms=150))

    result = await REGISTRY.call("grep_code", {"pattern": r"^(.*)(.*)(.*)(.*)(.*)\1\2\3\4\5$"}, ctx)

    assert result.status == "ok"
    assert result.data["refusal_reason"] == "timeout"
    assert "too expensive" in result.text
