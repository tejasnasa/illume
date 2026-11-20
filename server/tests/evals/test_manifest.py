"""Tests for the run manifest."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from evals.manifest import build_manifest, file_sha256, git_state, write_manifest

pytestmark = pytest.mark.unit

STAMP = datetime(2026, 11, 19, 12, 0, 0, tzinfo=UTC)


def _inputs(**overrides):
    inputs = {
        "arms": {"b": "hash-b", "a": "hash-a"},
        "prompt_version": "p1",
        "models": {"generator": "deepseek-v4-1-flash-1017"},
        "reported_snapshots": {"generator": "snap-1"},
        "price_table_version": "2026-11",
        "agent_token_cap": 50000,
        "corpus_pins": {"repo": "abc123"},
        "split_hash": "split-hash",
        "eval_instruction": "Answer from the code.",
        "git": {"sha": "deadbeef", "dirty": True},
        "uv_lock_sha256": "lockhash",
        "created_at": STAMP,
    }
    inputs.update(overrides)
    return inputs


def test_manifest_carries_every_recorded_field():
    manifest = build_manifest(**_inputs())
    assert set(manifest) == {
        "git_sha",
        "dirty",
        "uv_lock_sha256",
        "arms",
        "prompt_version",
        "models",
        "reported_snapshots",
        "price_table_version",
        "agent_token_cap",
        "corpus_pins",
        "split_hash",
        "eval_instruction",
        "created_at",
    }
    assert manifest["git_sha"] == "deadbeef"
    assert manifest["uv_lock_sha256"] == "lockhash"
    assert manifest["created_at"] == "2026-11-19T12:00:00+00:00"


def test_a_dirty_tree_is_recorded_not_refused():
    dirty = build_manifest(**_inputs(git={"sha": "x", "dirty": True}))
    clean = build_manifest(**_inputs(git={"sha": "x", "dirty": False}))
    assert dirty["dirty"] is True
    assert clean["dirty"] is False


def test_output_is_deterministic_and_sorted(tmp_path: Path):
    first = write_manifest(tmp_path / "one", **_inputs()).read_text()
    second = write_manifest(tmp_path / "two", **_inputs()).read_text()
    assert first == second
    parsed = json.loads(first)
    assert list(parsed) == sorted(parsed)
    assert list(parsed["arms"]) == ["a", "b"]
    assert first.startswith('{\n  "agent_token_cap"')


def test_write_manifest_creates_the_directory(tmp_path: Path):
    path = write_manifest(tmp_path / "deep" / "out", **_inputs())
    assert path.name == "manifest.json"
    assert path.is_file()


def test_defaults_are_read_from_the_environment():
    manifest = build_manifest(**_inputs(git=None, uv_lock_sha256=None, created_at=None))
    assert "dirty" in manifest
    assert manifest["uv_lock_sha256"] is None or len(manifest["uv_lock_sha256"]) == 64
    assert manifest["created_at"].endswith("+00:00")


def test_git_state_outside_a_repository_is_tolerated(tmp_path: Path):
    state = git_state(tmp_path)
    assert set(state) == {"sha", "dirty"}


def test_file_sha256(tmp_path: Path):
    path = tmp_path / "f"
    path.write_bytes(b"abc")
    assert file_sha256(path) == ("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
    assert file_sha256(tmp_path / "missing") is None
