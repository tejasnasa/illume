"""Canonical stage and phase identifiers for the ingestion progress stream.

The values in :class:`Stage` are the same strings passed to
:func:`app.services._stage_timer.stage`, so the timing vocabulary and the
live progress vocabulary describe one graph instead of two that drift
apart. ``READY`` is the one exception: it is published as a stage but has
no timer, because nothing times the final status flip.

Both enums are ``StrEnum``, so they serialise as bare strings through the
``json.dumps`` in :mod:`app.services._publish` and no client needs to know
they were ever enums.
"""

from enum import StrEnum


class Stage(StrEnum):
    """A named unit of work in the ingestion pipeline."""

    CLONE = "clone"
    PR_FETCH = "pr_fetch"
    PARSE = "parse"
    RESOLVE_DEPENDENCIES = "resolve_dependencies"
    COMPUTE_FAN_METRICS = "compute_fan_metrics"
    DETECT_STACK = "detect_stack"
    GIT_HISTORY = "git_history"
    CRITICALITY = "criticality"
    GLOSSARY = "glossary"
    READING_ORDER = "reading_order"
    GENERATE_EMBEDDINGS = "generate_embeddings"
    BRIEF = "brief"
    READY = "ready"

    # The two join blocks overlap other work rather than doing any of
    # their own, so they are timed but never rendered as a pipeline node.
    GLOSSARY_AND_READING_ORDER_JOIN = "glossary_and_reading_order_join"
    EMBED_AND_BRIEF_JOIN = "embed_and_brief_join"


class Phase(StrEnum):
    """Where a stage sits in its lifecycle."""

    STARTED = "started"
    PROGRESS = "progress"
    DONE = "done"
    FAILED = "failed"
