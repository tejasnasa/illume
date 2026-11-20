"""Tests for the on-disk GitHub cache."""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from evals.mining.github_cache import CachedPR, CachedPRFile, load_prs, repo_dir, save_pr

pytestmark = pytest.mark.unit

SLUG = "owner/repo"


def _pr(number: int, **overrides) -> CachedPR:
    fields: dict[str, Any] = {
        "number": number,
        "title": f"Title {number}",
        "body": "Body with unicode é and\nnewlines",
        "author": "ada",
        "merged_at": datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC),
        "merge_commit_sha": "a" * 40,
        "files": (
            CachedPRFile("src/a.py", "modified", None, 4, 1),
            CachedPRFile("src/b.py", "renamed", "src/old.py", 0, 0),
        ),
        "labels": ("bug", "core"),
        "user_type": "User",
    }
    fields.update(overrides)
    return CachedPR(**fields)


def test_a_pull_request_round_trips_exactly(tmp_path):
    original = _pr(7)
    save_pr(tmp_path, SLUG, original)
    assert load_prs(tmp_path, SLUG) == [original]


def test_files_that_were_not_fetched_stay_none(tmp_path):
    original = _pr(8, files=None, labels=())
    save_pr(tmp_path, SLUG, original)
    (loaded,) = load_prs(tmp_path, SLUG)
    assert loaded.files is None
    assert loaded == original


def test_a_non_utc_offset_survives(tmp_path):
    zone = timezone(timedelta(hours=5, minutes=30))
    original = _pr(9, merged_at=datetime(2026, 1, 1, 12, tzinfo=zone))
    save_pr(tmp_path, SLUG, original)
    (loaded,) = load_prs(tmp_path, SLUG)
    assert loaded.merged_at == original.merged_at
    assert loaded.merged_at.utcoffset() == timedelta(hours=5, minutes=30)


def test_prs_come_back_sorted_by_number(tmp_path):
    for number in (30, 4, 100, 12):
        save_pr(tmp_path, SLUG, _pr(number))
    assert [pr.number for pr in load_prs(tmp_path, SLUG)] == [4, 12, 30, 100]


def test_the_layout_is_one_file_per_pr_under_the_owner_repo_directory(tmp_path):
    written = save_pr(tmp_path, SLUG, _pr(12))
    assert written == tmp_path / "owner__repo" / "prs" / "12.json"
    assert repo_dir(tmp_path, SLUG) == tmp_path / "owner__repo"


def test_saving_twice_is_byte_identical_and_replaces(tmp_path):
    path = save_pr(tmp_path, SLUG, _pr(5))
    first = path.read_bytes()
    save_pr(tmp_path, SLUG, _pr(5))
    assert path.read_bytes() == first
    save_pr(tmp_path, SLUG, _pr(5, title="Changed"))
    assert [pr.title for pr in load_prs(tmp_path, SLUG)] == ["Changed"]


def test_key_order_is_stable(tmp_path):
    import json

    path = save_pr(tmp_path, SLUG, _pr(5))
    assert list(json.loads(path.read_text(encoding="utf-8"))) == [
        "number",
        "title",
        "body",
        "author",
        "merged_at",
        "merge_commit_sha",
        "files",
        "labels",
        "user_type",
    ]


def test_an_uncached_repository_has_no_prs(tmp_path):
    assert load_prs(tmp_path, "nobody/nothing") == []
