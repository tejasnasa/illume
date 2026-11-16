"""What the repository tools advertise, derived from the registry rather than a hand-kept list."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.mcp.context import MCP_PIPELINE, build_tool_context
from app.mcp.tools import (
    DESCRIPTION_OVERRIDES,
    MCP_EXCLUDED,
    REPO_DESCRIPTION,
    TITLES,
    exposed_tools,
    mcp_description,
    mcp_input_schema,
)
from app.services.agent.tools import REGISTRY
from app.services.retrieval.config import STRUCTURAL
from app.services.retrieval.embedding import embed_texts

EXPOSED = [tool.name for tool in exposed_tools()]


def test_every_registry_tool_is_exposed_except_the_excluded_ones():
    assert set(EXPOSED) == set(REGISTRY.names()) - MCP_EXCLUDED
    assert "finish" not in EXPOSED


def test_every_exposed_tool_has_a_title():
    assert set(EXPOSED) <= set(TITLES)


def test_an_override_names_an_exposed_tool():
    assert set(DESCRIPTION_OVERRIDES) <= set(EXPOSED)


@pytest.mark.parametrize("name", EXPOSED)
def test_the_schema_adds_a_required_repo_and_keeps_the_tools_own_arguments(name):
    tool = REGISTRY.get(name)
    own = tool.input_model.model_json_schema()

    schema = mcp_input_schema(tool)

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["repo"] == {"type": "string", "description": REPO_DESCRIPTION}
    assert schema["required"][0] == "repo"
    assert schema["required"][1:] == own.get("required", [])
    assert {k: v for k, v in schema["properties"].items() if k != "repo"} == own.get(
        "properties", {}
    )
    assert schema.get("$defs") == own.get("$defs")
    assert "repo" not in own.get("properties", {})


@pytest.mark.parametrize("name", EXPOSED)
def test_a_description_does_not_speak_of_the_agent_loop(name):
    description = mcp_description(REGISTRY.get(name)).lower()

    for phrase in ("finish", "the run", "the agent", "budget"):
        assert phrase not in description, phrase
    assert "`repo`" in description


def test_the_registry_description_is_left_alone():
    assert "chat" in REGISTRY.get("search_code").description


def test_the_pipeline_has_every_model_stage_off_and_the_structural_channels():
    assert MCP_PIPELINE.name == "mcp"
    assert MCP_PIPELINE.query.transform == "identity"
    assert MCP_PIPELINE.query.condense is False
    assert MCP_PIPELINE.rerank.kind == "none"
    assert MCP_PIPELINE.execution == "single_shot"
    assert MCP_PIPELINE.channels == STRUCTURAL.channels


def test_the_tool_context_is_for_one_repository_with_no_budget_and_no_events():
    repo = SimpleNamespace(
        id=uuid4(),
        github_url="https://github.com/acme/widgets",
        ingested_branch="main",
        ingested_commit_sha="a" * 40,
    )
    factory = object()

    ctx = build_tool_context(repo, "gh-token", session_factory=factory)  # type: ignore[arg-type]

    assert ctx.repository.id == repo.id
    assert ctx.repository.ingested_commit_sha == "a" * 40
    assert ctx.session_factory is factory
    assert ctx.github_token == "gh-token"
    assert ctx.pipeline is MCP_PIPELINE
    assert ctx.budget is None
    assert ctx.question is None
    assert ctx.embed is embed_texts
