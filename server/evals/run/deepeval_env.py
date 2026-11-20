"""The environment DeepEval runs under in the harness, set before it is imported.

DeepEval reads these variables when its settings are first built, so the judge modules import this
one before they import DeepEval. Nothing here reaches the network or the disk: telemetry is off,
dotenv files (which would pick up a developer's own ``.env``) are not read, and no update check
runs.

Library code here takes nothing from ``evals.settings``.
"""

from __future__ import annotations

import os
from importlib import metadata

OFFLINE_ENV: dict[str, str] = {
    "DEEPEVAL_TELEMETRY_OPT_OUT": "1",
    "DEEPEVAL_DISABLE_DOTENV": "1",
    "DEEPEVAL_UPDATE_WARNING_OPT_IN": "0",
    "DEEPEVAL_GRPC_LOGGING": "0",
}
"""The variables forced on, whatever the caller's environment says."""


def configure() -> None:
    """Forces the offline settings into the process environment.

    Safe to call repeatedly. It must run before ``deepeval`` is first imported to take effect.
    """
    os.environ.update(OFFLINE_ENV)


def deepeval_version() -> str:
    """The installed DeepEval release, read without importing the package."""
    return metadata.version("deepeval")


configure()

__all__ = ["OFFLINE_ENV", "configure", "deepeval_version"]
