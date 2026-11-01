"""Device push-token registration, and the notifications that use them.

The client registers the Expo push token of each device it runs on, and
asks here whether it has already done so. The server owns the registry, so
these tests are about the two things that go wrong in practice: a client
that registers on every launch filling the table with copies of itself, and
a device signing out taking somebody else's registration with it.

The second half of the file is the rule the whole feature exists for: a
sync the user asked for notifies them, and one the auto-update sweep
picked up does not. Only the server can tell those apart, so the decision
is made in the task -- and it is checked here, against the task, rather
than against the client that would have to trust it.
"""

import uuid

import pytest
from sqlalchemy import select

from app.models.push_token import PushToken
from tests.factories import make_user
from tests.helpers import authenticate

pytestmark = pytest.mark.integration

TOKEN_URL = "/api/v1/push/token"

ANDROID_TOKEN = "ExponentPushToken[android-device-token]"
IOS_TOKEN = "ExponentPushToken[ios-device-token]"


@pytest.fixture
async def user(db_session):
    """A registered user."""
    return await make_user(db_session)


@pytest.fixture
async def signed_in(client, user):
    """The same user, signed in."""
    await authenticate(client, user)
    return user


async def _rows(db_session) -> list[PushToken]:
    """Every stored push token."""
    result = await db_session.execute(select(PushToken))
    return list(result.scalars().all())


async def _tokens_of(db_session, user_id) -> list[str]:
    """The tokens stored for one user."""
    result = await db_session.execute(select(PushToken).where(PushToken.user_id == user_id))
    return [row.token for row in result.scalars().all()]


class TestRegistration:
    async def test_registers_a_token(self, client, signed_in, db_session):
        response = await client.post(
            TOKEN_URL,
            json={"token": ANDROID_TOKEN, "platform": "android"},
        )

        assert response.status_code == 200
        assert response.json() == {"registered": True, "token_count": 1}
        assert await _tokens_of(db_session, signed_in.id) == [ANDROID_TOKEN]

    async def test_registering_the_same_token_twice_refreshes_it(
        self, client, signed_in, db_session
    ):
        """
        A client that registers on every launch must not leave a row behind
        each time. The second registration updates the row it finds.
        """
        await client.post(TOKEN_URL, json={"token": ANDROID_TOKEN, "platform": "android"})
        first = (await _rows(db_session))[0]

        response = await client.post(
            TOKEN_URL,
            json={"token": ANDROID_TOKEN, "platform": "android"},
        )

        assert response.status_code == 200
        assert response.json() == {"registered": True, "token_count": 1}
        rows = await _rows(db_session)
        assert len(rows) == 1
        assert rows[0].id == first.id
        assert rows[0].updated_at >= first.updated_at

    async def test_registering_again_updates_the_platform(self, client, signed_in, db_session):
        """The same device, reported on a different platform."""
        await client.post(TOKEN_URL, json={"token": ANDROID_TOKEN, "platform": "android"})

        await client.post(TOKEN_URL, json={"token": ANDROID_TOKEN, "platform": "ios"})

        rows = await _rows(db_session)
        assert len(rows) == 1
        assert rows[0].platform == "ios"

    async def test_a_token_moves_with_the_account_on_the_device(
        self, client, signed_in, db_session
    ):
        """
        A device that signs out of one account and into another keeps its
        token, so the second registration takes it over. The previous
        account must stop receiving notifications for that phone.
        """
        await client.post(TOKEN_URL, json={"token": ANDROID_TOKEN, "platform": "android"})

        other = await make_user(db_session)
        await authenticate(client, other)
        await client.post(TOKEN_URL, json={"token": ANDROID_TOKEN, "platform": "android"})

        assert await _tokens_of(db_session, signed_in.id) == []
        assert await _tokens_of(db_session, other.id) == [ANDROID_TOKEN]

    async def test_a_device_can_register_itself_twice_under_two_accounts(
        self, client, signed_in, db_session
    ):
        """Two devices, two tokens, one account."""
        await client.post(TOKEN_URL, json={"token": ANDROID_TOKEN, "platform": "android"})
        await client.post(TOKEN_URL, json={"token": IOS_TOKEN, "platform": "ios"})

        assert sorted(await _tokens_of(db_session, signed_in.id)) == sorted(
            [ANDROID_TOKEN, IOS_TOKEN]
        )

    async def test_an_unknown_platform_is_rejected(self, client, signed_in):
        response = await client.post(
            TOKEN_URL,
            json={"token": ANDROID_TOKEN, "platform": "windows"},
        )

        assert response.status_code == 422

    async def test_an_empty_token_is_rejected(self, client, signed_in):
        response = await client.post(TOKEN_URL, json={"token": "", "platform": "android"})

        assert response.status_code == 422

    async def test_registration_requires_authentication(self, client, user, db_session):
        client.cookies.clear()

        response = await client.post(
            TOKEN_URL,
            json={"token": ANDROID_TOKEN, "platform": "android"},
        )

        assert response.status_code == 401
        assert await _rows(db_session) == []


class TestRemoval:
    async def test_removes_the_token(self, client, signed_in, db_session):
        await client.post(TOKEN_URL, json={"token": ANDROID_TOKEN, "platform": "android"})

        response = await client.request("DELETE", TOKEN_URL, json={"token": ANDROID_TOKEN})

        assert response.status_code == 200
        assert response.json() == {"registered": False, "token_count": 0}
        assert await _rows(db_session) == []

    async def test_removes_only_that_token(self, client, signed_in, db_session):
        """
        A device signing out takes its own registration with it and leaves
        the user's other devices registered.
        """
        await client.post(TOKEN_URL, json={"token": ANDROID_TOKEN, "platform": "android"})
        await client.post(TOKEN_URL, json={"token": IOS_TOKEN, "platform": "ios"})

        await client.request("DELETE", TOKEN_URL, json={"token": ANDROID_TOKEN})

        assert await _tokens_of(db_session, signed_in.id) == [IOS_TOKEN]

    async def test_does_not_remove_another_users_token(self, client, signed_in, db_session):
        """The token is only removable by the account that registered it."""
        other = await make_user(db_session)
        db_session.add(PushToken(user_id=other.id, token=IOS_TOKEN, platform="ios"))
        await db_session.commit()

        await client.request("DELETE", TOKEN_URL, json={"token": IOS_TOKEN})

        assert await _tokens_of(db_session, other.id) == [IOS_TOKEN]

    async def test_removing_an_unregistered_token_is_not_an_error(self, client, signed_in):
        """
        A device signing out should not have to know whether its
        registration survived.
        """
        response = await client.request("DELETE", TOKEN_URL, json={"token": ANDROID_TOKEN})

        assert response.status_code == 200
        assert response.json() == {"registered": False, "token_count": 0}

    async def test_removal_requires_authentication(self, client, user):
        client.cookies.clear()

        response = await client.request("DELETE", TOKEN_URL, json={"token": ANDROID_TOKEN})

        assert response.status_code == 401


class TestStatus:
    async def test_reports_no_registration(self, client, signed_in):
        response = await client.get(TOKEN_URL)

        assert response.status_code == 200
        assert response.json() == {"registered": False, "token_count": 0}

    async def test_reports_a_registration(self, client, signed_in):
        await client.post(TOKEN_URL, json={"token": ANDROID_TOKEN, "platform": "android"})

        response = await client.get(TOKEN_URL)

        assert response.status_code == 200
        assert response.json() == {"registered": True, "token_count": 1}

    async def test_another_users_registration_is_not_reported(self, client, signed_in, db_session):
        other = await make_user(db_session)
        db_session.add(PushToken(user_id=other.id, token=IOS_TOKEN, platform="ios"))
        await db_session.commit()

        response = await client.get(TOKEN_URL)

        assert response.json() == {"registered": False, "token_count": 0}

    async def test_status_requires_authentication(self, client, user):
        client.cookies.clear()

        response = await client.get(TOKEN_URL)

        assert response.status_code == 401


class TestIsolation:
    async def test_a_token_is_not_visible_to_another_account(self, client, signed_in, db_session):
        """One account's device must not make another account look registered."""
        await client.post(TOKEN_URL, json={"token": ANDROID_TOKEN, "platform": "android"})

        other = await make_user(db_session)
        await authenticate(client, other)

        response = await client.get(TOKEN_URL)

        assert response.json() == {"registered": False, "token_count": 0}


@pytest.fixture
def sync_repo():
    """A committed repository the sync task can pick up.

    Committed on purpose: the task opens its own session, so a row left in
    the test's transaction would be invisible to it. The owner carries a
    key, because the task refuses to sync a repository whose owner has
    none.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.security import hash_password
    from app.models.repository import Repository
    from app.models.user import User
    from tests.conftest import TEST_SYNC_DB_URL

    engine = create_engine(TEST_SYNC_DB_URL)
    session = sessionmaker(bind=engine)()

    user = User(
        email=f"push-sync-{uuid.uuid4().hex[:8]}@example.com",
        name="Push Sync User",
        password=hash_password("correct horse battery staple"),
        ai_provider="openai",
        ai_api_key="sk-test",
        ai_model="gpt-4o-mini",
    )
    session.add(user)
    session.flush()

    repo = Repository(
        user_id=user.id,
        github_url="https://github.com/example/sample-project",
        name="sample-project",
        status="ready",
        default_branch="main",
        ingested_branch="main",
        ingested_commit_sha="a" * 40,
    )
    session.add(repo)
    session.commit()
    repo_id = repo.id
    user_id = user.id
    session.close()

    yield repo_id

    session = sessionmaker(bind=engine)()
    try:
        session.query(Repository).filter(Repository.id == repo_id).delete()
        session.query(User).filter(User.id == user_id).delete()
        session.commit()
    finally:
        session.close()
        engine.dispose()


def _record_sends(monkeypatch) -> list[dict]:
    """Record the pushes the task attempts, without sending any."""
    from app.services import push as push_module

    sent: list[dict] = []

    def _record(user_id, *, title, body, data=None):
        sent.append({"title": title, "body": body, "data": data or {}})
        return True

    monkeypatch.setattr(push_module, "send_push_to_user", _record)
    return sent


class TestSyncNotifications:
    """What the sync task notifies about, and when.

    The two callers of the task are the route the user hits and the
    auto-update sweep, and they dispatch it differently. A sync the user
    asked for notifies; one the sweep picked up is silent, in both
    directions, because a repository that refreshes every six hours would
    otherwise train people to turn notifications off.
    """

    @pytest.fixture(autouse=True)
    def stubbed_sync(self, monkeypatch):
        """Replace the body of the sync so no git and no network is touched."""
        import app.tasks.sync as sync_module

        monkeypatch.setattr(
            sync_module,
            "_do_sync",
            lambda db, repo, access_token, generation, now: {"upserted": 0},
        )

    def test_a_sync_the_user_asked_for_notifies(self, sync_repo, monkeypatch):
        from app.tasks.sync import sync_repository

        sent = _record_sends(monkeypatch)

        result = sync_repository.apply(args=[str(sync_repo)])

        assert result.successful()
        assert len(sent) == 1
        assert sent[0]["data"]["event"] == "manual_sync_completed"

    def test_a_scheduled_sync_is_silent(self, sync_repo, monkeypatch):
        """The sweep hands the task the owner's token; the route does not."""
        from app.tasks.sync import sync_repository

        sent = _record_sends(monkeypatch)

        result = sync_repository.apply(args=[str(sync_repo), None])

        assert result.successful()
        assert sent == []
