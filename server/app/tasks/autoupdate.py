"""
Auto-update sweep tunables and dispatch glue.

The sweep itself lives in this module only as a placeholder; the actual
``sweep_due_repositories`` task lands alongside the scheduler. The constants
are declared here from day one so every other module that needs them imports
from a stable location rather than reading them off the codebase piecemeal.

Constants are module-level, not ``Settings`` fields, on purpose: every field of
``Settings`` is required and ``.env`` is gitignored, so a new field is another
way for a fresh checkout or a standalone script to fail to instantiate. A code
change plus a deploy is the intent for every value below.
"""

# Global kill switch. When False, the sweep returns without enqueuing anything.
# Set False to disable auto-update across the whole deployment without touching
# any individual repository's toggle.
AUTO_UPDATE_ENABLED: bool = True

# How often the beat process wakes and asks the database which repos are due.
# 10 minutes gives a 6-hour-interval repo a six-tick window of latency without
# dominating the database with sweeps.
SWEEP_INTERVAL_MINUTES: int = 10

# How long a sync holds its lease before another sync (or the next sweep on a
# crashed worker) may reclaim the repo. Picked generously above the slowest
# realistic sync (large repo, full LLM pass) so a still-running sync is never
# stolen, but tight enough that a SIGKILL'd worker hands control back within a
# reasonable window.
SYNC_LEASE_MINUTES: int = 60

# Thresholds at which an incremental update gives up and falls back to a full
# re-ingest. Cheap deterministic work scales linearly with the diff, but past
# some size the bookkeeping is more expensive than rebuilding from scratch.

# Hard cap on changed-file count. Above this, full rebuild -- correct and the
# only safe option.
SYNC_FULL_MAX_FILES: int = 500

# Soft cap: changed files as a fraction of the repo's total file count. A change
# that touches most of the repo is a re-ingest in all but name.
SYNC_FULL_MAX_RATIO: float = 0.5

# Failure isolation: after this many consecutive sync failures the auto-update
# toggle flips itself off, the UI shows "paused after N failures", and the user
# is expected to investigate rather than have the worker keep hammering.
SYNC_MAX_CONSECUTIVE_FAILURES: int = 3

# Backoff base for ``next_sync_at`` after a sync failure, in minutes. Doubles on
# each consecutive failure up to ``SYNC_MAX_CONSECUTIVE_FAILURES`` -- so a repo
# that fails once waits 5 minutes, fails twice waits 10, fails three times
# pauses outright.
SYNC_BACKOFF_BASE_MINUTES: int = 5
