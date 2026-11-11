"""Time spans in a question: the history channel and ``search_history`` filter on them.

The fixture's commits are authored on 2026-01-01, 02 and 03. Its first pull
request is merged on 2026-01-10 and its second on 2026-02-10; the fixture leaves
both unmerged, so the tests set the dates.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from freezegun import freeze_time

from app.services.agent.tools import REGISTRY
from app.services.retrieval.candidate import QueryVariant
from app.services.retrieval.channels import get_channel
from app.services.retrieval.citations import commit_key
from app.services.retrieval.config import HistoryChannel
from app.services.retrieval.dates import DateRange
from tests.factories import make_user
from tests.fixtures.agent_tools import make_tool_context, session_factory_for
from tests.fixtures.retrieval import axis_vector, make_context, seed_repo

pytestmark = pytest.mark.integration

FIRST = "a1b2c3d4e5f60718"  # 2026-01-01, "fix: reject expired tokens in verify_password"
SECOND = "b2c3d4e5f6071829"  # 2026-01-02, "feat: add invoice totals"
QUERY = "reject expired tokens add invoice totals password hashing bcrypt discounts"


def day(month: int, number: int) -> datetime:
    return datetime(2026, month, number, tzinfo=UTC)


@pytest.fixture
async def seeded(db_session):
    seeded = await seed_repo(db_session, await make_user(db_session))
    seeded.pull_requests[12].merged_at = day(1, 10)
    seeded.pull_requests[13].merged_at = day(2, 10)
    await db_session.flush()
    return seeded


async def search(db, seeded, date_range=None):
    ctx = make_context(db, seeded.repo, {QUERY: axis_vector(0)})
    ctx.date_range = date_range
    found = await get_channel("history").search(ctx, QueryVariant(QUERY), HistoryChannel())
    return {candidate.key for candidate in found}


def keys_of(seeded, *hashes: str, prs: tuple[int, ...] = ()) -> set[str]:
    return {commit_key(h) for h in hashes} | {f"PR:{n}" for n in prs}


class TestTheChannel:
    async def test_without_a_range_everything_is_searched(self, db_session, seeded):
        found = await search(db_session, seeded)

        assert keys_of(seeded, FIRST, SECOND, prs=(12, 13)) <= found

    async def test_commits_outside_the_range_are_excluded(self, db_session, seeded):
        found = await search(db_session, seeded, DateRange(day(1, 2), day(1, 31)))

        assert commit_key(FIRST) not in found
        assert commit_key(SECOND) in found

    async def test_the_range_ends_are_inclusive(self, db_session, seeded):
        found = await search(db_session, seeded, DateRange(day(1, 1), day(1, 2)))

        assert {commit_key(FIRST), commit_key(SECOND)} <= found

    async def test_pull_requests_are_filtered_by_their_merge_date(self, db_session, seeded):
        found = await search(db_session, seeded, DateRange(day(1, 5), day(1, 31)))

        assert "PR:12" in found
        assert "PR:13" not in found
        assert not {commit_key(FIRST), commit_key(SECOND)} & found

    async def test_a_pull_request_that_was_never_merged_is_left_out_of_a_range(
        self, db_session, seeded
    ):
        seeded.pull_requests[12].merged_at = None
        await db_session.flush()

        found = await search(db_session, seeded, DateRange(day(1, 1), day(12, 31)))

        assert "PR:12" not in found

    async def test_a_range_with_nothing_in_it_finds_nothing(self, db_session, seeded):
        assert await search(db_session, seeded, DateRange(day(6, 1), day(6, 30))) == set()

    async def test_an_open_ended_range_filters_one_side(self, db_session, seeded):
        found = await search(db_session, seeded, DateRange(day(1, 2), None))

        assert commit_key(FIRST) not in found
        assert {commit_key(SECOND), "PR:12", "PR:13"} <= found


async def history(db_session, seeded, **arguments):
    question = arguments.pop("question", None)
    ctx = make_tool_context(session_factory_for(db_session.bind), seeded.repo, question=question)
    with freeze_time(datetime(2026, 1, 2, 12, 0, tzinfo=UTC), real_asyncio=True):
        result = await REGISTRY.call("search_history", {"query": QUERY, **arguments}, ctx)
    assert result.status == "ok", result.text
    assert result.data is not None
    return {item["key"] for item in result.data["items"]}, result.text


class TestTheTool:
    async def test_without_dates_the_tool_searches_everything(self, db_session, seeded):
        found, text = await history(db_session, seeded)

        assert {commit_key(FIRST), commit_key(SECOND)} <= found
        assert "Restricted to" not in text

    async def test_a_range_in_the_question_applies_when_the_model_passes_none(
        self, db_session, seeded
    ):
        # "past 1 day" from 2026-01-02 12:00 starts on 2026-01-01 12:00.
        found, text = await history(db_session, seeded, question="What changed in the past 1 day?")

        assert commit_key(FIRST) not in found
        assert commit_key(SECOND) in found
        assert "commits and pull requests from 2026-01-01 to 2026-01-02" in text

    async def test_explicit_arguments_override_the_range_in_the_question(self, db_session, seeded):
        found, text = await history(
            db_session,
            seeded,
            question="What changed in the past 1 day?",
            since="2026-01-01",
            until="2026-01-01",
        )

        assert commit_key(FIRST) in found
        assert commit_key(SECOND) not in found
        assert "from 2026-01-01 to 2026-01-01" in text

    async def test_the_until_day_is_included_whole(self, db_session, seeded):
        found, _ = await history(db_session, seeded, since="2026-01-02", until="2026-01-02")

        assert commit_key(SECOND) in found
        assert commit_key(FIRST) not in found

    async def test_a_since_alone_leaves_the_end_open(self, db_session, seeded):
        found, text = await history(db_session, seeded, since="2026-01-02")

        assert commit_key(FIRST) not in found
        assert {commit_key(SECOND), "PR:12", "PR:13"} <= found
        assert "since 2026-01-02" in text

    async def test_a_malformed_date_is_refused_by_the_tool(self, db_session, seeded):
        ctx = make_tool_context(session_factory_for(db_session.bind), seeded.repo)

        result = await REGISTRY.call("search_history", {"query": QUERY, "since": "March"}, ctx)

        assert result.status != "ok"

    async def test_the_description_tells_the_model_to_pass_dates(self):
        tool = REGISTRY.get("search_history")

        assert "since and until" in tool.description
        assert {"since", "until"} <= set(tool.input_model.model_json_schema()["properties"])


class TestTheRetrievalTrace:
    @staticmethod
    def config():
        from app.services.retrieval.config import STRUCTURAL, QueryConfig, RerankConfig

        return STRUCTURAL.model_copy(
            update={"rerank": RerankConfig(kind="none"), "query": QueryConfig(condense=False)}
        )

    async def test_the_pipeline_reads_a_range_from_the_question_and_reports_it(
        self, db_session, seeded
    ):
        from app.services.retrieval.pipeline import retrieve

        question = "what changed in the past 1 day to reject expired tokens"
        ctx = make_context(db_session, seeded.repo, {question: axis_vector(0)})

        with freeze_time(datetime(2026, 1, 2, 12, 0, tzinfo=UTC), real_asyncio=True):
            result = await retrieve(self.config(), question, ctx=ctx)

        assert result.trace.date_range is not None
        assert result.trace.date_range["description"] == "from 2026-01-01 to 2026-01-02"
        assert result.trace.date_range["phrase"] == "past 1 day"

    async def test_a_question_without_a_time_span_reports_none(self, db_session, seeded):
        from app.services.retrieval.pipeline import retrieve

        question = "why was password hashing changed"
        ctx = make_context(db_session, seeded.repo, {question: axis_vector(0)})

        result = await retrieve(self.config(), question, ctx=ctx)

        assert result.trace.date_range is None
