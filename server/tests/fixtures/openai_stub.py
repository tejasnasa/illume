"""A deterministic stand-in for the OpenAI client.

One mocking implementation is shared by every test that needs the LLM. This is it, as an
in-process fake rather than an HTTP server: the services construct `OpenAI(api_key=...)`
inside the function that uses it, so patching the class on each service module is both
simpler and more precise than standing up a socket. The property that matters is the
same either way -- one implementation, deterministic output, no network.

It answers by *reading the prompt*, which is what makes it useful for pipeline tests: the
glossary needs definitions for the symbols actually present, and the reading order needs
annotations for the files actually in the order. A stub that returned a fixed list would
let a wiring bug pass, because the persistence code would still have something to store.

Vectors are derived from the text rather than random, so the same chunk always embeds to
the same point -- which is what lets a retrieval test assert anything about ordering.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

EMBEDDING_MODEL = "text-embedding-3-small"
DIMENSIONS = 1536

# The vector the E2E seed stores for every chunk and the E2E stub returns for every query.
#
# Retrieval filters candidates on `cosine_distance < 0.7`, and two unrelated 1536-dimension
# vectors are near-orthogonal -- so a text-derived query vector sits at distance ~1.0 from
# every seeded chunk, nothing survives the filter, and `answer_question` returns its canned
# "no relevant code" answer without calling the model at all. One shared constant gives
# distance 0, which is what makes the chat path reachable in E2E.
#
# It lives here, rather than in `factories.py`, because a real HTTP server imports it:
# `factories.py` pulls in `app.core.config`, which instantiates `Settings()` at import time
# and would make the stub depend on the whole application environment.
RETRIEVABLE_VECTOR: list[float] = [0.1] * DIMENSIONS

# `Name: <symbol>` on its own line, as `glossary_builder._build_prompt` renders it.
_GLOSSARY_ENTRY = re.compile(r"^Name: (.+)$", re.MULTILINE)
# `file_path=<path> | fan_in=...`, as `onboarding._build_annotation_prompt` renders it.
_ANNOTATED_FILE = re.compile(r"file_path=(\S+) \|")


def deterministic_vector(text: str, dimensions: int = DIMENSIONS) -> list[float]:
    """
    A unit vector derived from `text`.

    Built from a SHA-256 digest expanded across the dimensions, then normalised. Not
    semantically meaningful -- two chunks that mean the same thing will not be close --
    but stable and correctly shaped, which is what the schema and the distance operator
    need in order to be exercised.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    raw = [(digest[i % len(digest)] / 255.0) - 0.5 for i in range(dimensions)]
    norm = sum(component * component for component in raw) ** 0.5 or 1.0
    return [component / norm for component in raw]


@dataclass
class _TextResponse:
    output_text: str


@dataclass
class _EmbeddingItem:
    embedding: list[float]
    index: int


@dataclass
class _EmbeddingResponse:
    data: list[_EmbeddingItem]


class _Responses:
    def __init__(self, owner: FakeOpenAI):
        self._owner = owner

    def create(self, *, model=None, input=None, **kwargs) -> _TextResponse:
        self._owner.calls.append({"kind": "responses", "model": model, "input": input})
        prompt = _flatten_prompt(input)
        return _TextResponse(output_text=self._owner.answer_for(prompt))


class _Embeddings:
    def __init__(self, owner: FakeOpenAI):
        self._owner = owner

    def create(self, *, model=None, input=None, **kwargs) -> _EmbeddingResponse:
        texts = input if isinstance(input, list) else [input]
        self._owner.calls.append({"kind": "embeddings", "model": model, "count": len(texts)})
        self._owner.embedded_texts.extend(texts)
        return _EmbeddingResponse(
            data=[
                _EmbeddingItem(embedding=deterministic_vector(text), index=index)
                for index, text in enumerate(texts)
            ]
        )


class FakeOpenAI:
    """Stands in for `openai.OpenAI`; records what it was asked and answers deterministically."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.calls: list[dict] = []
        self.embedded_texts: list[str] = []
        self.responses = _Responses(self)
        self.embeddings = _Embeddings(self)

    def answer_for(self, prompt: str) -> str:
        """Route a prompt to the shape of answer it is asking for."""
        if "file_path=" in prompt and "annotation" in prompt:
            return self._annotations(prompt)
        if "Name:" in prompt and "definition" in prompt:
            return self._definitions(prompt)
        # The architecture narrative is free text; the caller stores it as-is.
        return "A small service that reads files and answers questions about them."

    def _definitions(self, prompt: str) -> str:
        names = []
        for name in _GLOSSARY_ENTRY.findall(prompt):
            name = name.strip()
            if name and name not in names:
                names.append(name)
        return json.dumps(
            [{"name": name, "definition": f"Definition for {name}."} for name in names]
        )

    def _annotations(self, prompt: str) -> str:
        paths = []
        for path in _ANNOTATED_FILE.findall(prompt):
            if path and path not in paths:
                paths.append(path)
        return json.dumps(
            [{"file_path": path, "annotation": f"Read {path} to get oriented."} for path in paths]
        )


def _flatten_prompt(payload: Any) -> str:
    """
    Reduce the Responses API `input` argument to a single string.

    Callers pass either a plain string or a list of `{"role", "content"}` dicts, and the
    fake needs the text either way.
    """
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        parts = []
        for item in payload:
            if isinstance(item, dict):
                content = item.get("content")
                parts.append(content if isinstance(content, str) else "")
        return "\n".join(parts)
    return ""


def install(monkeypatch) -> FakeOpenAI:
    """
    Patch every module that constructs an OpenAI client, and return the fake.

    Two import styles are in play and both need covering:

    * `from openai import OpenAI` -- the name is bound in the service module at import
      time, so the module's own attribute is what the call resolves.
    * `import openai` then `openai.OpenAI(...)` -- `onboarding` does this, and patching
      the service module would find no attribute to replace.

    So the `openai` module's own attribute is patched as well. `AsyncOpenAI` is included
    for `rag.py`, which the pipeline task does not call but which a chat test would.
    """
    import openai

    from app.services import architecture_brief, embedder, glossary_builder, onboarding, rag

    fake = FakeOpenAI()
    factory = lambda *args, **kwargs: fake  # noqa: E731

    monkeypatch.setattr(openai, "OpenAI", factory)
    monkeypatch.setattr(openai, "AsyncOpenAI", factory)

    for module in (architecture_brief, embedder, glossary_builder, onboarding):
        if hasattr(module, "OpenAI"):
            monkeypatch.setattr(module, "OpenAI", factory)
    if hasattr(rag, "AsyncOpenAI"):
        monkeypatch.setattr(rag, "AsyncOpenAI", factory)

    return fake
