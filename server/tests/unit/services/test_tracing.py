"""Opt-in chat tracing: off unless enabled, and a pure passthrough while off."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from openai import AsyncOpenAI

from app.services import tracing

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)


def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")


class TestEnabled:
    def test_off_by_default(self):
        assert tracing.tracing_enabled() is False

    def test_needs_the_key(self, monkeypatch):
        monkeypatch.setenv("LANGSMITH_TRACING", "true")
        assert tracing.tracing_enabled() is False
        monkeypatch.setenv("LANGSMITH_API_KEY", "  ")
        assert tracing.tracing_enabled() is False

    @pytest.mark.parametrize("value", ["", "false", "0"])
    def test_needs_tracing_true(self, monkeypatch, value):
        monkeypatch.setenv("LANGSMITH_TRACING", value)
        monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
        assert tracing.tracing_enabled() is False

    def test_on_with_both(self, monkeypatch):
        _enable(monkeypatch)
        assert tracing.tracing_enabled() is True


class TestWrapClient:
    def test_returns_the_client_unchanged_without_a_key(self, monkeypatch):
        monkeypatch.setenv("LANGSMITH_TRACING", "true")
        client = AsyncOpenAI(api_key="sk-test")
        original = client.responses.create
        assert tracing.wrap_client(client) is client
        assert client.responses.create == original

    def test_returns_the_client_unchanged_when_tracing_is_off(self, monkeypatch):
        monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
        client = AsyncOpenAI(api_key="sk-test")
        original = client.responses.create
        assert tracing.wrap_client(client) is client
        assert client.responses.create == original

    def test_wraps_when_enabled(self, monkeypatch):
        _enable(monkeypatch)
        client = AsyncOpenAI(api_key="sk-test")
        original = client.responses.create
        wrapped = tracing.wrap_client(client)
        assert wrapped.responses.create != original

    def test_does_not_wrap_twice(self, monkeypatch):
        _enable(monkeypatch)
        client = tracing.wrap_client(AsyncOpenAI(api_key="sk-test"))
        patched = client.responses.create
        assert tracing.wrap_client(client).responses.create is patched

    def test_leaves_the_base_url_to_the_sdk(self, monkeypatch):
        _enable(monkeypatch)
        monkeypatch.setenv("OPENAI_BASE_URL", "http://stub.test/v1")
        client = tracing.wrap_client(AsyncOpenAI(api_key="sk-test"))
        assert str(client.base_url).startswith("http://stub.test/v1")


class TestTraced:
    async def test_passes_arguments_and_result_through_when_off(self):
        @tracing.traced("sample")
        async def add(a: int, b: int, *, scale: int = 1) -> int:
            return (a + b) * scale

        assert await add(1, 2, scale=3) == 9

    async def test_exceptions_propagate_when_off(self):
        @tracing.traced("sample")
        async def boom() -> None:
            raise ValueError("nope")

        with pytest.raises(ValueError, match="nope"):
            await boom()

    async def test_keeps_the_function_metadata(self):
        @tracing.traced("sample")
        async def documented() -> None:
            """Docs."""

        assert documented.__name__ == "documented"
        assert documented.__doc__ == "Docs."

    async def test_does_not_build_a_run_when_off(self, monkeypatch):
        def fail(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("traceable must not be used while tracing is off")

        monkeypatch.setattr("langsmith.traceable", fail)

        @tracing.traced("sample")
        async def value() -> str:
            return "ok"

        assert await value() == "ok"


class TestMetadata:
    def test_noop_when_off(self, monkeypatch):
        def fail() -> None:
            raise AssertionError("no run should be looked up while tracing is off")

        monkeypatch.setattr("langsmith.run_helpers.get_current_run_tree", fail)
        tracing.add_trace_metadata(repo_id="r")

    def test_noop_without_an_open_run(self, monkeypatch):
        _enable(monkeypatch)
        monkeypatch.setattr("langsmith.run_helpers.get_current_run_tree", lambda: None)
        tracing.add_trace_metadata(repo_id="r")

    def test_attaches_to_the_open_run(self, monkeypatch):
        _enable(monkeypatch)
        seen: list[dict[str, Any]] = []
        run = SimpleNamespace(add_metadata=seen.append)
        monkeypatch.setattr("langsmith.run_helpers.get_current_run_tree", lambda: run)
        tracing.add_trace_metadata(repo_id="r", chunks_retrieved=3)
        assert seen == [{"repo_id": "r", "chunks_retrieved": 3}]
