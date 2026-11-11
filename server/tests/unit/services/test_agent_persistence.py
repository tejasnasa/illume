"""Payload caps, citation shapes and the interrupted-run rule, without a database."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.agent.persistence import (
    MAX_PAYLOAD_BYTES,
    STALE_RUN_SECONDS,
    citation_from_evidence,
    public_status,
    sanitize_payload,
)
from app.services.agent.state import Evidence

pytestmark = pytest.mark.unit


class TestPayloadCap:
    def test_a_small_payload_is_kept_as_it_is(self):
        payload = {"keys": ["F:a.py"], "n": 1, "nested": {"ok": True}}

        assert sanitize_payload(payload) == payload

    def test_an_oversized_payload_is_replaced_by_a_marker_under_the_cap(self):
        payload = {"text": "x" * (MAX_PAYLOAD_BYTES * 2)}

        stored = sanitize_payload(payload)

        assert stored["truncated"] is True
        assert stored["bytes"] > MAX_PAYLOAD_BYTES
        assert stored["preview"].startswith('{"text": "xxx')
        assert len(json.dumps(stored).encode()) < MAX_PAYLOAD_BYTES

    def test_a_payload_at_the_cap_is_not_truncated(self):
        overhead = len(json.dumps({"t": ""}).encode())
        payload = {"t": "y" * (MAX_PAYLOAD_BYTES - overhead)}

        assert sanitize_payload(payload) == payload

    def test_multibyte_text_is_measured_in_bytes_and_cut_on_a_character(self):
        payload = {"t": "é" * MAX_PAYLOAD_BYTES}

        stored = sanitize_payload(payload)

        assert stored["truncated"] is True
        stored["preview"].encode("utf-8")

    def test_nul_characters_that_jsonb_cannot_hold_are_removed(self):
        assert sanitize_payload({"t": "a\x00b"}) == {"t": "ab"}

    def test_the_literal_text_backslash_u_zero_survives_while_a_real_nul_goes(self):
        literal = "x = '\\u0000'"
        payload = {
            "t": "a\x00b " + literal,
            "n\x00k": ["\x00", (literal, "c\x00")],
        }

        stored = sanitize_payload(payload)

        assert stored == {"t": "ab " + literal, "nk": ["", [literal, "c"]]}
        assert "\x00" not in json.dumps(stored, ensure_ascii=False)

    def test_values_that_are_not_json_are_stringified(self):
        identifier = uuid.uuid4()

        assert sanitize_payload({"id": identifier}) == {"id": str(identifier)}


class TestCitations:
    def test_a_code_range_is_a_symbol_citation(self):
        citation = citation_from_evidence("F:app/a.py:10-20", Evidence(key="k", text="body"))

        assert (citation.source_type, citation.file_path) == ("symbol", "app/a.py")
        assert (citation.start_line, citation.end_line) == (10, 20)
        assert citation.chunk_text == "body" and citation.key == "F:app/a.py:10-20"

    def test_a_whole_file_is_a_file_citation(self):
        citation = citation_from_evidence("F:app/a.py", None)

        assert citation.source_type == "file" and citation.start_line is None

    def test_a_commit_a_pull_request_and_a_readme_section(self):
        assert citation_from_evidence("C:abcd1234", None).commit_hash == "abcd1234"
        assert citation_from_evidence("PR:42", None).pr_number == 42
        assert citation_from_evidence("D:README#install", None).source_type == "document"

    def test_evidence_text_is_capped(self):
        citation = citation_from_evidence("F:a.py", Evidence(key="k", text="z" * 100_000))

        assert len(citation.chunk_text) <= 4000


class TestInterrupted:
    NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)

    def run(self, status="running", age=timedelta(0)):
        return SimpleNamespace(status=status, created_at=self.NOW - age)

    def test_a_quiet_running_run_is_interrupted(self):
        run = self.run(age=timedelta(seconds=STALE_RUN_SECONDS + 1))

        assert public_status(run, None, self.NOW) == "interrupted"

    def test_recent_activity_keeps_a_long_run_running(self):
        run = self.run(age=timedelta(hours=1))

        assert public_status(run, self.NOW - timedelta(seconds=5), self.NOW) == "running"

    def test_a_young_run_is_running(self):
        assert public_status(self.run(), None, self.NOW) == "running"

    @pytest.mark.parametrize("status", ["done", "failed", "cancelled"])
    def test_a_run_that_ended_keeps_its_status(self, status):
        run = self.run(status=status, age=timedelta(days=3))

        assert public_status(run, None, self.NOW) == status
