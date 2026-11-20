"""The metric self-test runs clean in-process and from the command line."""

import subprocess
import sys
from pathlib import Path

import pytest

import evals.metrics.selftest  # noqa: F401
from evals import selftest_registry

pytestmark = pytest.mark.unit

SERVER_ROOT = Path(__file__).resolve().parents[2]


def test_every_selftest_case_passes():
    passed, failed = selftest_registry.run_all()
    assert failed == []
    assert len(passed) >= 20


def test_the_selftest_command_exits_zero_and_reports_its_cases():
    result = subprocess.run(
        [sys.executable, "-m", "evals", "selftest"],
        cwd=SERVER_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    summary = [line for line in result.stdout.splitlines() if "passed" in line][-1]
    assert int(summary.split()[0]) >= 20
    assert "0 failed" in summary
