"""The streaming endpoint: events, persistence, replay and the run's lifecycle.

The route runs for real against the test database and Redis. The model is
scripted, the decider answers from a list, and the sessions a run writes with
join the test's transaction; nothing else is replaced. Billing, tool-support
and override rules have their own modules.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from functools import partial

import httpx
import pytest
from openai import AuthenticationError
from sqlalchemy import select

from app.api.v1.agent import get_run_sessions
from app.core.config import settings
from app.core.database import get_async_db
from app.models import AgentRun, AgentStep
from app.services.agent import persistence
from app.services.agent import session as session_module
from app.services.agent.persistence import RunRecorder
from app.services.agent.slots import slot_key
from app.services.retrieval.config import DEEP_AGENT
from tests.fixtures.agent_run import (
    PlanDecider,
    ScriptedModel,
    call,
    finish,
    turn,
)
from tests.fixtures.agent_stream import (
    QUESTION,
    AnyModel,
    Committed,
    Hold,
    RawRequest,
    install,
    make_world,
    of_type,
    only_run,
    parse_sse,
    planner_model,
    runs_url,
    slot_count,
    step_rows,
    stream,
    stream_url,
    turns_of,
    types_of,
)
from tests.fixtures.retrieval import fake_embedder
from tests.helpers import authenticate

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def no_model_backed_stages(monkeypatch):
    """A key in a developer's environment must not turn on the model-backed stages."""
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(settings, "COHERE_API_KEY", "")


@pytest.fixture
async def world(client, db_session):
    return await make_world(client, db_session)


@pytest.fixture
async def live(app, engine):
    """Committed rows and a request session per request, for tests that need real concurrency."""
    committed = Committed(engine)

    async def request_session():
        async with committed.maker() as session:
            yield session

    app.dependency_overrides[get_async_db] = request_session
    yield committed
    await committed.drop()


def agent_model(world) -> ScriptedModel:
    """A model that searches once, then answers with a citation."""
    return ScriptedModel(
        [
            turn(call("search_symbols", {"name": "create_user"})),
            turn(
                finish(
                    f"`verify_password` is defined in app/auth/security.py [{world.symbol_key}]. "
                    f"Users are created in app/users/service.py [{world.user_key}]."
                )
            ),
        ]
    )


async def run_agent_preset(client, app, db_session, world, preset="deep_agent", **body):
    install(app, db_session, agent_model(world), decider=PlanDecider(1.0))
    return await stream(client, world.repo, preset=preset, **body)


COMPARISON = "Compare how a password is checked with how a user is created."


def detail_url(repo, run) -> str:
    return f"{runs_url(repo)}/{run.id}"


# --- what is streamed ----------------------------------------------------------------


class TestStreamShape:
    async def test_the_response_is_an_event_stream_with_the_proxy_headers(
        self, app, client, db_session, world
    ):
        install(app, db_session, agent_model(world), decider=PlanDecider(1.0))

        response = await client.post(
            stream_url(world.repo), json={"question": QUESTION, "preset": "deep_agent"}
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-accel-buffering"] == "no"

    async def test_every_frame_is_named_after_its_type_and_carries_its_seq(
        self, app, client, db_session, world
    ):
        install(app, db_session, agent_model(world), decider=PlanDecider(1.0))

        response = await client.post(
            stream_url(world.repo), json={"question": QUESTION, "preset": "deep_agent"}
        )

        frames = parse_sse(response.text)
        assert frames
        for frame in frames:
            envelope = frame["data"]
            assert frame["event"] == envelope["type"]
            assert frame["id"] == str(envelope["seq"])
            assert set(envelope) == {"seq", "ts", "run_id", "worker_id", "type", "data"}
        seqs = [frame["data"]["seq"] for frame in frames]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

    async def test_an_agent_run_streams_its_work_and_ends_with_done(
        self, app, client, db_session, world
    ):
        _, events = await run_agent_preset(client, app, db_session, world)

        names = types_of(events)
        assert names[0] == "run_started"
        assert names[-1] == "done"
        for expected in ("retrieval", "tool_call", "tool_result", "nodes", "evidence"):
            assert expected in names
        assert names.index("tool_call") < names.index("tool_result") < names.index("done")
        done = events[-1]["data"]
        assert done["status"] == "done"
        assert done["stop_reason"] == "finished"
        assert [c["key"] for c in done["citations"]] == [world.symbol_key, world.user_key]
        assert done["usage"]["tool_calls"] == 1

    async def test_tool_results_say_how_the_call_went(self, app, client, db_session, world):
        _, events = await run_agent_preset(client, app, db_session, world)

        results = [e["data"] for e in of_type(events, "tool_result")]
        search = next(r for r in results if r["tool"] == "search_symbols")
        assert search["status"] == "ok"
        assert search["result_count"] >= 1
        assert search["summary"]
        assert search["latency_ms"] >= 0
        assert search["truncated"] is False

    async def test_run_started_names_the_preset_and_the_configuration(
        self, app, client, db_session, world
    ):
        _, events = await run_agent_preset(client, app, db_session, world)

        started = events[0]["data"]
        assert started["preset"] == "deep_agent"
        assert started["config_hash"] == DEEP_AGENT.config_hash()
        assert started["execution"] == "agent"
        assert started["model"] == "openai:gpt-4o-mini"

    async def test_the_envelope_names_the_run_and_every_event_shares_it(
        self, app, client, db_session, world
    ):
        _, events = await run_agent_preset(client, app, db_session, world)

        run = await only_run(db_session, world.repo)
        assert {event["run_id"] for event in events} == {str(run.id)}

    async def test_a_single_shot_preset_goes_through_the_same_route(
        self, app, client, db_session, world
    ):
        install(app, db_session, AnyModel("It is defined in app/auth/security.py."))

        _, events = await stream(client, world.repo, preset="hybrid")

        names = types_of(events)
        assert names[0] == "run_started" and names[-1] == "done"
        assert "retrieval" in names and "answer_delta" in names
        assert "tool_call" not in names
        text = "".join(e["data"]["text"] for e in of_type(events, "answer_delta"))
        assert text == events[-1]["data"]["answer"]
        assert events[0]["data"]["execution"] == "single_shot"
        retrieval = of_type(events, "retrieval")[0]["data"]
        assert retrieval["source"] == "pipeline"
        assert retrieval["keys"]
        assert set(retrieval["channels"]) >= {"lexical", "symbol"}
        # The question itself is always the first phrasing searched.
        assert retrieval["queries"][0]["kind"] in ("original", "condensed")
        assert retrieval["queries"][0]["text"]

    async def test_a_planner_run_tags_worker_events_with_their_lane(
        self, app, client, db_session, world
    ):
        install(app, db_session, planner_model(world), decider=PlanDecider(1.0, 0.95))

        _, events = await stream(client, world.repo, COMPARISON, preset="deep_agent_workers")

        [plan] = of_type(events, "plan")
        assert plan["data"]["skipped"] is False
        assert [sub["id"] for sub in plan["data"]["subquestions"]] == ["w1", "w2"]
        started = of_type(events, "worker_started")
        # The plan names each lane by the id its worker reports, so a client
        # draws one lane per sub-question, not one per id it has seen.
        assert {e["data"]["worker_id"] for e in started} == {"w1", "w2"}
        done = of_type(events, "worker_done")
        assert {e["worker_id"] for e in started} == {"w1", "w2"}
        assert {e["worker_id"] for e in done} == {"w1", "w2"}
        questions = {e["worker_id"]: e["data"]["question"] for e in started}
        assert questions == {
            "w1": "Where is `verify_password` defined?",
            "w2": "Where is `create_user` defined?",
        }
        assert {e["data"]["stop_reason"] for e in done} == {"finished"}
        # Tool calls belong to a lane; the main agent's events carry none.
        assert {e["worker_id"] for e in of_type(events, "tool_call")} <= {"w1", "w2"}
        assert events[-1]["type"] == "done"
        assert events[-1]["data"]["answer"].startswith("Passwords are checked")
        assert events[-1]["worker_id"] is None


# --- what is stored ------------------------------------------------------------------


class TestPersistence:
    async def test_the_run_row_records_the_question_the_configuration_and_the_outcome(
        self, app, client, db_session, world
    ):
        await run_agent_preset(client, app, db_session, world)

        run = await only_run(db_session, world.repo)
        assert run.user_id == world.user.id
        assert run.question == QUESTION
        assert run.preset == "deep_agent"
        assert run.config == DEEP_AGENT.model_dump(mode="json")
        assert run.config_hash == DEEP_AGENT.config_hash()
        assert run.prompt_version
        assert run.model == "openai:gpt-4o-mini"
        assert run.decider and run.decider.startswith("jev:")
        assert run.ingested_commit_sha == world.repo.ingested_commit_sha
        assert run.status == "done"
        assert run.stop_reason == "finished"
        assert run.answer and "verify_password" in run.answer
        assert [c["key"] for c in run.citations] == [world.symbol_key, world.user_key]
        assert run.tool_calls == 1
        assert run.iterations == 2
        assert run.usage["input_tokens"] > 0
        assert run.latency_ms is not None and run.latency_ms >= 0
        assert run.error is None
        assert run.finished_at is not None

    async def test_event_rows_match_what_was_streamed_in_order(
        self, app, client, db_session, world
    ):
        _, events = await run_agent_preset(client, app, db_session, world)

        run = await only_run(db_session, world.repo)
        rows = [row for row in await step_rows(db_session, run.id) if row.kind == "event"]
        assert [(r.seq, r.name, r.worker_id, r.payload) for r in rows] == [
            (e["seq"], e["type"], e["worker_id"], e["data"]) for e in events
        ]

    async def test_detail_steps_are_stored_beside_the_events_in_one_order(
        self, app, client, db_session, world
    ):
        _, events = await run_agent_preset(client, app, db_session, world)

        run = await only_run(db_session, world.repo)
        rows = await step_rows(db_session, run.id)
        kinds = {row.kind for row in rows}
        assert {"event", "seed", "model_call", "tool_call"} <= kinds
        assert [row.seq for row in rows] == sorted({row.seq for row in rows})
        model_calls = [row for row in rows if row.kind == "model_call"]
        assert all(row.tokens_in is not None for row in model_calls)
        assert all("step_index" in row.payload for row in rows if row.kind != "event")

    async def test_a_single_shot_run_is_recorded_too(self, app, client, db_session, world):
        install(app, db_session, AnyModel("Answer."))

        _, events = await stream(client, world.repo, preset="hybrid")

        run = await only_run(db_session, world.repo)
        assert run.status == "done" and run.stop_reason == "answered"
        assert run.preset == "hybrid"
        assert run.prompt_version is None and run.decider is None
        rows = [r for r in await step_rows(db_session, run.id) if r.kind == "event"]
        assert [r.seq for r in rows] == [e["seq"] for e in events]

    async def test_the_turn_is_saved_and_linked_to_the_run(self, app, client, db_session, world):
        _, events = await run_agent_preset(client, app, db_session, world)

        run = await only_run(db_session, world.repo)
        [message] = await turns_of(db_session, world.repo)
        assert message.agent_run_id == run.id
        assert run.chat_message_id == message.id
        assert message.question == QUESTION
        assert message.answer == events[-1]["data"]["answer"]
        assert message.user_id == world.user.id
        assert [s["file_path"] for s in message.sources] == [
            "app/auth/security.py",
            "app/users/service.py",
        ]
        assert events[-1]["data"]["chat_message_id"] == str(message.id)

    async def test_the_turn_reloads_through_the_existing_history_endpoint(
        self, app, client, db_session, world
    ):
        _, events = await run_agent_preset(client, app, db_session, world)

        history = (await client.get(f"/api/v1/repository/{world.repo.id}/chat/history")).json()

        assert [turn_["answer"] for turn_ in history] == [events[-1]["data"]["answer"]]
        assert history[0]["question"] == QUESTION
        assert history[0]["sources"][0]["source_type"] == "symbol"

    async def test_nothing_secret_is_stored_or_streamed(self, app, client, db_session, world):
        response, _ = await run_agent_preset(client, app, db_session, world)

        run = await only_run(db_session, world.repo)
        rows = await step_rows(db_session, run.id)
        token = client.cookies.get("access_token")
        stored = json.dumps(
            [row.payload for row in rows] + [run.config, run.usage, run.citations], default=str
        )
        for secret in ("sk-user-secret", token):
            assert secret not in stored
            assert secret not in response.text

    async def test_a_failed_run_keeps_its_steps_and_saves_no_turn(
        self, app, client, db_session, world
    ):
        rejected = AuthenticationError(
            "bad key",
            response=httpx.Response(401, request=httpx.Request("POST", "https://x")),
            body=None,
        )
        model = ScriptedModel(
            [turn(call("search_symbols", {"name": "create_user"})), turn(error=rejected)]
        )
        install(app, db_session, model, decider=PlanDecider(1.0))

        _, events = await stream(client, world.repo, preset="deep_agent")

        assert events[-1]["type"] == "error"
        assert "done" not in types_of(events)
        error = events[-1]["data"]
        assert error["kind"] == "auth" and error["status"] == 502
        assert "Provider rejected the API key" in error["message"]
        run = await only_run(db_session, world.repo)
        assert run.status == "failed"
        assert "Provider rejected the API key" in run.error
        assert run.answer is None
        assert await turns_of(db_session, world.repo) == []
        stored = [r.name for r in await step_rows(db_session, run.id) if r.kind == "event"]
        assert stored[-1] == "error" and "tool_call" in stored

    async def test_a_single_shot_failure_is_reported_the_same_way(
        self, app, client, db_session, world
    ):
        from openai import APIConnectionError

        model = ScriptedModel(
            [turn(error=APIConnectionError(request=httpx.Request("POST", "https://x")))]
        )
        install(app, db_session, model)

        _, events = await stream(client, world.repo, preset="hybrid")

        assert events[-1]["type"] == "error"
        assert events[-1]["data"]["kind"] == "unreachable"
        assert (await only_run(db_session, world.repo)).status == "failed"
        assert await turns_of(db_session, world.repo) == []

    async def test_a_write_failure_does_not_kill_the_run(
        self, app, client, db_session, world, monkeypatch
    ):
        def broken(*args, **kwargs):
            raise RuntimeError("the database is down")

        monkeypatch.setattr(persistence, "insert", broken)

        _, events = await run_agent_preset(client, app, db_session, world)

        assert events[-1]["type"] == "done"
        degraded = [
            e["data"] for e in of_type(events, "degraded") if e["data"]["stage"] == "recording"
        ]
        assert len(degraded) == 1
        run = await only_run(db_session, world.repo)
        assert run.status == "done"
        assert await step_rows(db_session, run.id) == []

    async def test_records_past_the_cap_are_counted_not_stored(
        self, app, client, db_session, world, monkeypatch
    ):
        monkeypatch.setattr(
            session_module, "RunRecorder", partial(RunRecorder, max_steps=2, max_events=6)
        )

        _, events = await run_agent_preset(client, app, db_session, world)

        run = await only_run(db_session, world.repo)
        rows = await step_rows(db_session, run.id)
        event_rows = [r for r in rows if r.kind == "event"]
        detail_rows = [r for r in rows if r.kind != "event"]
        assert len(detail_rows) == 2
        # Six ordinary events, and the terminal one that is always kept.
        assert len(event_rows) == 7
        assert event_rows[-1].name == "done"
        assert len(events) > len(event_rows)
        assert events[-1]["data"]["steps_dropped"] > 0
        assert run.status == "done"


# --- replay --------------------------------------------------------------------------


class TestReplay:
    async def test_replay_returns_the_live_sequence_exactly(self, app, client, db_session, world):
        _, live = await run_agent_preset(client, app, db_session, world)
        run = await only_run(db_session, world.repo)

        replay = (await client.get(detail_url(world.repo, run))).json()

        assert replay["events"] == live

    async def test_replay_of_a_single_shot_run_matches_too(self, app, client, db_session, world):
        install(app, db_session, AnyModel("Answer."))
        _, live = await stream(client, world.repo, preset="hybrid")
        run = await only_run(db_session, world.repo)

        replay = (await client.get(detail_url(world.repo, run))).json()

        assert replay["events"] == live

    async def test_replay_of_a_parallel_run_keeps_every_lane(self, app, client, db_session, world):
        install(app, db_session, planner_model(world), decider=PlanDecider(1.0, 0.95))
        _, live = await stream(client, world.repo, COMPARISON, preset="deep_agent_workers")
        run = await only_run(db_session, world.repo)

        replay = (await client.get(detail_url(world.repo, run))).json()

        assert replay["events"] == live
        assert {e["worker_id"] for e in replay["events"]} >= {"w1", "w2", None}

    async def test_the_detail_carries_the_run_and_its_outcome(self, app, client, db_session, world):
        _, live = await run_agent_preset(client, app, db_session, world)
        run = await only_run(db_session, world.repo)

        detail = (await client.get(detail_url(world.repo, run))).json()

        assert detail["id"] == str(run.id)
        assert detail["status"] == "done"
        assert detail["preset"] == "deep_agent"
        assert detail["question"] == QUESTION
        assert detail["answer"] == live[-1]["data"]["answer"]
        assert detail["config_hash"] == DEEP_AGENT.config_hash()
        assert detail["chat_message_id"] == live[-1]["data"]["chat_message_id"]
        assert detail["events_available"] is True
        assert detail["usage"]["tool_calls"] == 1

    async def test_a_run_whose_steps_were_pruned_says_so(self, app, client, db_session, world):
        await run_agent_preset(client, app, db_session, world)
        run = await only_run(db_session, world.repo)
        from sqlalchemy import delete

        await db_session.execute(delete(AgentStep).where(AgentStep.run_id == run.id))
        await db_session.flush()

        detail = (await client.get(detail_url(world.repo, run))).json()

        assert detail["events"] == [] and detail["events_available"] is False
        assert detail["status"] == "done" and detail["answer"]

    async def test_an_unknown_run_is_not_found(self, client, world):
        import uuid

        response = await client.get(f"{runs_url(world.repo)}/{uuid.uuid4()}")

        assert response.status_code == 404


async def insert_run(db, world, *, status="running", created=None, **fields) -> AgentRun:
    run = AgentRun(
        user_id=world.user.id,
        repository_id=world.repo.id,
        question=fields.pop("question", "q"),
        preset="classic",
        config={},
        config_hash="0" * 64,
        status=status,
        created_at=created or datetime.now(UTC),
        **fields,
    )
    db.add(run)
    await db.flush()
    return run


class TestListing:
    async def test_runs_are_listed_newest_first_and_limited(self, client, db_session, world):
        now = datetime.now(UTC)
        for minutes, question in ((30, "oldest"), (20, "middle"), (10, "newest")):
            await insert_run(
                db_session,
                world,
                status="done",
                created=now - timedelta(minutes=minutes),
                question=question,
            )

        everything = (await client.get(runs_url(world.repo))).json()
        limited = (await client.get(runs_url(world.repo), params={"limit": 2})).json()

        assert [r["question"] for r in everything] == ["newest", "middle", "oldest"]
        assert [r["question"] for r in limited] == ["newest", "middle"]
        assert "events" not in everything[0] and "answer" not in everything[0]

    async def test_each_run_carries_the_tokens_it_spent(self, client, db_session, world):
        await insert_run(
            db_session,
            world,
            status="done",
            usage={"input_tokens": 1200, "output_tokens": 340, "tool_calls": 3},
        )
        await insert_run(db_session, world, status="done", question="no usage")

        listed = {r["question"]: r for r in (await client.get(runs_url(world.repo))).json()}

        assert listed["q"]["input_tokens"] == 1200
        assert listed["q"]["output_tokens"] == 340
        assert listed["no usage"]["input_tokens"] is None

    async def test_the_limit_is_bounded(self, client, world):
        assert (await client.get(runs_url(world.repo), params={"limit": 0})).status_code == 422
        assert (await client.get(runs_url(world.repo), params={"limit": 101})).status_code == 422

    async def test_only_the_callers_runs_on_this_repository_are_listed(
        self, client, db_session, world
    ):
        from tests.factories import make_repo, make_user

        mine = await insert_run(db_session, world, status="done", question="mine")
        other_repo = await make_repo(db_session, world.user, name="elsewhere")
        stranger = await make_user(db_session)
        db_session.add_all(
            [
                AgentRun(
                    user_id=world.user.id,
                    repository_id=other_repo.id,
                    question="other repo",
                    preset="classic",
                    config={},
                    config_hash="0" * 64,
                ),
                AgentRun(
                    user_id=stranger.id,
                    repository_id=world.repo.id,
                    question="someone else's",
                    preset="classic",
                    config={},
                    config_hash="0" * 64,
                ),
            ]
        )
        await db_session.flush()

        listed = (await client.get(runs_url(world.repo))).json()

        assert [r["id"] for r in listed] == [str(mine.id)]


class TestInterruptedRuns:
    async def test_a_run_left_running_by_a_killed_process_reads_as_interrupted(
        self, client, db_session, world
    ):
        long_ago = datetime.now(UTC) - timedelta(hours=1)
        run = await insert_run(db_session, world, created=long_ago)
        db_session.add(
            AgentStep(
                run_id=run.id,
                seq=1,
                kind="event",
                name="run_started",
                payload={
                    "preset": "classic",
                    "config_hash": "x",
                    "model": "m",
                    "execution": "single_shot",
                },
                created_at=long_ago,
            )
        )
        await db_session.flush()

        detail = (await client.get(detail_url(world.repo, run))).json()
        listed = (await client.get(runs_url(world.repo))).json()

        assert detail["status"] == "interrupted"
        assert [e["type"] for e in detail["events"]] == ["run_started"]
        assert listed[0]["status"] == "interrupted"

    async def test_a_run_that_is_still_writing_reads_as_running(self, client, db_session, world):
        started = datetime.now(UTC) - timedelta(hours=1)
        run = await insert_run(db_session, world, created=started)
        db_session.add(
            AgentStep(
                run_id=run.id,
                seq=1,
                kind="tool_call",
                name="tools",
                payload={},
                created_at=datetime.now(UTC),
            )
        )
        await db_session.flush()

        detail = (await client.get(detail_url(world.repo, run))).json()

        assert detail["status"] == "running"

    async def test_a_fresh_run_is_running(self, client, db_session, world):
        run = await insert_run(db_session, world)

        detail = (await client.get(detail_url(world.repo, run))).json()

        assert detail["status"] == "running"

    async def test_a_finished_run_is_never_interrupted(self, client, db_session, world):
        run = await insert_run(
            db_session, world, status="failed", created=datetime.now(UTC) - timedelta(days=2)
        )

        detail = (await client.get(detail_url(world.repo, run))).json()

        assert detail["status"] == "failed"


# --- the client hangs up -------------------------------------------------------------


class TestDisconnect:
    async def test_hanging_up_cancels_the_run_and_keeps_what_it_did(
        self, app, client, db_session, world, redis_client
    ):
        hold = Hold()
        model = ScriptedModel([turn(finish("never reached"), before=hold)])
        install(app, db_session, model, decider=PlanDecider(1.0))
        raw = RawRequest(
            app,
            client,
            f"/api/v1/repository/{world.repo.id}/chat/stream",
            {"question": QUESTION, "preset": "deep_agent"},
        )

        raw.start()
        await asyncio.wait_for(hold.reached.wait(), 15)
        assert await slot_count(redis_client, world.user) == 1
        await raw.hang_up()

        run = await only_run(db_session, world.repo)
        assert run.status == "cancelled"
        assert run.stop_reason == "cancelled"
        assert run.finished_at is not None
        assert run.answer is None
        rows = await step_rows(db_session, run.id)
        assert [r.name for r in rows if r.kind == "event"][0] == "run_started"
        assert "seed" in {r.kind for r in rows}
        assert await turns_of(db_session, world.repo) == []
        assert await slot_count(redis_client, world.user) == 0

    async def test_a_cancelled_run_is_not_charged(
        self, app, client, db_session, redis_client, monkeypatch
    ):
        from types import SimpleNamespace

        from app.services import llm_config

        world = await make_world(client, db_session, byok=False)
        hold = Hold()
        model = AnyModel()
        original = model.create

        async def slow(**kwargs):
            if kwargs.get("stream"):
                await hold()
            return await original(**kwargs)

        model.create = slow  # type: ignore[method-assign]
        stub = SimpleNamespace(AI_API_KEY="sk-server", AI_MODEL="deepseek-flash", AI_BASE_URL="")
        monkeypatch.setattr(llm_config, "settings", stub)
        install(app, db_session, model)
        raw = RawRequest(
            app,
            client,
            f"/api/v1/repository/{world.repo.id}/chat/stream",
            {"question": QUESTION, "preset": "hybrid"},
        )

        raw.start()
        await asyncio.wait_for(hold.reached.wait(), 15)
        await raw.hang_up()

        await db_session.refresh(world.user)
        assert world.user.free_chat_messages_used == 0
        assert (await only_run(db_session, world.repo)).status == "cancelled"
        assert await turns_of(db_session, world.repo) == []


# --- the concurrency cap -------------------------------------------------------------


class TestSlots:
    async def test_the_third_request_is_refused_while_two_are_running(
        self, app, client, live, redis_client
    ):
        # Both runs hold their model call open, so both slots stay taken. The runs and
        # the requests each need a connection of their own, hence committed rows.
        user, repo = await live.user_with_repo(byok=True)
        await authenticate(client, user)
        holds = [Hold(), Hold()]
        model = ScriptedModel(
            [turn(finish("one"), before=holds[0]), turn(finish("two"), before=holds[1])]
        )
        install(app, None, model, sessions=live.maker, decider=PlanDecider(1.0))

        async def ask():
            return await stream(client, repo, preset="deep_agent")

        first = asyncio.create_task(ask())
        await asyncio.wait_for(holds[0].reached.wait(), 15)
        second = asyncio.create_task(ask())
        await asyncio.wait_for(holds[1].reached.wait(), 15)

        assert await slot_count(redis_client, user) == 2
        ttl = await redis_client.ttl(slot_key(user.id))
        assert 0 < ttl <= 960
        refused = await client.post(
            stream_url(repo), json={"question": QUESTION, "preset": "deep_agent"}
        )

        assert refused.status_code == 429
        assert "at once" in refused.json()["detail"]
        assert len(model.requests) == 2
        holds[0].release.set()
        holds[1].release.set()
        results = await asyncio.gather(first, second)
        assert [events[-1]["type"] for _, events in results] == ["done", "done"]
        assert await slot_count(redis_client, user) == 0
        async with live.maker() as db:
            runs = (await db.execute(select(AgentRun).where(AgentRun.user_id == user.id))).scalars()
            assert len(list(runs)) == 2

    async def test_a_finished_run_gives_its_slot_back(
        self, app, client, db_session, world, redis_client
    ):
        install(
            app,
            db_session,
            ScriptedModel([turn(finish("a")), turn(finish("b")), turn(finish("c"))]),
            decider=PlanDecider(1.0),
        )

        for _ in range(3):
            _, events = await stream(client, world.repo, preset="deep_agent")
            assert events[-1]["type"] == "done"

        assert await slot_count(redis_client, world.user) == 0

    async def test_a_failed_run_gives_its_slot_back(
        self, app, client, db_session, world, redis_client
    ):
        install(
            app,
            db_session,
            ScriptedModel([turn(error=RuntimeError("boom"))]),
            decider=PlanDecider(1.0),
        )

        _, events = await stream(client, world.repo, preset="deep_agent")

        assert events[-1]["type"] == "error"
        assert events[-1]["data"]["kind"] == "internal"
        assert await slot_count(redis_client, world.user) == 0

    async def test_a_run_that_crashes_outright_gives_its_slot_back(
        self, app, client, db_session, world, redis_client
    ):
        def broken_factory(**kwargs):
            raise RuntimeError("could not build the client")

        install(app, db_session, client_factory=broken_factory, decider=PlanDecider(1.0))

        _, events = await stream(client, world.repo, preset="deep_agent")

        assert events[-1]["type"] == "error"
        assert (await only_run(db_session, world.repo)).status == "failed"
        assert await slot_count(redis_client, world.user) == 0

    async def test_the_slot_key_expires_even_if_nothing_releases_it(
        self, client, world, redis_client
    ):
        from app.services.agent.slots import RunSlots

        slots = RunSlots()
        assert await slots.acquire(world.user.id) is True

        assert 0 < await redis_client.ttl(slot_key(world.user.id)) <= 960
        await redis_client.delete(slot_key(world.user.id))

    async def test_a_refused_request_leaves_no_run_behind(
        self, app, client, db_session, world, redis_client
    ):
        await redis_client.set(slot_key(world.user.id), 2, ex=60)
        model = ScriptedModel([turn(finish("never"))])
        install(app, db_session, model, decider=PlanDecider(1.0))

        refused = await client.post(
            stream_url(world.repo), json={"question": QUESTION, "preset": "deep_agent"}
        )

        assert refused.status_code == 429
        assert model.requests == []
        assert await runs_of_user(db_session, world) == []
        # The refusal gave back the slot it briefly took.
        assert await slot_count(redis_client, world.user) == 2
        await redis_client.delete(slot_key(world.user.id))


async def runs_of_user(db, world):
    from sqlalchemy import select

    return list(
        (await db.execute(select(AgentRun).where(AgentRun.user_id == world.user.id)))
        .scalars()
        .all()
    )


class TestRequestChecks:
    async def test_an_unready_repository_is_refused(self, app, client, db_session, world):
        world.repo.status = "pending"
        await db_session.flush()
        install(app, db_session, ScriptedModel())

        response = await client.post(stream_url(world.repo), json={"question": QUESTION})

        assert response.status_code == 400
        assert "not ready" in response.json()["detail"]

    async def test_an_unknown_preset_is_a_validation_error(self, client, world):
        response = await client.post(
            stream_url(world.repo), json={"question": QUESTION, "preset": "nope"}
        )

        assert response.status_code == 422

    async def test_unknown_body_fields_are_rejected(self, client, world):
        response = await client.post(
            stream_url(world.repo), json={"question": QUESTION, "token": "abc"}
        )

        assert response.status_code == 422

    async def test_history_is_replayed_and_capped_like_the_chat_route(
        self, app, client, db_session, world
    ):
        model = AnyModel()
        vector = list(
            world.seeded.symbol_embeddings[("app/auth/security.py", "verify_password")].embedding
        )
        install(app, db_session, model, embed=fake_embedder({QUESTION: vector}))
        history = [
            {"role": "user" if n % 2 == 0 else "assistant", "content": f"turn {n}"}
            for n in range(8)
        ]

        _, events = await stream(client, world.repo, preset="classic", history=history)

        assert events[-1]["type"] in {"done"}
        answering = [r for r in model.requests if r.get("stream")]
        sent = answering[0]["input"]
        contents = [m["content"] for m in sent if m["role"] != "system"]
        assert contents[:-1] == [f"turn {n}" for n in range(3, 8)]
        assert contents[-1] == QUESTION


def test_the_sessions_seam_defaults_to_the_production_factory():
    from app.core.database import AsyncSessionLocal

    assert get_run_sessions() is AsyncSessionLocal
