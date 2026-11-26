"""File detail: a file's symbols in line order and the commits that touched it."""

from datetime import UTC, datetime

import pytest

from app.models import Commit
from tests.factories import make_file, make_ingested_repo, make_symbol, make_user
from tests.helpers import authenticate

pytestmark = pytest.mark.integration

PATH = "src/parser.py"


def detail_url(repo, path: str = PATH, commits: int | None = None) -> str:
    suffix = f"&commits={commits}" if commits is not None else ""
    return f"/api/v1/repository/{repo.id}/file?path={path}{suffix}"


def commit(repo, hash_: str, message: str, day: int, files: list[str]) -> Commit:
    return Commit(
        repository_id=repo.id,
        hash=hash_,
        author_name="Ada",
        author_email="ada@example.com",
        message=message,
        files_changed=len(files),
        changed_files_list=files,
        authored_at=datetime(2026, 3, day, tzinfo=UTC),
    )


@pytest.fixture
async def repo(client, db_session):
    user = await make_user(db_session)
    repo, _ = await make_ingested_repo(db_session, user)
    file = await make_file(db_session, repo, path=PATH)
    await make_symbol(db_session, file, name="tokenize", start_line=40)
    await make_symbol(db_session, file, name="Parser", kind="class", start_line=5)
    await make_symbol(db_session, file, name="os", kind="import", start_line=1)
    db_session.add_all(
        [
            commit(repo, "a" * 40, "feat: add the parser\n\nBody.", 1, [PATH]),
            commit(repo, "b" * 40, "fix: unrelated", 2, ["src/other.py"]),
            commit(repo, "c" * 40, "fix: tokenize tabs", 3, ["README.md", PATH]),
            # A path that merely contains this one must not match.
            commit(repo, "d" * 40, "chore: nested", 4, [f"vendor/{PATH}"]),
        ]
    )
    await db_session.commit()
    await authenticate(client, user)
    return repo


async def test_lists_definitions_in_line_order_without_imports(client, repo):
    body = (await client.get(detail_url(repo))).json()

    assert [(s["kind"], s["name"], s["start_line"]) for s in body["symbols"]] == [
        ("class", "Parser", 5),
        ("function", "tokenize", 40),
    ]


async def test_lists_only_commits_that_touched_the_exact_path_newest_first(client, repo):
    body = (await client.get(detail_url(repo))).json()

    assert [(c["hash"][0], c["title"]) for c in body["commits"]] == [
        ("c", "fix: tokenize tabs"),
        ("a", "feat: add the parser"),
    ]
    assert body["commits"][0]["author"] == "Ada"


async def test_commits_parameter_caps_the_history(client, repo):
    body = (await client.get(detail_url(repo, commits=1))).json()

    assert len(body["commits"]) == 1


async def test_an_unknown_path_is_404(client, repo):
    response = await client.get(detail_url(repo, path="src/missing.py"))

    assert response.status_code == 404
