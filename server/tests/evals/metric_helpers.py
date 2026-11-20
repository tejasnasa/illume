"""Small builders for metric tests."""

from __future__ import annotations

from typing import Any

from evals.run.records import CandidateRecord, Generation, StepRecordOut


def make_generation(answer: str = "", **fields: Any) -> Generation:
    """A minimal generation record."""
    base: dict[str, Any] = {
        "record_key": "k",
        "item_id": "i",
        "arm": "x",
        "config_hash": "h",
        "model": "m",
        "answer": answer,
    }
    base.update(fields)
    return Generation(**base)


def make_candidate(key: str, rank: int, file_path: str | None = None) -> CandidateRecord:
    """A candidate with the given key and rank."""
    return CandidateRecord(key=key, rank=rank, source_type="symbol", file_path=file_path)


def make_step(index: int, kind: str = "tool_call", **fields: Any) -> StepRecordOut:
    """An agent step."""
    return StepRecordOut(index=index, kind=kind, node="n", **fields)
