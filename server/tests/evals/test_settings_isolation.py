"""Isolation tests for ``evals.settings``.

Importing it rewrites the process environment, so the behavioural checks run in a fresh
subprocess. Each child runs in a directory holding a decoy ``.env`` with a sentinel for
every ``Settings`` field and has those fields stripped from its environment, so the only
place a sentinel could come from is a ``.env`` file. Nothing here opens a connection.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.config import Settings
from evals.envcheck import (
    EVAL_DATABASE_URL,
    EVAL_REDIS_URL,
    EVAL_SETTINGS_FIELDS,
    EVAL_SYNC_DATABASE_URL,
    uncovered_fields,
)

pytestmark = pytest.mark.unit

SERVER_ROOT = Path(__file__).resolve().parents[2]
FIELDS = list(Settings.model_fields)
SENTINEL = "DECOY-FROM-DOTENV"


def _sentinel(field: str) -> str:
    # Numeric and list fields must still validate, so their sentinels are shaped
    # accordingly; the string fields carry the marker text.
    if field in ("ACCESS_TOKEN_EXPIRE_MINUTES", "MOBILE_TOKEN_EXPIRE_MINUTES"):
        return "987654"
    if field == "OAUTH_REDIRECT_ALLOWLIST":
        return f'["{SENTINEL}"]'
    return f"{SENTINEL}-{field}"


@pytest.fixture
def decoy_dir(tmp_path: Path) -> Path:
    (tmp_path / ".env").write_text("".join(f"{f}={_sentinel(f)}\n" for f in FIELDS))
    return tmp_path


def _child_env(*, strip_settings: bool) -> dict[str, str]:
    env = dict(os.environ)
    if strip_settings:
        for name in (*FIELDS, "OPENAI_BASE_URL"):
            env.pop(name, None)
    env["PYTHONPATH"] = str(SERVER_ROOT)
    return env


def _run(code: str, *, cwd: Path, strip_settings: bool = True, args=()):
    return subprocess.run(
        [sys.executable, *args, "-c", code],
        cwd=cwd,
        env=_child_env(strip_settings=strip_settings),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_every_settings_field_is_covered():
    assert uncovered_fields(Settings.model_fields) == set()
    assert set(EVAL_SETTINGS_FIELDS) == set(Settings.model_fields)


def test_settings_imported_after_evals_yield_the_eval_urls(decoy_dir: Path):
    result = _run(
        "import json, evals.settings\n"
        "from app.core.config import settings\n"
        "print(json.dumps([settings.DATABASE_URL, settings.SYNC_DATABASE_URL,"
        " settings.REDIS_URL]))\n",
        cwd=decoy_dir,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == [
        EVAL_DATABASE_URL,
        EVAL_SYNC_DATABASE_URL,
        EVAL_REDIS_URL,
    ]


def test_no_setting_comes_from_a_dotenv_file(decoy_dir: Path):
    result = _run(
        "import json, evals.settings\n"
        "from app.core.config import settings\n"
        "print(json.dumps(settings.model_dump()))\n",
        cwd=decoy_dir,
    )
    assert result.returncode == 0, result.stderr
    dumped = json.loads(result.stdout.splitlines()[-1])
    assert set(dumped) == set(FIELDS)
    assert SENTINEL not in json.dumps(dumped)
    assert "987654" not in {str(v) for v in dumped.values()}


def test_importing_app_config_first_is_refused():
    # Run with the test environment intact, so app.core.config binds to the test stack.
    result = _run(
        "import app.core.config\nimport evals.settings\n",
        cwd=SERVER_ROOT,
        strip_settings=False,
    )
    assert result.returncode != 0
    assert "EvalIsolationError" in result.stderr


def test_selftest_runs_without_a_database_and_names_the_target():
    result = subprocess.run(
        [sys.executable, "-m", "evals", "selftest"],
        cwd=SERVER_ROOT,
        env=_child_env(strip_settings=True),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    first = result.stdout.splitlines()[0]
    assert first == "target database: postgresql://illume:***@localhost:5434/illume_eval"
    assert "eval@" not in result.stdout


def test_unbuilt_commands_exit_with_status_two():
    result = subprocess.run(
        [sys.executable, "-m", "evals", "mine"],
        cwd=SERVER_ROOT,
        env=_child_env(strip_settings=True),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 2
    assert result.stdout.splitlines()[0].startswith("target database: ")
