"""
A minimal OpenAI-compatible server for the E2E stack.

    uv run python scripts/openai_stub_server.py          # :8099

The E2E API runs with ``OPENAI_BASE_URL`` pointed here, which the OpenAI SDK honours by
default, so every LLM call the *server* makes lands on this process instead of
api.openai.com. That matters for one spec in particular: the chat flow runs
``answer_question``, which embeds the query and then generates an answer, and both are real
network calls from the API's point of view.

Why a server rather than a patch. The in-process fake in ``tests/fixtures/openai_stub.py``
replaces the client object, which works because a pytest process owns the code under test.
An E2E run does not: the API is a separate process reached over HTTP, so the only seam
available is the socket. This module shares one value with the seed -- `RETRIEVABLE_VECTOR`
-- so a query's embedding lands at distance 0 from the chunks the seed stored, which is
what makes retrieval return anything at all.

Two endpoints, both of which the SDK parses from the wire:

- ``POST /v1/responses`` -- ``client.responses.create``, returning ``output_text``. The
  SDK derives ``output_text`` by concatenating the text parts of ``output``.
- ``POST /v1/embeddings`` -- ``client.embeddings.create``, 1536 dimensions to match the
  ``Vector(1536)`` column, carrying the value the seed stored.

Not a general emulator: it answers a fixed sentence for any prompt and ignores the model
name. It exists so the E2E suite has no external dependency, not to be faithful.
"""

import sys
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

# Running this as a script puts `scripts/` on sys.path, not the server root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.factories import RETRIEVABLE_VECTOR  # noqa: E402

EMBEDDING_MODEL = "text-embedding-3-small"

# Canned, and deliberately not derived from the prompt. The chat spec asserts that an
# answer arrives and renders; a prompt-dependent answer would be a second thing that can
# drift, and the pipeline that consumes prompt-dependent output is covered in-process.
ANSWER = (
    "Based on the indexed sources, `func_0` is the first function in the fixture "
    "repository, and `src/module_0.py` contains it."
)

app = FastAPI(title="OpenAI stub")


class _ResponsesRequest(BaseModel):
    """Only the fields the stub reads; the rest of the payload is ignored."""

    model: str | None = None
    input: object | None = None
    max_output_tokens: int | None = None


class _EmbeddingsRequest(BaseModel):
    """Same: the stub needs the input texts and nothing else."""

    model: str | None = None
    input: str | list[str]


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness, so the E2E config can wait for the stub rather than racing it."""
    return {"status": "ok"}


@app.post("/v1/responses")
async def responses(_body: _ResponsesRequest) -> dict:
    """
    Answer a Responses API call.

    The `output` shape is what the SDK's `output_text` helper walks: a list of items, each
    with a list of content parts, of which only the `output_text` parts contribute.
    """
    return {
        "id": "resp_stub",
        "object": "response",
        "created_at": 0,
        "model": "stub",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "id": "msg_stub",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": ANSWER, "annotations": []}],
            }
        ],
        "parallel_tool_calls": False,
        "tool_choice": "none",
        "tools": [],
    }


@app.post("/v1/embeddings")
async def embeddings(body: _EmbeddingsRequest) -> dict:
    """
    Answer an embeddings call with the seeded vector, not a text-derived one.

    Retrieval filters candidates on `cosine_distance < 0.7`. Two unrelated 1536-dimension
    vectors are near-orthogonal, so a hash-derived query vector sits at distance ~1.0 from
    every seeded chunk, nothing survives the filter, and `answer_question` returns its
    canned "No relevant code was found" answer *without calling the model at all*. The
    chat spec would then assert against a path that never reached this server.

    Returning the same constant the seed stored gives distance 0, so retrieval returns the
    top-K chunks and the answer path is genuinely exercised. The consequence is that
    ranking is meaningless here -- every chunk is equidistant -- which is fine: what this
    spec checks is that an answer and its citations reach the browser, and ordering is
    covered by the backend's retrieval tests.
    """
    texts = body.input if isinstance(body.input, list) else [body.input]
    return {
        "object": "list",
        "model": EMBEDDING_MODEL,
        "data": [
            {"object": "embedding", "index": index, "embedding": list(RETRIEVABLE_VECTOR)}
            for index, _ in enumerate(texts)
        ],
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8099, log_level="info")
