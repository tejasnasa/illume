"""
Persistent clone cache tunables.

The ``ensure_clone`` / ``refresh_clone`` / ``touch`` / ``evict_to_cap`` /
``cache_size`` interface is the contract the sync task will depend on; this
module declares the constants in advance so every other module that needs
them imports from a stable location rather than reading them off the codebase
piecemeal.

A persistent clone is a performance optimization, never a correctness
dependency: every failure mode falls back to a fresh ``tempfile.mkdtemp``
clone, and wiping the cache at any time is safe.
"""

# Total cap on disk the cache is allowed to consume. Conservative on boxes with
# little free space; the live box has 51 GiB free so 2 GiB is comfortably
# affordable.
CLONE_CACHE_MAX_BYTES: int = 2 * 1024 * 1024 * 1024

# Per-repo ceiling so a single large repository cannot evict everything else.
# Picked below ``CLONE_CACHE_MAX_BYTES`` -- the two together ensure that a repo
# larger than this cannot enter the cache at all (and degrades to an ephemeral
# clone instead).
CLONE_CACHE_MAX_REPO_BYTES: int = 512 * 1024 * 1024

# Global kill switch. When False, ``ensure_clone`` falls straight through to
# the ephemeral ``tempfile.mkdtemp`` path.
CLONE_CACHE_ENABLED: bool = True
