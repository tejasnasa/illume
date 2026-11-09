"""The public event schema and the translation from a run's internal events.

The schema snapshot is what the client's types are checked against: a change to
any event's data fails here until the snapshot is regenerated and the client side
updated with it. The registries drive the rest, so a new internal event or a new
public type is covered the day it is added.
"""

from __future__ import annotations

import json

import pytest

from app.services.agent.events import (
    EVENT_MODELS,
    TERMINAL_TYPES,
    Event,
    EventTranslator,
    EventType,
    StreamEvent,
    event_schema,
)
from tests.fixtures.golden import assert_matches_golden

pytestmark = pytest.mark.unit

# Internal events that are deliberately not public, with the record that says it instead.
NOT_PUBLIC = {
    Event.RUN_STARTED: "the route announces the run, with the preset",
    Event.NODE: "main-agent nodes are internal; worker nodes are translated",
    Event.MODEL_CALL: "kept as a step; usage arrives in done",
    Event.ANSWER: "superseded by done",
    Event.RUN_FINISHED: "superseded by done",
}

SAMPLES: dict[Event, dict] = {
    Event.ROUTE: {
        "route": "local",
        "accepted": False,
        "confidence": 0.4,
        "probabilities": {"local": 0.4, "global": 0.3},
        "model": "jev",
    },
    Event.SEED: {"keys": ["F:a.py:1-2"], "standalone_question": "q", "channels": {"dense": 3}},
    Event.PLAN: {
        "skipped": False,
        "subquestions": [{"id": "a", "question": "first?", "focus": "code"}],
        "synthesis_hint": "",
        "model": "m",
    },
    Event.THINKING: {"iteration": 0, "text": "Looking."},
    Event.TOOL_CALL: {"call_id": "c1", "tool": "search_code", "arguments": "{}", "step": 3},
    Event.TOOL_RESULT: {
        "call_id": "c1",
        "tool": "search_code",
        "status": "ok",
        "elapsed_ms": 12.5,
        "truncated": False,
        "error_type": None,
        "step": 3,
        "result_count": 2,
        "summary": "2 citable item(s)",
    },
    Event.NODES: {"call_id": "c1", "tool": "get_importers", "paths": ["a.py"], "action": "touched"},
    Event.EVIDENCE: {"keys": ["F:a.py:1-2"]},
    Event.COMPACTED: {
        "trigger": "window",
        "replaced": 4,
        "estimated_tokens_before": 100,
        "estimated_tokens_after": 50,
        "context_window": 250000,
    },
    Event.ANSWER_DELTA: {"text": "Hello"},
    Event.DEGRADED: {"stage": "budget", "limit": "max_tool_calls", "used": 60, "allowed": 60},
    Event.ERROR: {"kind": "auth", "message": "Provider rejected the API key", "status": 502},
    Event.WORKER_FAILED: {"worker_id": "w1", "subquestion": "q", "kind": "auth", "message": "no"},
}


def test_every_public_type_has_a_data_model():
    assert set(EVENT_MODELS) == set(EventType)


def test_the_terminal_types_are_done_and_error():
    assert TERMINAL_TYPES == {EventType.DONE, EventType.ERROR}


def test_the_schema_snapshot_matches(update_golden):
    rendered = json.dumps(event_schema(), indent=2, sort_keys=True)

    assert_matches_golden("agent_event_schema.json", rendered + "\n", update_golden)


def test_the_schema_covers_every_type_and_the_envelope():
    schema = event_schema()

    assert set(schema["events"]) == {t.value for t in EventType}
    assert set(schema["envelope"]["properties"]) == {
        "seq",
        "ts",
        "run_id",
        "worker_id",
        "type",
        "data",
    }


def test_every_internal_event_is_translated_or_accounted_for():
    """A new internal event fails here until it is mapped or listed as not public."""
    unaccounted = set(Event) - set(SAMPLES) - set(NOT_PUBLIC)
    assert unaccounted == set(), f"neither translated nor listed as internal: {unaccounted}"


@pytest.mark.parametrize("name", sorted(SAMPLES, key=str), ids=str)
def test_a_translated_event_validates_against_its_model(name):
    translated = EventTranslator().translate(name.value, SAMPLES[name])

    assert len(translated) == 1
    event = translated[0]
    assert event.type in EVENT_MODELS
    EVENT_MODELS[event.type].model_validate(event.data)


@pytest.mark.parametrize("name", sorted(NOT_PUBLIC, key=str), ids=str)
def test_events_that_are_not_public_translate_to_nothing(name):
    payload = {"node": "agent", "phase": "started"} if name is Event.NODE else {"x": 1}

    assert EventTranslator().translate(name.value, payload) == []


def test_an_unknown_internal_event_translates_to_nothing():
    assert EventTranslator().translate("something_new", {"a": 1}) == []


def translate_one(name: Event, payload=None, translator=None):
    [only] = (translator or EventTranslator()).translate(
        name.value, payload if payload is not None else SAMPLES[name]
    )
    return only


class TestMapping:
    def test_seed_becomes_a_retrieval_from_the_seed(self):
        event = translate_one(Event.SEED)

        assert event.type is EventType.RETRIEVAL
        assert event.data["source"] == "seed"
        assert event.data["channels"] == {"dense": 3}

    def test_route_reports_whether_it_fell_back(self):
        event = translate_one(Event.ROUTE)

        assert event.type is EventType.ROUTE
        assert event.data["fell_back"] is True
        assert event.data["probabilities"]["local"] == 0.4

    def test_a_tool_result_carries_latency_summary_and_count(self):
        event = translate_one(Event.TOOL_RESULT)

        assert event.data["latency_ms"] == 12.5
        assert event.data["result_count"] == 2
        assert event.data["summary"] == "2 citable item(s)"

    def test_compaction_is_a_context_degradation(self):
        event = translate_one(Event.COMPACTED)

        assert event.type is EventType.DEGRADED
        assert event.data["stage"] == "context"
        assert event.data["detail"]["replaced"] == 4

    def test_a_failed_worker_is_a_degradation_of_the_worker_stage(self):
        event = translate_one(Event.WORKER_FAILED)

        assert event.type is EventType.DEGRADED
        assert event.data["stage"] == "worker"
        assert event.data["reason"] == "no"

    def test_extra_degradation_fields_land_under_detail(self):
        event = translate_one(
            Event.DEGRADED, {"stage": "rerank", "reranker": "jev", "reason": "no key"}
        )

        assert event.data["stage"] == "rerank"
        assert event.data["detail"] == {"reranker": "jev"}

    def test_the_worker_tag_moves_to_the_envelope(self):
        [event] = EventTranslator().translate(
            Event.TOOL_CALL.value, {"tool": "search_code", "worker_id": "w2"}
        )

        assert event.worker_id == "w2"
        assert "worker_id" not in event.data

    def test_workers_become_started_and_done_with_their_question(self):
        translator = EventTranslator()
        translate_one(Event.PLAN, translator=translator)

        [started] = translator.translate(
            "node", {"node": "worker", "phase": "started", "worker_id": "w1"}
        )
        [done] = translator.translate(
            "node",
            {
                "node": "worker",
                "phase": "done",
                "worker_id": "w1",
                "status": "completed",
                "stop_reason": "finished",
            },
        )

        assert started.type is EventType.WORKER_STARTED
        assert started.data == {"worker_id": "w1", "question": "first?"}
        assert done.type is EventType.WORKER_DONE
        assert done.data["stop_reason"] == "finished" and done.data["question"] == "first?"

    def test_the_main_agents_nodes_are_not_public(self):
        assert EventTranslator().translate("node", {"node": "agent", "phase": "started"}) == []

    def test_fields_outside_the_schema_are_dropped(self):
        event = translate_one(
            Event.EVIDENCE, {"keys": ["F:a.py"], "api_key": "sk-secret", "text": "raw source"}
        )

        assert event.data == {"keys": ["F:a.py"]}

    def test_a_malformed_payload_is_dropped_rather_than_sent(self):
        assert (
            EventTranslator().translate("evidence", {"keys": "not-a-list-of-keys-but-a-str"}) == []
        )
        assert EventTranslator().translate("tool_call", {}) == []


class TestEnvelope:
    def test_the_envelope_round_trips_through_json(self):
        event = StreamEvent(
            seq=3,
            ts="2026-11-07T00:00:00.000000+00:00",
            run_id="r",
            worker_id=None,
            type=EventType.EVIDENCE,
            data={"keys": ["F:a.py"]},
        )

        assert StreamEvent.model_validate_json(event.model_dump_json()) == event
