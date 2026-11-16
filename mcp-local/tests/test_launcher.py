"""The launcher, run as a subprocess and driven over stdio against a real test backend."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
from conftest import Backend, launcher_env
from mcp import Client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client

LAUNCH_TIMEOUT_SECONDS = 60


@asynccontextmanager
async def direct_client(backend: Backend) -> AsyncIterator[Client]:
    """An SDK client connected to the backend's ``/mcp`` with the seeded token."""
    http_client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {backend.token}"})
    transport = streamable_http_client(f"{backend.url}/mcp", http_client=http_client)
    async with http_client, Client(transport, mode="legacy") as client:
        yield client


@asynccontextmanager
async def launcher_client(backend: Backend, token: str | None = None) -> AsyncIterator[Client]:
    """An SDK client connected to the launcher subprocess over stdio."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "illume_mcp", "--url", backend.url],
        env=launcher_env(backend.token if token is None else token),
    )
    async with Client(params, mode="legacy") as client:
        yield client


def run_launcher(backend: Backend, token: str | None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "illume_mcp", "--url", backend.url],
        env=launcher_env(token),
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=LAUNCH_TIMEOUT_SECONDS,
        check=False,
    )


async def test_initialize_mirrors_the_hosted_server(backend: Backend) -> None:
    async with direct_client(backend) as hosted, launcher_client(backend) as local:
        assert local.instructions == hosted.instructions
        assert local.instructions
        assert local.server_capabilities == hosted.server_capabilities
        assert local.server_info is not None and hosted.server_info is not None
        assert local.server_info.name == hosted.server_info.name


async def test_tools_list_matches_the_hosted_list_exactly(backend: Backend) -> None:
    async with direct_client(backend) as hosted, launcher_client(backend) as local:
        expected = (await hosted.session.list_tools()).model_dump(by_alias=True)
        actual = (await local.session.list_tools()).model_dump(by_alias=True)

    assert actual == expected
    assert len(actual["tools"]) > 15


async def test_call_tool_returns_the_seeded_repository(backend: Backend) -> None:
    async with launcher_client(backend) as local:
        result = await local.call_tool("list_repositories", {})

    assert not result.is_error
    assert backend.repo_name in json.dumps(result.model_dump(by_alias=True))


async def test_call_tool_result_matches_the_hosted_result(backend: Backend) -> None:
    async with direct_client(backend) as hosted, launcher_client(backend) as local:
        expected = await hosted.call_tool("list_repositories", {})
        actual = await local.call_tool("list_repositories", {})

    assert actual.model_dump(by_alias=True) == expected.model_dump(by_alias=True)


async def test_an_error_result_keeps_is_error(backend: Backend) -> None:
    async with direct_client(backend) as hosted, launcher_client(backend) as local:
        expected = await hosted.call_tool("no_such_tool", {})
        actual = await local.call_tool("no_such_tool", {})

    assert expected.is_error
    assert actual.is_error
    assert actual.model_dump(by_alias=True) == expected.model_dump(by_alias=True)


async def test_resources_and_prompts_match_the_hosted_lists(backend: Backend) -> None:
    async with direct_client(backend) as hosted, launcher_client(backend) as local:
        for method in ("list_resources", "list_resource_templates", "list_prompts"):
            expected = await getattr(hosted, method)()
            actual = await getattr(local, method)()
            assert actual.model_dump(by_alias=True) == expected.model_dump(by_alias=True), method

        templates = await local.list_resource_templates()
        prompts = await local.list_prompts()

    assert len(templates.resource_templates) == 2
    assert len(prompts.prompts) == 4


async def test_resource_read_returns_the_overview(backend: Backend) -> None:
    uri = f"illume://repo/{backend.repo_number}/overview"
    async with direct_client(backend) as hosted, launcher_client(backend) as local:
        expected = await hosted.read_resource(uri)
        actual = await local.read_resource(uri)

    assert actual.contents
    assert actual.model_dump(by_alias=True) == expected.model_dump(by_alias=True)


async def test_get_prompt_matches_the_hosted_prompt(backend: Backend) -> None:
    async with direct_client(backend) as hosted, launcher_client(backend) as local:
        name = (await hosted.list_prompts()).prompts[0].name
        arguments = {
            arg.name: str(backend.repo_number)
            for arg in (await hosted.list_prompts()).prompts[0].arguments or []
        }
        expected = await hosted.get_prompt(name, arguments)
        actual = await local.get_prompt(name, arguments)

    assert actual.model_dump(by_alias=True) == expected.model_dump(by_alias=True)


def test_a_bad_token_exits_non_zero_without_echoing_it(backend: Backend) -> None:
    bad_token = "ilm_this-token-was-never-issued-0123456789"

    result = run_launcher(backend, bad_token)

    assert result.returncode != 0
    assert "invalid or revoked" in result.stderr
    assert "Settings" in result.stderr
    assert bad_token not in result.stderr + result.stdout


def test_a_missing_token_exits_non_zero_with_the_instruction(backend: Backend) -> None:
    result = run_launcher(backend, None)

    assert result.returncode != 0
    assert "ILLUME_MCP_TOKEN" in result.stderr


def test_there_is_no_token_flag() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "illume_mcp", "--token", "x"],
        env=launcher_env("irrelevant"),
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=LAUNCH_TIMEOUT_SECONDS,
        check=False,
    )

    assert result.returncode != 0
    assert "unrecognized arguments" in result.stderr
