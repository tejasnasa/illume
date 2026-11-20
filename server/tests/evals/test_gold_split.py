"""The frozen split, its lock and the pre-registration guard."""

import subprocess
from collections import Counter
from pathlib import Path

import pytest

from evals.gold.schema import make_item
from evals.gold.split import (
    PreregNotFrozen,
    SplitLockError,
    make_lock,
    make_pilot,
    make_split,
    read_lock,
    require_frozen_prereg,
    verify_lock,
    write_lock,
    write_slices,
)

pytestmark = pytest.mark.unit

BASE = "d" * 40


def _items(n_changeset_prs=60, n_structural=40, repos=("alpha", "beta")):
    items = []
    for repo in repos:
        for pr in range(n_changeset_prs):
            for template in ("changeset.blind", "changeset.anchor"):
                extra = {"anchor_file": "src/entry.py"} if template.endswith("anchor") else {}
                items.append(
                    make_item(
                        repo=repo,
                        base_commit=BASE,
                        family="changeset",
                        template=template,
                        question_seed=f"pr {pr} {template}",
                        gold_files=("src/a.py", "src/b.py"),
                        cluster=f"{repo}#{pr}",
                        merges_since_base=pr,
                        **extra,
                    )
                )
        for n in range(n_structural):
            items.append(
                make_item(
                    repo=repo,
                    base_commit=BASE,
                    family="structural",
                    template="structural.importers",
                    question_seed=f"importers {n}",
                    gold_files=(f"src/f{n}.py",),
                    circular_with=("graph",),
                )
            )
    return items


def test_the_split_is_deterministic_and_independent_of_input_order():
    items = _items()
    one = make_split(items, seed=3)
    two = make_split(list(reversed(items)), seed=3)
    assert [i.id for i in one.test] == [i.id for i in two.test]
    assert [i.id for i in one.tuning] == [i.id for i in two.tuning]
    other = make_split(items, seed=4)
    assert [i.id for i in other.test] != [i.id for i in one.test]


def test_no_id_is_in_both_slices_and_every_item_is_assigned():
    items = _items()
    split = make_split(items, seed=1)
    tuning = {i.id for i in split.tuning}
    test = {i.id for i in split.test}
    assert not tuning & test
    assert tuning | test == {i.id for i in items}


def test_clusters_are_never_split_across_slices():
    split = make_split(_items(), seed=1)
    home: dict[str, set[str]] = {}
    for name, members in split.slices.items():
        for item in members:
            home.setdefault(item.cluster or item.id, set()).add(name)
    assert all(len(names) == 1 for names in home.values())


def test_stratification_proportions_roughly_hold():
    split = make_split(_items(), seed=1)
    tuning = Counter((i.repo, i.family) for i in split.tuning)
    total = Counter((i.repo, i.family) for i in [*split.tuning, *split.test])
    for key, count in total.items():
        assert abs(tuning[key] / count - 0.2) <= 0.05, key


def test_the_lock_hash_changes_when_a_test_item_changes_and_verify_raises():
    items = _items()
    split = make_split(items, seed=1)
    lock = make_lock(split)
    verify_lock(items, lock)
    victim = split.test[0]
    changed = [
        i.model_copy(update={"question": "edited"}) if i.id == victim.id else i for i in items
    ]
    with pytest.raises(SplitLockError, match="changed"):
        verify_lock(changed, lock)
    assert make_lock(make_split(changed, seed=1))["frozen_sha256"] != lock["frozen_sha256"]


def test_a_tuning_edit_does_not_trip_the_lock():
    items = _items()
    split = make_split(items, seed=1)
    lock = make_lock(split)
    victim = split.tuning[0]
    changed = [
        i.model_copy(update={"question": "edited"}) if i.id == victim.id else i for i in items
    ]
    verify_lock(changed, lock)


def test_a_missing_test_item_raises():
    items = _items()
    split = make_split(items, seed=1)
    lock = make_lock(split)
    gone = split.test[0].id
    with pytest.raises(SplitLockError, match="missing"):
        verify_lock([i for i in items if i.id != gone], lock)


def test_the_lock_file_round_trips_and_slices_are_written(tmp_path):
    split = make_split(_items(), seed=1)
    lock = write_lock(split, tmp_path / "split.lock.json")
    assert read_lock(tmp_path / "split.lock.json") == lock
    assert lock["ids"]["test"] == sorted(lock["ids"]["test"])
    assert lock["counts"] == {"test": len(split.test), "tuning": len(split.tuning)}
    paths = write_slices(split, tmp_path)
    assert set(paths) == {"tuning", "test"}
    assert (tmp_path / "test.jsonl").exists()


def test_pilot_mode_puts_everything_in_one_slice():
    items = _items()
    pilot = make_pilot(items)
    assert set(pilot.slices) == {"pilot"}
    assert {i.id for i in pilot.slices["pilot"]} == {i.id for i in items}
    lock = make_lock(pilot)
    assert lock["frozen_slice"] == "pilot"
    assert lock["counts"] == {"pilot": len(items)}
    verify_lock(items, lock)


# --- the pre-registration guard --------------------------------------------------------


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "scratch"
    (root / "prereg").mkdir(parents=True)
    _git(root, "init", "-q")
    (root / "keep").write_text("x")
    _git(root, "add", "keep")
    _git(root, "commit", "-q", "-m", "init")
    return root


@pytest.mark.parametrize(("slice_name", "name"), [("test", "v1.md"), ("pilot", "pilot.md")])
def test_the_guard_walks_missing_untracked_committed_and_modified(repo, slice_name, name):
    prereg = repo / "prereg"
    with pytest.raises(PreregNotFrozen, match="does not exist"):
        require_frozen_prereg(slice_name, prereg, repo_root=repo)

    (prereg / name).write_text("draft")
    with pytest.raises(PreregNotFrozen, match="not tracked"):
        require_frozen_prereg(slice_name, prereg, repo_root=repo)

    _git(repo, "add", f"prereg/{name}")
    with pytest.raises(PreregNotFrozen, match="uncommitted"):
        require_frozen_prereg(slice_name, prereg, repo_root=repo)

    _git(repo, "commit", "-q", "-m", "freeze")
    assert require_frozen_prereg(slice_name, prereg, repo_root=repo) == prereg / name

    (prereg / name).write_text("edited after freezing")
    with pytest.raises(PreregNotFrozen, match="uncommitted"):
        require_frozen_prereg(slice_name, prereg, repo_root=repo)


def test_the_test_slice_needs_v1_not_the_pilot_file(repo):
    prereg = repo / "prereg"
    (prereg / "pilot.md").write_text("pilot")
    _git(repo, "add", "prereg/pilot.md")
    _git(repo, "commit", "-q", "-m", "freeze pilot")
    require_frozen_prereg("pilot", prereg, repo_root=repo)
    with pytest.raises(PreregNotFrozen, match="v1.md"):
        require_frozen_prereg("test", prereg, repo_root=repo)


def test_the_tuning_slice_is_always_allowed(repo):
    require_frozen_prereg("tuning", repo / "prereg", repo_root=repo)


def test_an_unknown_slice_is_rejected(repo):
    with pytest.raises(ValueError):
        require_frozen_prereg("final", repo / "prereg", repo_root=repo)
