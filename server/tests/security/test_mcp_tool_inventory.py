"""Guards the MCP tool surface against drift, the way the IDOR matrix guards the routes.

The tool list is derived from what the MCP server registers, not written by hand. Every
tool that takes a ``repo`` must refuse another user's repository, whichever way it is
named, and refuse a missing one. A tool without a ``repo`` argument must be named in
:data:`NO_REPO_TOOLS`, so adding a tool that addresses no repository (or forgetting
the argument on one that should) fails here until someone decides it is intended.
The two resource templates that address a repository get the same treatment.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote

import pytest
from mcp import MCPError
from mcp_types import Tool

from app.mcp.account_tools import build_account_tools
from app.mcp.ask import build_ask_tool
from app.mcp.limits import RateLimiter
from app.mcp.resources import RESOURCE_TEMPLATES
from app.mcp.tools import build_repository_tools
from tests.factories import make_repo, make_user

pytestmark = pytest.mark.security

NO_REPO_TOOLS = frozenset({"whoami", "list_repositories"})
"""Tools that act on the token's owner as a whole and so take no repository."""

NOT_FOUND = "No repository matches"
VICTIM_NAME = "vault-internal"
VICTIM_URL = "https://github.com/victimorg/vault-internal"


def registered_tools() -> dict[str, Tool]:
    """Every tool the MCP server registers, by name.

    Built from the same builders :func:`app.mcp.server.build_mcp` composes, so a
    builder added there but not here is caught by the comparison with ``tools/list``
    below. Building a tool touches neither the database nor Redis.
    """
    limiter = RateLimiter(lambda: None)
    built = [
        *build_account_tools(None, limiter),  # type: ignore[arg-type]
        *build_repository_tools(None, limiter),  # type: ignore[arg-type]
        build_ask_tool(None, limiter),  # type: ignore[arg-type]
    ]
    return {tool.definition.name: tool.definition for tool in built}


TOOLS = registered_tools()
REPO_TOOLS = sorted(
    name for name, tool in TOOLS.items() if "repo" in tool.input_schema["properties"]
)


def filler_arguments(tool: Tool) -> dict[str, Any]:
    """Valid-looking values for every required argument except ``repo``."""
    schema = tool.input_schema
    values: dict[str, Any] = {}
    for name in schema.get("required", []):
        if name == "repo":
            continue
        prop = schema["properties"][name]
        kind = prop.get("type")
        if "enum" in prop:
            values[name] = prop["enum"][0]
        elif kind == "integer":
            values[name] = 1
        elif kind == "number":
            values[name] = 1.0
        elif kind == "boolean":
            values[name] = True
        elif kind == "array":
            values[name] = ["x"]
        else:
            values[name] = "x"
    return values


def text_of(result) -> str:
    return "\n".join(block.text for block in result.content) + json.dumps(result.structured_content)


@pytest.fixture
async def victim_repo(db_session):
    """A ready repository owned by someone other than the token's owner."""
    victim = await make_user(db_session)
    return await make_repo(db_session, victim, name=VICTIM_NAME, github_url=VICTIM_URL)


def references(repo) -> list[str]:
    """The ways a client can name ``repo``: number, UUID and owner/name in two cases."""
    return [
        str(repo.repo_number),
        str(repo.id),
        "victimorg/vault-internal",
        "VICTIMORG/Vault-Internal",
    ]


def without(text: str, ref: str) -> str:
    """``text`` minus the reference the caller itself supplied, which an error may echo."""
    return text.replace(unquote(ref), "").replace(ref, "")


class TestTheInventory:
    def test_the_sweep_is_not_vacuous(self):
        assert len(REPO_TOOLS) >= 15
        assert {"search_code", "read_file", "ask_illume"} <= set(REPO_TOOLS)

    def test_every_tool_without_a_repo_is_on_the_allow_list(self):
        without_repo = {name for name in TOOLS if name not in REPO_TOOLS}

        assert without_repo == NO_REPO_TOOLS, (
            "A tool takes no `repo` argument and is not in NO_REPO_TOOLS (or an allow-listed "
            f"tool gained one): {sorted(without_repo ^ NO_REPO_TOOLS)}"
        )

    def test_a_repo_argument_is_a_required_string(self):
        for name in REPO_TOOLS:
            schema = TOOLS[name].input_schema
            assert schema["properties"]["repo"]["type"] == "string", name
            assert "repo" in schema["required"], name

    async def test_the_registered_tools_are_exactly_what_the_server_lists(self, mcp_client):
        listed = {tool.name for tool in (await mcp_client.list_tools()).tools}

        assert listed == set(TOOLS)

    def test_every_resource_template_addresses_a_repo(self):
        assert {t.name for t in RESOURCE_TEMPLATES} == {"overview", "reading-order"}
        assert all("{repo}" in t.uri_template for t in RESOURCE_TEMPLATES)


@pytest.mark.parametrize("name", REPO_TOOLS)
class TestRepoTools:
    async def test_another_users_repository_is_refused_however_it_is_named(
        self, name, victim_repo, mcp_client
    ):
        texts = set()
        for ref in references(victim_repo):
            result = await mcp_client.call_tool(
                name, {"repo": ref, **filler_arguments(TOOLS[name])}
            )

            text = text_of(result)
            assert result.is_error is True, f"{name} accepted {ref!r}"
            assert NOT_FOUND in text
            assert VICTIM_NAME not in without(text, ref)
            assert str(victim_repo.id) not in without(text, ref)
            assert result.structured_content is None
            texts.add(text.replace(ref, "<ref>"))

        # The wording is the one a repository that does not exist at all gets.
        missing = await mcp_client.call_tool(
            name, {"repo": "nobody/nothing", **filler_arguments(TOOLS[name])}
        )
        assert text_of(missing).replace("nobody/nothing", "<ref>") in texts

    @pytest.mark.parametrize("value", [None, "", "   ", [], {}, True, 1.5])
    async def test_a_missing_or_unusable_repo_is_rejected(
        self, name, value, victim_repo, mcp_client
    ):
        arguments = filler_arguments(TOOLS[name])
        for sent in (arguments, {**arguments, "repo": value}):
            try:
                result = await mcp_client.call_tool(name, sent)
            except MCPError:
                continue
            assert result.is_error is True, f"{name} accepted repo={sent.get('repo')!r}"
            assert VICTIM_NAME not in text_of(result)


@pytest.mark.parametrize("name", sorted(NO_REPO_TOOLS))
async def test_a_tool_without_a_repo_shows_only_the_callers_own_data(name, victim_repo, mcp_client):
    result = await mcp_client.call_tool(name, {})

    assert result.is_error is not True
    assert VICTIM_NAME not in text_of(result)
    assert str(victim_repo.id) not in text_of(result)


@pytest.mark.parametrize("template", [t.uri_template for t in RESOURCE_TEMPLATES])
class TestResourceTemplates:
    async def test_another_users_repository_is_refused_however_it_is_named(
        self, template, victim_repo, mcp_client
    ):
        refs = [*references(victim_repo), "victimorg%2Fvault-internal"]
        for ref in refs:
            with pytest.raises(MCPError) as caught:
                await mcp_client.read_resource(template.replace("{repo}", ref))

            assert NOT_FOUND in caught.value.message
            assert VICTIM_NAME not in without(caught.value.message, ref)

    @pytest.mark.parametrize("ref", ["", "%20", "%20%20"])
    async def test_a_blank_repo_is_rejected(self, template, ref, mcp_client):
        with pytest.raises(MCPError):
            await mcp_client.read_resource(template.replace("{repo}", ref))
