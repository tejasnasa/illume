"""Answers that may be out of date: what is stored with a turn and what the changes route says.

The write path is checked through both ways a turn gets saved, the legacy chat
route and the streaming route. The marking itself is covered by the sync tests;
here a stale message is built directly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import Commit, Embedding
from app.services.rag import RAGResponse, SourceReference
from tests.factories import make_chat_message, make_ingested_repo, make_user
from tests.fixtures.agent_run import PlanDecider, ScriptedModel, call, finish, turn
from tests.fixtures.agent_stream import (
    QUESTION,
    SECURITY,
    USERS,
    AnyModel,
    install,
    make_world,
    stream,
    turns_of,
)
from tests.fixtures.retrieval import fake_embedder
from tests.helpers import authenticate

pytestmark = pytest.mark.integration

SNAPSHOT = "1" * 40
HEAD = "2" * 40
ASKED = datetime(2026, 1, 1, tzinfo=UTC)


def changes_url(repo, message) -> str:
    return f"/api/v1/repository/{repo.id}/chat/{message.id}/changes"


def history_url(repo) -> str:
    return f"/api/v1/repository/{repo.id}/chat/history"


@pytest.fixture(autouse=True)
def no_model_backed_stages(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")


class TestWhatIsStoredWithATurn:
    async def test_the_legacy_route_stores_the_snapshot_and_every_cited_file(
        self, client, db_session, monkeypatch
    ):
        user = await make_user(db_session, ai_api_key="sk-test")
        repo, _ = await make_ingested_repo(db_session, user)
        repo.ingested_commit_sha = SNAPSHOT
        await db_session.flush()
        await authenticate(client, user)

        async def fake_answer_question(query, repository_id, db, history=None, *, llm=None):
            return RAGResponse(
                answer="An answer.",
                sources=[
                    SourceReference(
                        source_type="symbol", chunk_text="x", file_path="src/a.py", symbol_name="f"
                    ),
                    SourceReference(source_type="file", chunk_text="y", file_path="src/b.py"),
                    SourceReference(
                        source_type="symbol", chunk_text="z", file_path="src/a.py", symbol_name="g"
                    ),
                    SourceReference(source_type="commit", chunk_text="c", commit_hash="abc"),
                    SourceReference(source_type="pull_request", chunk_text="p", pr_number=3),
                ],
            )

        import app.api.v1.chat as chat_module

        monkeypatch.setattr(chat_module, "answer_question", fake_answer_question)

        response = await client.post(
            f"/api/v1/repository/{repo.id}/chat", json={"question": "What is this?"}
        )

        assert response.status_code == 200
        [message] = await turns_of(db_session, repo)
        assert message.answered_commit_sha == SNAPSHOT
        # Distinct, in first-seen order; commits and PRs have no file and add nothing.
        assert message.cited_paths == ["src/a.py", "src/b.py"]
        assert message.stale_at is None

    async def test_a_classic_shaped_stream_counts_every_source_as_cited(
        self, app, client, db_session
    ):
        world = await make_world(client, db_session)
        world.repo.ingested_commit_sha = SNAPSHOT
        await db_session.flush()
        # Classic keeps only chunks near the question, so embed the question where
        # one of the repository's own symbol chunks already is.
        symbol = world.seeded.symbols[(SECURITY, "verify_password")]
        vector = (
            await db_session.execute(
                select(Embedding.embedding).where(
                    Embedding.repository_id == world.repo.id, Embedding.source_id == symbol.id
                )
            )
        ).scalar_one()
        install(
            app,
            db_session,
            AnyModel("It is defined in the auth module."),
            embed=fake_embedder({QUESTION: list(vector)}),
        )

        _, events = await stream(client, world.repo, preset="classic")

        assert events[-1]["type"] == "done"
        [message] = await turns_of(db_session, world.repo)
        cited_files = [s["file_path"] for s in message.sources if s["file_path"]]
        assert cited_files, "the fixture's answer should have file sources"
        assert message.cited_paths == list(dict.fromkeys(cited_files))
        assert message.answered_commit_sha == SNAPSHOT

    async def test_a_cited_shape_stores_only_the_files_the_answer_cited(
        self, app, client, db_session
    ):
        world = await make_world(client, db_session)
        world.repo.ingested_commit_sha = SNAPSHOT
        await db_session.flush()
        install(
            app,
            db_session,
            AnyModel(f"It is checked in {SECURITY} [{world.symbol_key}]."),
        )

        _, events = await stream(client, world.repo, preset="hybrid")

        assert events[-1]["type"] == "done"
        [message] = await turns_of(db_session, world.repo)
        assert message.cited_paths == [SECURITY]

    async def test_an_agent_turn_stores_only_the_files_the_answer_cited(
        self, app, client, db_session
    ):
        world = await make_world(client, db_session)
        world.repo.ingested_commit_sha = SNAPSHOT
        await db_session.flush()
        model = ScriptedModel(
            [
                turn(call("search_symbols", {"name": "create_user"})),
                turn(finish(f"It is checked in {SECURITY} [{world.symbol_key}].")),
            ]
        )
        install(app, db_session, model, decider=PlanDecider(1.0))

        _, events = await stream(client, world.repo, preset="deep_agent")

        assert events[-1]["type"] == "done"
        [message] = await turns_of(db_session, world.repo)
        assert message.cited_paths == [SECURITY]
        assert USERS not in message.cited_paths
        assert message.answered_commit_sha == SNAPSHOT

    async def test_a_repository_without_a_snapshot_stores_none(self, app, client, db_session):
        world = await make_world(client, db_session)
        world.repo.ingested_commit_sha = None
        await db_session.flush()
        install(app, db_session, AnyModel("An answer."))

        await stream(client, world.repo, preset="hybrid")

        [message] = await turns_of(db_session, world.repo)
        assert message.answered_commit_sha is None


class TestHistory:
    async def test_the_history_carries_the_staleness_fields(self, client, db_session):
        user = await make_user(db_session, ai_api_key="sk-test")
        repo, _ = await make_ingested_repo(db_session, user)
        await authenticate(client, user)
        stale_at = datetime(2026, 2, 1, tzinfo=UTC)
        await make_chat_message(
            db_session,
            repo,
            user,
            question="old",
            answered_commit_sha=SNAPSHOT,
            cited_paths=["src/a.py"],
            stale_at=stale_at,
            stale_paths=["src/a.py"],
            stale_commit_sha=HEAD,
        )
        await make_chat_message(db_session, repo, user, question="fresh")

        rows = (await client.get(history_url(repo))).json()

        old, fresh = rows
        assert old["answered_commit_sha"] == SNAPSHOT
        assert old["stale_paths"] == ["src/a.py"]
        assert old["stale_commit_sha"] == HEAD
        assert datetime.fromisoformat(old["stale_at"]) == stale_at
        assert fresh["stale_at"] is None and fresh["stale_paths"] is None
        assert "cited_paths" not in old


async def add_commit(db, repo, number: int, authored_at: datetime, files: list[str]) -> Commit:
    commit = Commit(
        repository_id=repo.id,
        hash=f"{number:040x}",
        author_name=f"Author {number}",
        author_email=f"a{number}@example.test",
        message=f"change {number}",
        files_changed=len(files),
        changed_files_list=files,
        authored_at=authored_at,
    )
    db.add(commit)
    await db.flush()
    return commit


@pytest.fixture
async def stale(client, db_session):
    user = await make_user(db_session, ai_api_key="sk-test")
    repo, _ = await make_ingested_repo(db_session, user)
    repo.github_url = "https://github.com/acme/widgets.git"
    await db_session.flush()
    await authenticate(client, user)
    message = await make_chat_message(
        db_session,
        repo,
        user,
        created_at=ASKED,
        answered_commit_sha=SNAPSHOT,
        cited_paths=["src/a.py", "src/b.py"],
        stale_at=ASKED + timedelta(days=5),
        stale_paths=["src/a.py"],
        stale_commit_sha=HEAD,
    )
    return user, repo, message


class TestChangesRoute:
    async def test_it_lists_the_stale_paths_and_the_commits_that_touched_them(
        self, client, db_session, stale
    ):
        _, repo, message = stale
        await add_commit(db_session, repo, 1, ASKED + timedelta(days=1), ["src/a.py", "src/x.py"])
        await add_commit(db_session, repo, 2, ASKED + timedelta(days=3), ["src/a.py"])
        # Not about a stale path, and before the answer: neither is listed.
        await add_commit(db_session, repo, 3, ASKED + timedelta(days=2), ["src/other.py"])
        await add_commit(db_session, repo, 4, ASKED - timedelta(days=2), ["src/a.py"])
        # Touches a file the answer cited that did not change: not a stale path.
        await add_commit(db_session, repo, 5, ASKED + timedelta(days=4), ["src/b.py"])

        response = await client.get(changes_url(repo, message))

        assert response.status_code == 200
        body = response.json()
        assert body["stale_paths"] == ["src/a.py"]
        assert [c["hash"] for c in body["commits"]] == [f"{2:040x}", f"{1:040x}"]
        newest = body["commits"][0]
        assert newest["message"] == "change 2"
        assert newest["author_name"] == "Author 2"
        assert newest["files"] == ["src/a.py"]
        assert datetime.fromisoformat(newest["authored_at"]) == ASKED + timedelta(days=3)
        assert body["answered_commit_sha"] == SNAPSHOT
        assert body["stale_commit_sha"] == HEAD

    async def test_the_compare_url_names_both_commits(self, client, stale):
        _, repo, message = stale

        body = (await client.get(changes_url(repo, message))).json()

        assert body["compare_url"] == f"https://github.com/acme/widgets/compare/{SNAPSHOT}...{HEAD}"

    async def test_the_compare_url_is_absent_without_both_commits(self, client, db_session, stale):
        _, repo, message = stale
        message.answered_commit_sha = None
        await db_session.flush()

        body = (await client.get(changes_url(repo, message))).json()

        assert body["compare_url"] is None

    async def test_the_list_is_capped_at_twenty_newest_first(self, client, db_session, stale):
        _, repo, message = stale
        for number in range(1, 26):
            await add_commit(
                db_session, repo, number, ASKED + timedelta(hours=number), ["src/a.py"]
            )

        body = (await client.get(changes_url(repo, message))).json()

        hashes = [c["hash"] for c in body["commits"]]
        assert len(hashes) == 20
        assert hashes == [f"{n:040x}" for n in range(25, 5, -1)]

    async def test_a_message_that_is_not_stale_has_nothing_to_list(self, client, db_session, stale):
        user, repo, _ = stale
        fresh = await make_chat_message(db_session, repo, user, created_at=ASKED)
        await add_commit(db_session, repo, 1, ASKED + timedelta(days=1), ["src/a.py"])

        body = (await client.get(changes_url(repo, fresh))).json()

        assert body["stale_paths"] == [] and body["commits"] == []
        assert body["compare_url"] is None

    async def test_another_users_message_is_a_404(self, client, db_session, stale):
        _, repo, message = stale
        stranger = await make_user(db_session, ai_api_key="sk-other")
        await authenticate(client, stranger)

        assert (await client.get(changes_url(repo, message))).status_code == 404

    async def test_a_message_of_another_repository_is_a_404(self, client, db_session, stale):
        user, _, message = stale
        other, _ = await make_ingested_repo(db_session, user, name="second-repo")

        assert (await client.get(changes_url(other, message))).status_code == 404

    async def test_an_unknown_message_is_a_404(self, client, stale):
        _, repo, _ = stale

        response = await client.get(f"/api/v1/repository/{repo.id}/chat/{uuid.uuid4()}/changes")

        assert response.status_code == 404

    async def test_an_unknown_repository_is_a_404(self, client, stale):
        _, _, message = stale

        response = await client.get(f"/api/v1/repository/{uuid.uuid4()}/chat/{message.id}/changes")

        assert response.status_code == 404
