"""Retention of agent run steps: old steps go, runs and recent steps stay.

Runs against committed rows on the test database (the task opens its own sync
session), and cleans up after itself. Assertions are on the rows each test seeded, since
the task prunes every old step in the table and other tests may be running beside it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.core.celery import celery
from app.models import AgentRun, AgentStep, Repository, User
from app.services.agent.persistence import RETENTION_DAYS
from app.tasks import agent_retention
from app.tasks.agent_retention import prune_agent_steps
from tests.conftest import TEST_SYNC_DB_URL

pytestmark = pytest.mark.integration


@pytest.fixture
def seeded():
    """A user, a repository and a run, committed; removed afterwards."""
    engine = create_engine(TEST_SYNC_DB_URL)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    user = User(id=uuid.uuid4(), name="Retention", email=f"ret-{uuid.uuid4().hex}@example.com")
    session.add(user)
    session.commit()
    repo = Repository(
        id=uuid.uuid4(),
        user_id=user.id,
        github_url=f"https://github.com/example/{uuid.uuid4().hex[:8]}",
        name="retention",
        status="ready",
    )
    session.add(repo)
    session.commit()
    run = AgentRun(
        id=uuid.uuid4(),
        user_id=user.id,
        repository_id=repo.id,
        question="q",
        preset="classic",
        config={},
        config_hash="0" * 64,
        status="done",
        answer="kept",
    )
    session.add(run)
    session.commit()
    try:
        yield session, run
    finally:
        session.rollback()
        session.execute(delete(User).where(User.id == user.id))
        session.commit()
        session.close()
        engine.dispose()


def add_steps(session, run, ages_in_days):
    for seq, age in enumerate(ages_in_days, start=1):
        session.add(
            AgentStep(
                run_id=run.id,
                seq=seq,
                kind="event",
                name="evidence",
                payload={"keys": []},
                created_at=datetime.now(UTC) - timedelta(days=age),
            )
        )
    session.commit()


def remaining(session, run) -> list[int]:
    session.expire_all()
    return sorted(
        session.execute(select(AgentStep.seq).where(AgentStep.run_id == run.id)).scalars().all()
    )


def test_steps_older_than_the_retention_period_are_deleted(seeded):
    session, run = seeded
    add_steps(session, run, [RETENTION_DAYS + 5, RETENTION_DAYS + 1, 29, 1, 0])

    prune_agent_steps.apply().get()

    assert remaining(session, run) == [3, 4, 5]


def test_the_run_itself_is_kept(seeded):
    session, run = seeded
    add_steps(session, run, [90, 91])

    prune_agent_steps.apply().get()

    assert remaining(session, run) == []
    kept = session.execute(select(AgentRun).where(AgentRun.id == run.id)).scalar_one()
    assert kept.answer == "kept"


def test_a_shorter_retention_can_be_asked_for(seeded):
    session, run = seeded
    add_steps(session, run, [10, 3, 1])

    prune_agent_steps.apply(args=[7]).get()

    assert remaining(session, run) == [2, 3]


def test_nothing_is_deleted_when_everything_is_recent(seeded):
    session, run = seeded
    add_steps(session, run, [0, 1, 2])

    prune_agent_steps.apply(args=[RETENTION_DAYS]).get()

    assert remaining(session, run) == [1, 2, 3]


def test_deletion_proceeds_in_batches(seeded, monkeypatch):
    session, run = seeded
    monkeypatch.setattr(agent_retention, "PRUNE_BATCH_SIZE", 2)
    add_steps(session, run, [60, 61, 62, 63, 64, 1])

    prune_agent_steps.apply(args=[RETENTION_DAYS]).get()

    assert remaining(session, run) == [6]


def test_the_task_is_registered_and_scheduled_beside_the_sweep():
    import app.tasks.autoupdate  # noqa: F401  (installs the schedule on import)

    schedule = celery.conf.beat_schedule

    assert "sweep-due-repositories" in schedule
    entry = schedule["prune-agent-steps"]
    assert entry["task"] == "app.tasks.agent_retention.prune_agent_steps"
    assert entry["schedule"].hour == {3} and entry["schedule"].minute == {40}


def test_the_worker_includes_the_retention_module():
    assert "app.tasks.agent_retention" in celery.conf.include
