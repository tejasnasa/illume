"""The recorder that sits between a run and the database.

Uses a stand-in session opener that keeps the rows it is asked to insert, so the
queueing, batching, coalescing and caps are checked without a database.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any

import pytest

from app.services.agent import persistence
from app.services.agent.events import EventType
from app.services.agent.persistence import RunRecorder
from app.services.agent.steps import StepRecord

pytestmark = pytest.mark.unit


class FakeSession:
    def __init__(self, store: list[dict[str, Any]], fail: bool) -> None:
        self._store, self._fail = store, fail

    async def execute(self, statement: Any, rows: list[dict[str, Any]]) -> None:
        if self._fail:
            raise RuntimeError("the database is down")
        self._store.extend(rows)

    async def commit(self) -> None:
        return None


class FakeOpener:
    def __init__(self, *, fail: bool = False, delay: float = 0.0) -> None:
        self.rows: list[dict[str, Any]] = []
        self.fail = fail
        self.delay = delay

    def __call__(self):
        @asynccontextmanager
        async def open_session():
            if self.delay:
                await asyncio.sleep(self.delay)
            yield FakeSession(self.rows, self.fail)

        return open_session()


def recorder(opener: FakeOpener | None = None, **limits: int) -> tuple[RunRecorder, FakeOpener]:
    opener = opener or FakeOpener()
    return RunRecorder(uuid.uuid4(), opener, **limits), opener  # type: ignore[arg-type]


def step(index: int, kind: str = "tool_call", **payload: Any) -> StepRecord:
    return StepRecord(index=index, kind=kind, node="tools", payload=payload)  # type: ignore[arg-type]


def drained(rec: RunRecorder) -> list[Any]:
    items = []
    while not rec.stream.empty():
        items.append(rec.stream.get_nowait())
    return items


class TestDeltas:
    async def test_a_token_stream_becomes_a_few_chunks_with_nothing_lost(self):
        rec, opener = recorder()

        for letter in "abcdefghij" * 100:
            await rec.emit("answer_delta", {"text": letter})
        rec.flush_deltas()
        await rec.close()

        events = drained(rec)
        assert "".join(e.data["text"] for e in events) == "abcdefghij" * 100
        assert 1 < len(events) <= 12
        assert [r["payload"]["text"] for r in opener.rows] == [e.data["text"] for e in events]

    async def test_buffered_text_is_flushed_before_the_next_event(self):
        rec, _ = recorder()

        await rec.emit("answer_delta", {"text": "partial"})
        await rec.emit("tool_call", {"tool": "search_code"})

        assert [e.type for e in drained(rec)] == [EventType.ANSWER_DELTA, EventType.TOOL_CALL]

    async def test_text_from_different_lanes_is_not_merged(self):
        rec, _ = recorder()

        await rec.emit("answer_delta", {"text": "one", "worker_id": "w1"})
        await rec.emit("answer_delta", {"text": "two", "worker_id": "w2"})
        rec.flush_deltas()

        events = drained(rec)
        assert [(e.worker_id, e.data["text"]) for e in events] == [("w1", "one"), ("w2", "two")]


class TestSequence:
    async def test_events_and_steps_share_one_increasing_counter(self):
        rec, opener = recorder()

        await rec.emit("evidence", {"keys": ["F:a.py"]})
        await rec.record(step(0, input_tokens=10, output_tokens=2))
        await rec.emit("tool_call", {"tool": "search_code"})
        await rec.close()

        assert [r["seq"] for r in opener.rows] == [1, 2, 3]
        assert [r["kind"] for r in opener.rows] == ["event", "tool_call", "event"]
        step_row = opener.rows[1]
        assert (step_row["tokens_in"], step_row["tokens_out"]) == (10, 2)
        assert step_row["payload"]["step_index"] == 0

    async def test_the_streamed_envelope_and_the_stored_row_agree(self):
        rec, opener = recorder()

        await rec.emit("evidence", {"keys": ["F:a.py"], "worker_id": "w1"})
        await rec.close()

        [event] = drained(rec)
        [row] = opener.rows
        assert (event.seq, event.worker_id, event.type.value) == (row["seq"], "w1", row["name"])
        assert event.data == row["payload"]
        assert event.ts == persistence._iso(row["created_at"])


class TestCaps:
    async def test_steps_past_the_cap_are_counted_not_stored(self):
        rec, opener = recorder(max_steps=2)

        for index in range(5):
            await rec.record(step(index))
        await rec.close()

        assert len(opener.rows) == 2
        assert rec.dropped == 3

    async def test_events_past_the_cap_still_stream_but_the_terminal_one_is_stored(self):
        rec, opener = recorder(max_events=3)

        for n in range(6):
            await rec.emit("evidence", {"keys": [f"F:{n}.py"]})
        rec.publish(EventType.DONE, {"run_id": "r", "answer": "a", "stop_reason": "finished"})
        await rec.close()

        assert len(drained(rec)) == 7
        assert [r["name"] for r in opener.rows] == ["evidence"] * 3 + ["done"]
        assert rec.dropped == 3

    async def test_the_two_caps_are_independent(self):
        rec, opener = recorder(max_steps=1, max_events=1)

        await rec.record(step(0))
        await rec.emit("evidence", {"keys": ["F:a.py"]})
        await rec.record(step(1))
        await rec.emit("evidence", {"keys": ["F:b.py"]})
        await rec.close()

        assert sorted(r["kind"] for r in opener.rows) == ["event", "tool_call"]

    async def test_a_large_payload_is_truncated_with_a_marker(self):
        rec, opener = recorder()

        await rec.record(step(0, text="x" * 200_000))
        await rec.close()

        assert opener.rows[0]["payload"]["truncated"] is True


class TestFailures:
    async def test_a_failing_write_is_announced_once_and_never_raised(self):
        rec, opener = recorder(FakeOpener(fail=True))

        for n in range(5):
            await rec.emit("evidence", {"keys": [f"F:{n}.py"]})
            await asyncio.sleep(0)
        await rec.close()

        degraded = [e for e in drained(rec) if e.type is EventType.DEGRADED]
        assert len(degraded) == 1
        assert degraded[0].data["stage"] == "recording"
        assert rec.write_failures >= 1
        assert opener.rows == []

    async def test_close_waits_for_queued_rows(self):
        rec, opener = recorder(FakeOpener(delay=0.05))

        await rec.emit("evidence", {"keys": ["F:a.py"]})
        assert opener.rows == []
        await rec.close()

        assert len(opener.rows) == 1

    async def test_close_gives_up_after_its_timeout(self):
        rec, opener = recorder(FakeOpener(delay=5))

        await rec.emit("evidence", {"keys": ["F:a.py"]})
        await rec.close(timeout=0.05)

        assert opener.rows == []

    async def test_end_stream_flushes_text_and_closes_the_queue(self):
        rec, _ = recorder()

        await rec.emit("answer_delta", {"text": "tail"})
        rec.end_stream()

        items = drained(rec)
        assert items[0].data["text"] == "tail" and items[-1] is None
