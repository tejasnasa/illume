"""Onboarding guide: reading order, critical files, and the architecture brief."""

import pytest

from tests.factories import make_guide, make_ingested_repo, make_user
from tests.helpers import authenticate, random_uuid

pytestmark = pytest.mark.integration


def guide_url(repo) -> str:
    return f"/api/v1/repository/{repo.id}/guide"


READING_ORDER = [
    # Deliberately out of order, so the endpoint's sort is what produces the sequence.
    {"position": 3, "path": "src/c.py", "annotation": "Read last.", "fan_in": 0},
    {"position": 1, "path": "src/a.py", "annotation": "Start here.", "fan_in": 7},
    {"position": 2, "path": "src/b.py", "annotation": "Then this.", "fan_in": 3},
]

CRITICAL_FILES = [
    {
        "path": "src/safe.py",
        "criticality": "safe",
        "reasons": [],
        "fan_in": 1,
        "change_frequency": 0.5,
        "has_tests": True,
    },
    {
        "path": "src/hot.py",
        "criticality": "critical",
        "reasons": ["high fan-in"],
        "fan_in": 42,
        "change_frequency": 9.5,
        "has_tests": False,
    },
    {
        "path": "src/warm.py",
        "criticality": "caution",
        "reasons": ["no tests"],
        "fan_in": 12,
        "change_frequency": 2.0,
        "has_tests": False,
    },
]

BRIEF = {
    "entry_points": ["src/main.py"],
    "directory_summary": {"src": "Everything."},
    "external_integrations": ["OpenAI"],
    "data_flow": [{"from": "src/a.py", "to": "src/b.py", "step": 1}],
    "module_edges": [{"source": "src/a.py", "target": "src/b.py"}],
    "key_modules": [{"path": "src/a.py", "summary": "Core."}],
    "ownership_summary": [{"owner": "Ada", "files": 3}],
}


@pytest.fixture
async def guided(client, db_session):
    """A signed-in user whose repository has a fully populated guide."""
    user = await make_user(db_session)
    repo, _ = await make_ingested_repo(db_session, user)
    await make_guide(
        db_session,
        repo,
        reading_order=READING_ORDER,
        critical_files=CRITICAL_FILES,
        architecture_brief=BRIEF,
    )
    await authenticate(client, user)
    return user, repo


class TestReadingOrder:
    async def test_orders_by_position_not_storage_order(self, client, guided):
        _, repo = guided

        body = (await client.get(guide_url(repo))).json()

        assert [item["position"] for item in body["reading_order"]] == [1, 2, 3]

    async def test_renames_the_stored_path_key(self, client, guided):
        """Storage says `path`; the response contract says `file_path`."""
        _, repo = guided

        first = (await client.get(guide_url(repo))).json()["reading_order"][0]

        assert first["file_path"] == "src/a.py"
        assert first["annotation"] == "Start here."
        assert first["fan_in"] == 7

    async def test_does_not_leak_the_tier_field(self, client, guided):
        """
        `reading_order` rows carry a `tier` in storage that the endpoint drops. The
        client re-joins the guide onto graph nodes by path, so tier never reaches it.
        """
        _, repo = guided

        first = (await client.get(guide_url(repo))).json()["reading_order"][0]

        assert "tier" not in first

    async def test_absent_reading_order_is_an_empty_list(self, client, db_session):
        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)
        await make_guide(db_session, repo, reading_order=None)
        await authenticate(client, user)

        body = (await client.get(guide_url(repo))).json()

        assert body["reading_order"] == []

    async def test_a_malformed_entry_is_skipped_not_fatal(self, client, db_session):
        """A non-dict in the JSONB blob must not 500 the whole guide."""
        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)
        await make_guide(db_session, repo, reading_order=["not-a-dict", READING_ORDER[1]])
        await authenticate(client, user)

        body = (await client.get(guide_url(repo))).json()

        assert len(body["reading_order"]) == 1


class TestCriticalFiles:
    async def test_sorts_critical_first(self, client, guided):
        _, repo = guided

        body = (await client.get(guide_url(repo))).json()

        assert [f["criticality"] for f in body["critical_files"]] == [
            "critical",
            "caution",
            "safe",
        ]

    async def test_carries_the_reasons_and_metrics(self, client, guided):
        _, repo = guided

        first = (await client.get(guide_url(repo))).json()["critical_files"][0]

        assert first["file_path"] == "src/hot.py"
        assert first["reasons"] == ["high fan-in"]
        assert first["fan_in"] == 42
        assert first["has_tests"] is False

    async def test_an_unknown_criticality_sorts_last(self, client, db_session):
        """Anything outside the three known labels must not sort above `critical`."""
        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)
        await make_guide(
            db_session,
            repo,
            critical_files=[
                {
                    "path": "x.py",
                    "criticality": "unrecognised",
                    "reasons": [],
                    "fan_in": 1,
                    "change_frequency": None,
                    "has_tests": False,
                },
                *CRITICAL_FILES,
            ],
        )
        await authenticate(client, user)

        body = (await client.get(guide_url(repo))).json()

        assert body["critical_files"][-1]["criticality"] == "unrecognised"


class TestArchitectureBrief:
    async def test_returns_every_section(self, client, guided):
        _, repo = guided

        brief = (await client.get(guide_url(repo))).json()["architecture_brief"]

        assert brief["entry_points"] == ["src/main.py"]
        assert brief["external_integrations"] == ["OpenAI"]
        assert brief["key_modules"] == [{"path": "src/a.py", "summary": "Core."}]

    async def test_aliases_the_data_flow_from_key(self, client, guided):
        """
        `from` is a Python keyword, so the model aliases it to `from_`. Serialization
        must emit the alias, not the attribute name, or the client's type breaks.
        """
        _, repo = guided

        step = (await client.get(guide_url(repo))).json()["architecture_brief"]["data_flow"][0]

        assert step["from"] == "src/a.py"
        assert step["to"] == "src/b.py"

    async def test_is_null_when_never_generated(self, client, db_session):
        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)
        await make_guide(db_session, repo, architecture_brief=None)
        await authenticate(client, user)

        assert (await client.get(guide_url(repo))).json()["architecture_brief"] is None


class TestPdfReady:
    async def test_is_false_without_a_pdf_path(self, client, guided):
        _, repo = guided

        assert (await client.get(guide_url(repo))).json()["pdf_ready"] is False

    async def test_is_false_when_the_path_does_not_exist(self, client, db_session):
        """The flag reflects the file on disk, not merely that a path was recorded."""
        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)
        await make_guide(db_session, repo, pdf_path="/nowhere/missing.pdf")
        await authenticate(client, user)

        assert (await client.get(guide_url(repo))).json()["pdf_ready"] is False

    async def test_is_true_for_a_pdf_that_exists(self, client, db_session, tmp_path):
        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)
        pdf = tmp_path / "guide.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        await make_guide(db_session, repo, pdf_path=str(pdf))
        await authenticate(client, user)

        assert (await client.get(guide_url(repo))).json()["pdf_ready"] is True


class TestGuards:
    async def test_reports_not_found_when_no_guide_was_generated(self, client, db_session):
        """Ingested but guideless is a 404, distinct from the 409 the graph returns."""
        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)
        await authenticate(client, user)

        response = await client.get(guide_url(repo))

        assert response.status_code == 404
        assert "not generated" in response.json()["detail"].lower()

    async def test_another_users_repository_is_not_found(self, client, db_session):
        mine = await make_user(db_session)
        theirs = await make_user(db_session)
        their_repo, _ = await make_ingested_repo(db_session, theirs)
        await make_guide(db_session, their_repo, reading_order=READING_ORDER)
        await authenticate(client, mine)

        assert (await client.get(guide_url(their_repo))).status_code == 404

    async def test_an_unknown_id_is_not_found(self, client, db_session):
        await authenticate(client, await make_user(db_session))

        assert (await client.get(f"/api/v1/repository/{random_uuid()}/guide")).status_code == 404

    async def test_requires_authentication(self, client, guided):
        _, repo = guided
        client.cookies.clear()

        assert (await client.get(guide_url(repo))).status_code == 401
