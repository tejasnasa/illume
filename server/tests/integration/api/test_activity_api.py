"""Recent activity: merged pull requests and commits, newest first."""

from datetime import UTC, datetime

import pytest

from app.models import Commit, PullRequest
from tests.factories import make_ingested_repo, make_user
from tests.helpers import authenticate

pytestmark = pytest.mark.integration


def activity_url(repo, limit: int | None = None) -> str:
    suffix = f"?limit={limit}" if limit is not None else ""
    return f"/api/v1/repository/{repo.id}/activity{suffix}"


def commit(repo, hash_: str, message: str, day: int) -> Commit:
    return Commit(
        repository_id=repo.id,
        hash=hash_,
        author_name="Ada",
        author_email="ada@example.com",
        message=message,
        files_changed=2,
        authored_at=datetime(2026, 3, day, tzinfo=UTC),
    )


@pytest.fixture
async def active(client, db_session):
    user = await make_user(db_session)
    repo, _ = await make_ingested_repo(db_session, user)
    db_session.add_all(
        [
            commit(repo, "a" * 40, "fix: handle empty input\n\nLonger body.", 1),
            commit(repo, "b" * 40, "Merge pull request #7 from ada/feature", 3),
            commit(repo, "c" * 40, "feat: add the parser", 4),
            PullRequest(
                repository_id=repo.id,
                number=7,
                title="Add a feature",
                author="Ada",
                files_changed=5,
                merged_at=datetime(2026, 3, 3, tzinfo=UTC),
            ),
            PullRequest(
                repository_id=repo.id,
                number=8,
                title="Still open",
                author="Bob",
                files_changed=1,
            ),
        ]
    )
    await db_session.commit()
    await authenticate(client, user)
    return repo


async def test_lists_merged_pull_requests_and_commits_newest_first(client, active):
    items = (await client.get(activity_url(active))).json()["items"]

    assert [(item["kind"], item["title"]) for item in items] == [
        ("commit", "feat: add the parser"),
        ("pull_request", "Add a feature"),
        ("commit", "fix: handle empty input"),
    ]
    assert items[1]["number"] == 7
    assert items[0]["hash"] == "c" * 40


async def test_limit_caps_the_list(client, active):
    items = (await client.get(activity_url(active, limit=2))).json()["items"]

    assert len(items) == 2


async def test_an_empty_history_is_an_empty_list(client, db_session):
    user = await make_user(db_session)
    repo, _ = await make_ingested_repo(db_session, user)
    await authenticate(client, user)

    assert (await client.get(activity_url(repo))).json() == {"items": []}


async def test_another_users_repository_is_not_found(client, db_session, active):
    await authenticate(client, await make_user(db_session))

    assert (await client.get(activity_url(active))).status_code == 404
