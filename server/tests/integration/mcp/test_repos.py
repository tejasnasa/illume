"""``resolve_repo``: one reference format per case, scoped to the caller."""

from __future__ import annotations

import uuid

import pytest

from app.mcp.repos import McpRepoError, resolve_repo
from tests.factories import make_repo, make_user

pytestmark = pytest.mark.integration


@pytest.fixture
async def user(db_session):
    return await make_user(db_session)


@pytest.fixture
async def repo(db_session, user):
    return await make_repo(
        db_session, user, name="Widget", github_url="https://github.com/Acme/Widget"
    )


class TestResolving:
    async def test_by_repo_number(self, db_session, user, repo):
        assert (await resolve_repo(db_session, user.id, str(repo.repo_number))).id == repo.id

    async def test_by_uuid(self, db_session, user, repo):
        assert (await resolve_repo(db_session, user.id, str(repo.id))).id == repo.id

    @pytest.mark.parametrize("ref", ["acme/widget", "Acme/Widget", "ACME/WIDGET", " acme/widget "])
    async def test_by_owner_and_name_ignoring_case(self, db_session, user, repo, ref):
        assert (await resolve_repo(db_session, user.id, ref)).id == repo.id

    @pytest.mark.parametrize("suffix", [".git", "/", ".git/"])
    async def test_by_owner_and_name_with_a_suffix_on_the_reference(
        self, db_session, user, repo, suffix
    ):
        assert (await resolve_repo(db_session, user.id, f"acme/widget{suffix}")).id == repo.id

    async def test_a_stored_url_with_git_suffix_matches(self, db_session, user):
        stored = await make_repo(
            db_session, user, name="gadget", github_url="https://github.com/acme/gadget.git"
        )

        assert (await resolve_repo(db_session, user.id, "acme/gadget")).id == stored.id

    async def test_a_name_that_only_ends_the_same_does_not_match(self, db_session, user, repo):
        assert (await _message(db_session, user, "acme/idget")).startswith("No repository matches")

    async def test_underscores_are_literal_not_wildcards(self, db_session, user):
        await make_repo(db_session, user, name="a_b", github_url="https://github.com/acme/a_b")

        assert "No repository matches" in await _message(db_session, user, "acme/axb")


class TestNotFound:
    async def test_garbage_is_not_found(self, db_session, user, repo):
        for ref in ["", "   ", "???", "not a repo", "a/b/c", "99999999999999"]:
            assert "No repository matches" in await _message(db_session, user, ref)

    async def test_another_users_repository_reads_the_same_as_a_missing_one(
        self, db_session, user, repo
    ):
        other = await make_user(db_session)
        theirs = await make_repo(
            db_session, other, name="secret", github_url="https://github.com/zed/secret"
        )

        missing_number = str(theirs.repo_number + 1000)
        missing_uuid = str(uuid.uuid4())
        pairs = [
            (str(theirs.repo_number), missing_number),
            (str(theirs.id), missing_uuid),
            ("zed/secret", "nobody/nothing"),
        ]
        for real, missing in pairs:
            message = await _message(db_session, user, real)
            assert message == (await _message(db_session, user, missing)).replace(missing, real)
            assert message.startswith("No repository matches")

    async def test_an_unknown_uuid_and_number_are_not_found(self, db_session, user):
        assert "No repository matches" in await _message(db_session, user, str(uuid.uuid4()))
        assert "No repository matches" in await _message(db_session, user, "424242")


class TestAmbiguity:
    async def test_two_repositories_with_the_same_owner_and_name_list_their_numbers(
        self, db_session, user
    ):
        first = await make_repo(db_session, user, name="dup", github_url="https://github.com/o/dup")
        second = await make_repo(
            db_session, user, name="dup", github_url="https://github.com/o/dup.git"
        )

        message = await _message(db_session, user, "o/dup")

        assert "matches 2 repositories" in message
        assert str(first.repo_number) in message and str(second.repo_number) in message

    async def test_the_number_disambiguates(self, db_session, user):
        first = await make_repo(db_session, user, name="dup", github_url="https://github.com/o/dup")
        await make_repo(db_session, user, name="dup", github_url="https://github.com/o/dup")

        assert (await resolve_repo(db_session, user.id, str(first.repo_number))).id == first.id

    async def test_another_users_duplicate_does_not_make_it_ambiguous(self, db_session, user):
        mine = await make_repo(db_session, user, name="dup", github_url="https://github.com/o/dup")
        other = await make_user(db_session)
        await make_repo(db_session, other, name="dup", github_url="https://github.com/o/dup")

        assert (await resolve_repo(db_session, user.id, "o/dup")).id == mine.id


class TestUsability:
    async def test_a_repository_that_is_still_ingesting_says_so(self, db_session, user):
        repo = await make_repo(
            db_session, user, name="busy", github_url="https://github.com/o/busy", status="parsing"
        )

        message = await _message(db_session, user, str(repo.repo_number))

        assert "still ingesting" in message
        assert "status=parsing" in message

    async def test_a_failed_repository_says_so(self, db_session, user):
        repo = await make_repo(
            db_session,
            user,
            name="broken",
            github_url="https://github.com/o/broken",
            status="failed",
        )

        message = await _message(db_session, user, "o/broken")

        assert "failed to ingest" in message
        assert str(repo.repo_number) in message


async def _message(db, user, ref: str) -> str:
    with pytest.raises(McpRepoError) as raised:
        await resolve_repo(db, user.id, ref)
    return raised.value.message
