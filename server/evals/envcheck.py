"""Side-effect-free helpers that keep the eval harness pointed at its own stack.

Nothing here imports ``app.core.config``: importing it instantiates ``settings`` from
the environment, which is exactly what these helpers exist to control.
"""

from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Literal

from sqlalchemy.engine import make_url

EVAL_DB_PORT = 5434
EVAL_REDIS_PORT = 6381

EVAL_DATABASE_URL = "postgresql+asyncpg://illume:eval@localhost:5434/illume_eval"
EVAL_SYNC_DATABASE_URL = "postgresql://illume:eval@localhost:5434/illume_eval"
EVAL_REDIS_URL = "redis://localhost:6381/0"

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})

# Pinned generator model id for eval runs.
EVAL_GENERATOR_MODEL = "deepseek-flash"

# Keys read from the eval env file. GITHUB_TOKEN and the JUDGE_* keys are used by the harness
# only and are never exported under a name the application reads.
ENV_EVAL_KEYS = (
    "OPENAI_API_KEY",
    "AI_API_KEY",
    "AI_BASE_URL",
    "OPENROUTER_API_KEY",
    "GITHUB_TOKEN",
    "JUDGE_MODEL",
    "JUDGE_BASE_URL",
    "JUDGE_API_KEY",
    "JUDGE_API_STYLE",
)

# Every field of ``app.core.config.Settings``. A test compares this against
# ``Settings.model_fields`` so a new field cannot be added without being pinned here.
EVAL_SETTINGS_FIELDS = (
    "DATABASE_URL",
    "SYNC_DATABASE_URL",
    "REDIS_URL",
    "OPENAI_API_KEY",
    "AI_MODEL",
    "AI_API_KEY",
    "AI_BASE_URL",
    "OPENROUTER_API_KEY",
    "ACCESS_TOKEN_EXPIRE_MINUTES",
    "SECRET_KEY",
    "FRONTEND_URL",
    "ENVIRONMENT",
    "GITHUB_CLIENT_ID",
    "GITHUB_CLIENT_SECRET",
    "GITHUB_REDIRECT_URL",
    "RESEND_API_KEY",
    "CONTACT_TO_EMAIL",
    "CONTACT_FROM_EMAIL",
    "DOMAIN",
    "OAUTH_REDIRECT_ALLOWLIST",
    "MOBILE_TOKEN_EXPIRE_MINUTES",
)


class EvalIsolationError(RuntimeError):
    """Raised when the eval harness could reach something other than the eval stack."""


def assert_eval_url(url: str, *, kind: Literal["database", "redis"]) -> None:
    """Assert that a URL targets the eval stack.

    Args:
        url: The connection URL to check.
        kind: Which service the URL is for.

    Raises:
        EvalIsolationError: If the host is not local, the port is missing, or the port is
            not the eval stack's port for ``kind``.
    """
    expected = EVAL_DB_PORT if kind == "database" else EVAL_REDIS_PORT
    try:
        parsed = make_url(url)
    except Exception as exc:
        raise EvalIsolationError(f"unparseable {kind} URL") from exc
    if parsed.host not in LOCAL_HOSTS:
        raise EvalIsolationError(
            f"{kind} host {parsed.host!r} is not local; the eval stack runs on localhost"
        )
    if parsed.port != expected:
        raise EvalIsolationError(
            f"{kind} port {parsed.port!r} is not the eval stack's port {expected}"
        )


def eval_environment(keys: Mapping[str, str]) -> dict[str, str]:
    """Build a value for every ``Settings`` field.

    Args:
        keys: Real keys read from the eval env file. Absent keys become empty strings.

    Returns:
        A mapping covering every name in ``EVAL_SETTINGS_FIELDS``.
    """
    return {
        "DATABASE_URL": EVAL_DATABASE_URL,
        "SYNC_DATABASE_URL": EVAL_SYNC_DATABASE_URL,
        "REDIS_URL": EVAL_REDIS_URL,
        "OPENAI_API_KEY": keys.get("OPENAI_API_KEY", ""),
        "AI_MODEL": EVAL_GENERATOR_MODEL,
        "AI_API_KEY": keys.get("AI_API_KEY", ""),
        "AI_BASE_URL": keys.get("AI_BASE_URL", ""),
        "OPENROUTER_API_KEY": keys.get("OPENROUTER_API_KEY", ""),
        "ACCESS_TOKEN_EXPIRE_MINUTES": "60",
        "SECRET_KEY": "eval-secret-key-not-for-production",
        "FRONTEND_URL": "http://localhost:3000",
        "ENVIRONMENT": "eval",
        "GITHUB_CLIENT_ID": "eval-github-client-id",
        "GITHUB_CLIENT_SECRET": "eval-github-client-secret",
        "GITHUB_REDIRECT_URL": "http://localhost:8000/api/v1/auth/github/callback",
        "RESEND_API_KEY": "",
        "CONTACT_TO_EMAIL": "",
        "CONTACT_FROM_EMAIL": "",
        "DOMAIN": "localhost",
        "OAUTH_REDIRECT_ALLOWLIST": "[]",
        "MOBILE_TOKEN_EXPIRE_MINUTES": "60",
    }


def uncovered_fields(model_fields: Collection[str]) -> set[str]:
    """Return the ``Settings`` fields that ``eval_environment`` does not set.

    Args:
        model_fields: The field names of ``Settings`` (``Settings.model_fields``).

    Returns:
        Field names missing from ``EVAL_SETTINGS_FIELDS``.
    """
    return set(model_fields) - set(EVAL_SETTINGS_FIELDS)


def read_env_eval(path: Path) -> dict[str, str]:
    """Parse the eval env file.

    Supports blank lines, ``#`` comments, an optional ``export`` prefix and single or
    double quotes around values.

    Args:
        path: The file to read.

    Returns:
        The parsed keys, or an empty dict when the file does not exist.

    Raises:
        EvalIsolationError: On a malformed line or a key that is not recognised.
    """
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep:
            raise EvalIsolationError(f"{path.name}:{number}: expected KEY=VALUE")
        if name not in ENV_EVAL_KEYS:
            raise EvalIsolationError(f"{path.name}:{number}: unknown key {name!r}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[name] = value
    return values


def mask_url(url: str) -> str:
    """Return a URL with its password replaced by ``***``.

    Args:
        url: A connection URL.

    Returns:
        The URL safe to print.
    """
    try:
        parsed = make_url(url)
    except Exception:
        return "<unparseable url>"
    return parsed.render_as_string(hide_password=True)
