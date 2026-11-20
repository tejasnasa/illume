"""The frozen tuning/test split, its lock file and the pre-registration guard.

Items are split by hash, stratified by repository and family, with every cluster (both
variants of a pull request) kept in one slice. The lock records the ids of each slice and a
SHA-256 of the canonical test file, so any later edit to a test item is detected. The pilot
has no tuning/test split: every item goes in one ``pilot`` slice.

Generation on a frozen slice must follow a pre-registration committed to git; the commit is
the timestamp, so "frozen" means tracked and unmodified.
"""

import hashlib
import json
import subprocess
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.gold.schema import GoldItem, canonical_json, write_jsonl

DEFAULT_TUNING_FRACTION = 0.2
PILOT = "pilot"
TUNING = "tuning"
TEST = "test"

PREREG_FILES = {TEST: "v1.md", PILOT: "pilot.md"}
LOCK_NAME = "split.lock.json"


class SplitLockError(RuntimeError):
    """Raised when the items no longer match the lock."""


class PreregNotFrozen(RuntimeError):
    """Raised when a generation run is attempted without a frozen pre-registration."""


@dataclass(frozen=True)
class Split:
    """Items assigned to slices.

    Attributes:
        seed: The seed the assignment hashes with.
        tuning_fraction: The tuning share used; 0 for a pilot.
        slices: Items by slice name (``tuning`` and ``test``, or ``pilot``), each sorted by id.
        frozen_slice: The slice the lock hashes: ``test``, or ``pilot``.
    """

    seed: int
    tuning_fraction: float
    slices: dict[str, tuple[GoldItem, ...]]
    frozen_slice: str

    @property
    def tuning(self) -> tuple[GoldItem, ...]:
        """The tuning slice; empty for a pilot."""
        return self.slices.get(TUNING, ())

    @property
    def test(self) -> tuple[GoldItem, ...]:
        """The test slice; empty for a pilot."""
        return self.slices.get(TEST, ())


def _digest(seed: int, unit: str) -> str:
    return hashlib.sha256(f"{seed}:{unit}".encode()).hexdigest()


def _by_id(items: Iterable[GoldItem]) -> tuple[GoldItem, ...]:
    return tuple(sorted(items, key=lambda item: item.id))


def make_split(
    items: Iterable[GoldItem], *, seed: int, tuning_fraction: float = DEFAULT_TUNING_FRACTION
) -> Split:
    """Split items into tuning and test, stratified by repository and family.

    Items sharing a cluster form one unit and always land together; an item without a
    cluster is its own unit. A cluster is stratified by its smallest-id member. Within a
    stratum the units are ordered by a hash of ``f"{seed}:{cluster_or_id}"`` and the first
    ``round(tuning_fraction * units)`` go to tuning, so the result does not depend on
    input order or on any random state.

    Args:
        items: Every item to assign.
        seed: The hashing seed.
        tuning_fraction: The share of units, per stratum, that go to tuning.

    Returns:
        The split, frozen on the test slice.
    """
    units: dict[str, list[GoldItem]] = defaultdict(list)
    for item in items:
        units[item.cluster or item.id].append(item)
    strata: dict[tuple[str, str], list[str]] = defaultdict(list)
    for unit, members in units.items():
        lead = min(members, key=lambda member: member.id)
        strata[(lead.repo, lead.family)].append(unit)

    tuning: list[GoldItem] = []
    test: list[GoldItem] = []
    for key in sorted(strata):
        ordered = sorted(strata[key], key=lambda unit: (_digest(seed, unit), unit))
        cut = int(tuning_fraction * len(ordered) + 0.5)
        for position, unit in enumerate(ordered):
            (tuning if position < cut else test).extend(units[unit])
    return Split(
        seed=seed,
        tuning_fraction=tuning_fraction,
        slices={TUNING: _by_id(tuning), TEST: _by_id(test)},
        frozen_slice=TEST,
    )


def make_pilot(items: Iterable[GoldItem], *, seed: int = 0) -> Split:
    """Put every item in one ``pilot`` slice; the starter run has no tuning/test split.

    Args:
        items: Every item.
        seed: Recorded in the lock for reference; it does not affect the assignment.

    Returns:
        A split whose only slice is ``pilot``.
    """
    return Split(
        seed=seed,
        tuning_fraction=0.0,
        slices={PILOT: _by_id(items)},
        frozen_slice=PILOT,
    )


def slice_text(items: Iterable[GoldItem]) -> str:
    """The canonical JSONL text of a slice: sorted by id, exactly what ``write_jsonl`` writes."""
    return "".join(
        canonical_json(item.model_dump(mode="json")) + "\n"
        for item in sorted(items, key=lambda item: item.id)
    )


def slice_hash(items: Iterable[GoldItem]) -> str:
    """The SHA-256 of a slice's canonical JSONL text."""
    return hashlib.sha256(slice_text(items).encode("utf-8")).hexdigest()


def make_lock(split: Split) -> dict[str, Any]:
    """Describe a split for committing.

    Args:
        split: The split.

    Returns:
        A JSON-ready mapping: the seed, the tuning fraction, the slice sizes, the sorted ids
        of every slice, the frozen slice's name and its content hash.
    """
    return {
        "seed": split.seed,
        "tuning_fraction": split.tuning_fraction,
        "counts": {name: len(items) for name, items in sorted(split.slices.items())},
        "ids": {name: sorted(item.id for item in items) for name, items in split.slices.items()},
        "frozen_slice": split.frozen_slice,
        "frozen_sha256": slice_hash(split.slices[split.frozen_slice]),
    }


def write_lock(split: Split, path: Path) -> dict[str, Any]:
    """Write ``split.lock.json``.

    Args:
        split: The split.
        path: The lock file to write; parent directories are created.

    Returns:
        The lock that was written.
    """
    lock = make_lock(split)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((json.dumps(lock, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return lock


def read_lock(path: Path) -> dict[str, Any]:
    """Read a lock file written by ``write_lock``."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_lock(items: Iterable[GoldItem], lock: dict[str, Any]) -> None:
    """Check that the frozen slice still matches the lock.

    Args:
        items: The current items (at least the frozen slice's).
        lock: A lock from ``make_lock`` or ``read_lock``.

    Raises:
        SplitLockError: If a frozen item is missing or the recomputed hash differs, meaning
            a frozen item was added, removed or changed.
    """
    name = lock["frozen_slice"]
    wanted = set(lock["ids"][name])
    current = {item.id: item for item in items if item.id in wanted}
    missing = sorted(wanted - current.keys())
    if missing:
        raise SplitLockError(f"{len(missing)} frozen {name} items are missing, e.g. {missing[0]}")
    if slice_hash(current.values()) != lock["frozen_sha256"]:
        raise SplitLockError(f"the {name} slice no longer matches its lock: an item changed")


def write_slices(split: Split, directory: Path) -> dict[str, Path]:
    """Write each slice as ``<slice>.jsonl`` in a directory.

    Args:
        split: The split.
        directory: Where to write.

    Returns:
        The path written for each slice.
    """
    return {
        name: write_jsonl(Path(directory) / f"{name}.jsonl", items)
        for name, items in split.slices.items()
    }


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True, check=False
    )


def require_frozen_prereg(slice_name: str, prereg_dir: Path, *, repo_root: Path) -> Path:
    """Refuse a generation run on a slice whose pre-registration is not committed.

    ``test`` needs ``v1.md`` and ``pilot`` needs ``pilot.md``; ``tuning`` needs nothing.
    A file is frozen when git tracks it and it matches ``HEAD`` exactly, so a staged but
    uncommitted or later-edited file is not.

    Args:
        slice_name: ``tuning``, ``test`` or ``pilot``.
        prereg_dir: The directory holding the pre-registration files.
        repo_root: The git repository's root, where the git commands run.

    Returns:
        The frozen file's path, or the ``prereg_dir`` itself for ``tuning``.

    Raises:
        PreregNotFrozen: If the file is missing, untracked or has uncommitted changes.
        ValueError: If the slice name is not recognised.
    """
    if slice_name == TUNING:
        return Path(prereg_dir)
    if slice_name not in PREREG_FILES:
        raise ValueError(f"unknown slice {slice_name!r}")
    path = Path(prereg_dir) / PREREG_FILES[slice_name]
    problem: str | None = None
    if not path.exists():
        problem = "does not exist"
    elif _git(repo_root, "ls-files", "--error-unmatch", str(path)).returncode != 0:
        problem = "is not tracked by git"
    elif _git(repo_root, "diff", "--quiet", "HEAD", "--", str(path)).returncode != 0:
        problem = "has uncommitted changes"
    if problem is not None:
        raise PreregNotFrozen(
            f"generation on the {slice_name!r} slice needs {path.name} frozen, but {path} "
            f"{problem}. Commit it first: the commit is the timestamp."
        )
    return path
