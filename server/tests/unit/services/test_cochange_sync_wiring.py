"""The incremental sync rebuilds co-change inside its deterministic step."""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.tasks.sync as sync_module

pytestmark = pytest.mark.unit

STEPS = (
    "apply_file_delta",
    "analyze_git_history",
    "build_cochange",
    "delete_repo_edges",
    "resolve_dependencies",
    "compute_fan_metrics",
    "run_criticality_scoring",
    "detect_stack",
    "detect_entry_points",
)


def test_the_rebuild_follows_git_history_and_shares_the_steps_session(monkeypatch):
    calls: list[tuple[str, object]] = []

    def recorder(name: str, result=None):
        def record(db, *args, **kwargs):
            calls.append((name, db))
            return result

        return record

    for name in STEPS:
        result = (0, 0, 0, []) if name == "apply_file_delta" else None
        monkeypatch.setattr(sync_module, name, recorder(name, result))
    monkeypatch.setattr(sync_module, "detect_stack", lambda root: [])
    monkeypatch.setattr(sync_module, "detect_entry_points", lambda root: [])
    db = MagicMock()
    repo = SimpleNamespace(id=uuid.uuid4(), ingested_commit_sha="a" * 40)

    sync_module._run_step_a(db, repo, Path("."), [("M", "a.py")])

    order = [name for name, _ in calls]
    assert order.index("build_cochange") == order.index("analyze_git_history") + 1
    assert order.index("build_cochange") < order.index("delete_repo_edges")
    cochange_db = next(db_ for name, db_ in calls if name == "build_cochange")
    assert cochange_db is db
    # The caller owns the transaction, so the step itself commits nothing.
    db.commit.assert_not_called()
