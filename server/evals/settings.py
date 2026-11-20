"""Process-wide configuration for the eval harness.

Importing this module has a deliberate side effect: it rewrites ``os.environ`` so that
``app.core.config`` resolves to the isolated eval stack, with every ``Settings`` field set
explicitly so nothing can fall through to ``server/.env``. It must be imported before
anything under ``app``, and only the CLI entry point does so. Library code under
``evals/`` takes what it needs as parameters.
"""

import os
import sys
from pathlib import Path

from evals.envcheck import (
    ENV_EVAL_KEYS,
    EVAL_DATABASE_URL,
    EVAL_REDIS_URL,
    EVAL_SYNC_DATABASE_URL,
    EvalIsolationError,
    assert_eval_url,
    eval_environment,
    read_env_eval,
)

EVALS_DIR = Path(__file__).resolve().parent
ENV_EVAL_PATH = EVALS_DIR / ".env.eval"
OUT_DIR = EVALS_DIR / "out"
CLONES_DIR = OUT_DIR / "clones"

# Spending limits for the starter run, in US dollars.
STARTER_BUDGET_USD = 10.0
STARTER_STOP_USD = 9.50


def _refuse_if_app_config_already_loaded() -> None:
    """Refuse to run when ``app.core.config`` was imported against another stack.

    Raises:
        EvalIsolationError: If ``app.core.config`` is already loaded and its URLs are not
            the eval stack's.
    """
    module = sys.modules.get("app.core.config")
    if module is None:
        return
    loaded = module.settings
    if (
        loaded.SYNC_DATABASE_URL != EVAL_SYNC_DATABASE_URL
        or loaded.DATABASE_URL != EVAL_DATABASE_URL
        or loaded.REDIS_URL != EVAL_REDIS_URL
    ):
        raise EvalIsolationError(
            "app.core.config was imported before evals.settings and is bound to another "
            "stack; import evals.settings first"
        )


_refuse_if_app_config_already_loaded()

_keys = read_env_eval(ENV_EVAL_PATH)
_environment = eval_environment(_keys)

assert_eval_url(_environment["SYNC_DATABASE_URL"], kind="database")
assert_eval_url(_environment["DATABASE_URL"], kind="database")
assert_eval_url(_environment["REDIS_URL"], kind="redis")

os.environ.update(_environment)

DATABASE_URL = _environment["DATABASE_URL"]
SYNC_DATABASE_URL = _environment["SYNC_DATABASE_URL"]
REDIS_URL = _environment["REDIS_URL"]

# Used by mining only; deliberately not exported under any name the application reads.
GITHUB_TOKEN = _keys.get("GITHUB_TOKEN", "")


def require_github_token() -> str:
    """Return the GitHub token, failing clearly when it is not configured.

    Returns:
        The token from ``server/evals/.env.eval``.

    Raises:
        EvalIsolationError: If the token is empty.
    """
    if not GITHUB_TOKEN:
        raise EvalIsolationError("GITHUB_TOKEN is not set in server/evals/.env.eval")
    return GITHUB_TOKEN


def require_key(name: str) -> str:
    """Return a configured key, failing clearly when it is empty.

    Args:
        name: One of ``OPENAI_API_KEY``, ``AI_API_KEY``, ``AI_BASE_URL``,
            ``OPENROUTER_API_KEY`` or ``GITHUB_TOKEN``.

    Returns:
        The key's value.

    Raises:
        EvalIsolationError: If the name is not recognised or its value is empty.
    """
    if name == "GITHUB_TOKEN":
        return require_github_token()
    if name not in ENV_EVAL_KEYS:
        raise EvalIsolationError(f"unknown key {name!r}")
    value = _keys.get(name, "")
    if not value:
        raise EvalIsolationError(f"{name} is not set in server/evals/.env.eval")
    return value
