"""The Model Context Protocol server that exposes Illume's repository knowledge to AI tools."""

import logging


def _ensure_call_logs_are_emitted(log: logging.Logger) -> None:
    """Give the MCP layer's per-call log lines a handler of their own.

    The API process configures no logging, so the root logger drops anything below
    WARNING and the one line per tool call would never reach the container log.
    The handler is added once, on the package logger, so every module below it is
    covered; propagation stays on, so anything that does configure the root logger
    (or a test capturing records) still receives the lines.

    Args:
        log: The package logger.
    """
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s %(message)s"))
        log.addHandler(handler)
    log.setLevel(logging.INFO)


_ensure_call_logs_are_emitted(logging.getLogger(__name__))
