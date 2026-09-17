"""Glossary browsing, filtering, and search."""

import pytest

from tests.factories import make_glossary_entry, make_ingested_repo, make_repo, make_user
from tests.helpers import authenticate, random_uuid

pytestmark = pytest.mark.integration


def browse_url(repo) -> str:
    return f"/api/v1/repository/{repo.id}/glossary"


def search_url(repo) -> str:
    return f"/api/v1/repository/{repo.id}/glossary/search"


@pytest.fixture
async def glossary(client, db_session):
    """
    A signed-in user with four terms.

    Names are chosen so alphabetical order, substring matching, and case folding each
    have something to bite on: "Cache" and "CacheEviction" share a prefix, "RetryPolicy"
    only matches if folding works.
    """
    user = await make_user(db_session)
    repo, _ = await make_ingested_repo(db_session, user)
    await make_glossary_entry(
        db_session, repo, name="Cache", definition="Stores hot values.", file_path="src/a.py"
    )
    await make_glossary_entry(
        db_session,
        repo,
        name="CacheEviction",
        definition="Drops entries under pressure.",
        file_path="src/a.py",
    )
    await make_glossary_entry(
        db_session,
        repo,
        name="RetryPolicy",
        definition="Controls how a failed fetch is retried.",
        file_path="src/b.py",
    )
    await make_glossary_entry(
        db_session, repo, name="Zebra", definition="Nothing references this.", file_path="src/c.py"
    )
    await authenticate(client, user)
    return user, repo


class TestBrowse:
    async def test_returns_entries_alphabetically(self, client, glossary):
        _, repo = glossary

        body = (await client.get(browse_url(repo))).json()

        assert [e["name"] for e in body["entries"]] == [
            "Cache",
            "CacheEviction",
            "RetryPolicy",
            "Zebra",
        ]

    async def test_reports_the_total_independently_of_the_page(self, client, glossary):
        """`total` counts the filtered set, not the page -- it drives the pager."""
        _, repo = glossary

        body = (await client.get(f"{browse_url(repo)}?page_size=2")).json()

        assert body["total"] == 4
        assert len(body["entries"]) == 2

    async def test_walks_pages_without_repeating(self, client, glossary):
        _, repo = glossary

        first = (await client.get(f"{browse_url(repo)}?page_size=2&page=1")).json()
        second = (await client.get(f"{browse_url(repo)}?page_size=2&page=2")).json()

        names = [e["name"] for e in first["entries"]] + [e["name"] for e in second["entries"]]
        assert len(set(names)) == 4

    async def test_echoes_the_requested_page(self, client, glossary):
        _, repo = glossary

        body = (await client.get(f"{browse_url(repo)}?page=2&page_size=2")).json()

        assert body["page"] == 2
        assert body["page_size"] == 2

    async def test_filters_by_exact_file_path(self, client, glossary):
        _, repo = glossary

        body = (await client.get(f"{browse_url(repo)}?file_path=src/a.py")).json()

        assert {e["name"] for e in body["entries"]} == {"Cache", "CacheEviction"}

    async def test_an_unknown_file_path_yields_nothing(self, client, glossary):
        """Exact match, not a prefix -- an unmatched filter must not fall back to all rows."""
        _, repo = glossary

        body = (await client.get(f"{browse_url(repo)}?file_path=src/a")).json()

        assert body["entries"] == []
        assert body["total"] == 0

    async def test_is_empty_for_a_repo_with_no_glossary(self, client, db_session):
        user = await make_user(db_session)
        repo = await make_repo(db_session, user)
        await authenticate(client, user)

        body = (await client.get(browse_url(repo))).json()

        assert body["entries"] == []
        assert body["total"] == 0

    @pytest.mark.parametrize(
        ("param", "value"),
        [("page", "0"), ("page", "-1"), ("page_size", "0"), ("page_size", "101")],
        ids=["page-zero", "page-negative", "size-zero", "size-too-large"],
    )
    async def test_rejects_out_of_range_pagination(self, client, glossary, param, value):
        _, repo = glossary

        assert (await client.get(f"{browse_url(repo)}?{param}={value}")).status_code == 422


class TestSearch:
    async def test_matches_names_case_insensitively(self, client, glossary):
        """`ilike` must fold both directions, not just lowercase the query."""
        _, repo = glossary

        body = (await client.get(f"{search_url(repo)}?q=cache")).json()

        assert {e["name"] for e in body["entries"]} == {"Cache", "CacheEviction"}

    async def test_matches_definitions_too(self, client, glossary):
        _, repo = glossary

        body = (await client.get(f"{search_url(repo)}?q=pressure")).json()

        assert {e["name"] for e in body["entries"]} == {"CacheEviction"}

    async def test_matches_a_substring_anywhere_in_the_name(self, client, glossary):
        _, repo = glossary

        body = (await client.get(f"{search_url(repo)}?q=viction")).json()

        assert {e["name"] for e in body["entries"]} == {"CacheEviction"}

    async def test_reports_total_for_the_search_not_the_repo(self, client, glossary):
        _, repo = glossary

        body = (await client.get(f"{search_url(repo)}?q=cache")).json()

        assert body["total"] == 2

    async def test_no_match_returns_an_empty_page(self, client, glossary):
        _, repo = glossary

        body = (await client.get(f"{search_url(repo)}?q=definitely-not-a-term")).json()

        assert body["entries"] == []
        assert body["total"] == 0

    async def test_requires_a_query(self, client, glossary):
        _, repo = glossary

        assert (await client.get(search_url(repo))).status_code == 422

    async def test_rejects_an_empty_query(self, client, glossary):
        """min_length=1 -- an empty q would otherwise match every row."""
        _, repo = glossary

        assert (await client.get(f"{search_url(repo)}?q=")).status_code == 422

    async def test_a_percent_sign_is_literal(self, client, glossary):
        """
        `%` is a LIKE wildcard, so an unescaped query of `%` becomes the pattern `%%%`
        and matches the whole glossary. The query is a bound parameter -- this is not
        injection -- but the user's text still needs escaping before it is used as a
        pattern.
        """
        _, repo = glossary

        body = (await client.get(f"{search_url(repo)}?q=%")).json()

        assert body["total"] == 0

    async def test_an_underscore_is_literal(self, client, glossary):
        """
        The sharper half of the same hazard: `_` matches any single character, so `Z_bra`
        matches "Zebra". Identifiers are exactly where this bites -- snake_case names and
        dunder methods are full of underscores that a user means literally.
        """
        _, repo = glossary

        body = (await client.get(f"{search_url(repo)}?q=Z_bra")).json()

        assert {e["name"] for e in body["entries"]} == set()

    async def test_a_dunder_name_matches_only_itself(self, client, db_session, glossary):
        _, repo = glossary
        await make_glossary_entry(db_session, repo, name="__init__")
        await make_glossary_entry(db_session, repo, name="reinitialize")

        body = (await client.get(f"{search_url(repo)}?q=__init__")).json()

        assert {e["name"] for e in body["entries"]} == {"__init__"}


class TestGuards:
    async def test_browsing_another_users_repository_is_not_found(self, client, db_session):
        mine = await make_user(db_session)
        theirs = await make_user(db_session)
        their_repo, _ = await make_ingested_repo(db_session, theirs)
        await make_glossary_entry(db_session, their_repo, name="Secret")
        await authenticate(client, mine)

        assert (await client.get(browse_url(their_repo))).status_code == 404

    async def test_searching_another_users_repository_is_not_found(self, client, db_session):
        mine = await make_user(db_session)
        theirs = await make_user(db_session)
        their_repo, _ = await make_ingested_repo(db_session, theirs)
        await make_glossary_entry(db_session, their_repo, name="Secret")
        await authenticate(client, mine)

        assert (await client.get(f"{search_url(their_repo)}?q=secret")).status_code == 404

    async def test_an_unknown_id_is_not_found(self, client, db_session):
        await authenticate(client, await make_user(db_session))

        assert (await client.get(f"/api/v1/repository/{random_uuid()}/glossary")).status_code == 404

    async def test_a_malformed_id_is_a_validation_error(self, client, db_session):
        await authenticate(client, await make_user(db_session))

        assert (await client.get("/api/v1/repository/not-a-uuid/glossary")).status_code == 422

    @pytest.mark.parametrize("path", ["glossary", "glossary/search?q=a"])
    async def test_requires_authentication(self, client, db_session, path):
        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)
        client.cookies.clear()

        assert (await client.get(f"/api/v1/repository/{repo.id}/{path}")).status_code == 401
