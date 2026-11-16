"""The MCP token service against a real database.

Covers minting, the one way a token becomes a user, and the throttle on
``last_used_at``. The route-level behaviour is in ``test_mcp_tokens_api.py``.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time
from sqlalchemy import select

from app.models.mcp_token import McpToken
from app.services.mcp_tokens import (
    LAST_USED_THROTTLE,
    MAX_TOKENS_PER_USER,
    TOKEN_PREFIX,
    TokenLimitError,
    TokenNotFoundError,
    create_token,
    hash_token,
    list_tokens,
    resolve_token,
    revoke_token,
)
from tests.factories import make_user

pytestmark = pytest.mark.integration

START = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)


async def _fresh(db_session, token_id) -> McpToken:
    result = await db_session.execute(
        select(McpToken).where(McpToken.id == token_id).execution_options(populate_existing=True)
    )
    return result.scalar_one()


class TestCreate:
    async def test_the_plaintext_has_the_prefix_and_enough_length(self, db_session):
        user = await make_user(db_session)

        _, plaintext = await create_token(db_session, user.id, "laptop", 90)

        assert plaintext.startswith(TOKEN_PREFIX)
        assert len(plaintext) >= len(TOKEN_PREFIX) + 43

    async def test_only_the_hash_and_a_display_prefix_are_stored(self, db_session):
        user = await make_user(db_session)

        token, plaintext = await create_token(db_session, user.id, "laptop", None)

        assert token.token_hash == hash_token(plaintext)
        assert token.token_prefix == plaintext[len(TOKEN_PREFIX) :][:8]
        assert token.expires_at is None

    async def test_expiry_is_counted_from_now(self, db_session):
        user = await make_user(db_session)

        token, _ = await create_token(db_session, user.id, "laptop", 30)

        remaining = token.expires_at - datetime.now(UTC)
        assert timedelta(days=29, hours=23) < remaining <= timedelta(days=30)

    async def test_a_thousand_draws_never_collide(self):
        # The generator the service uses; the database is not needed to see a
        # collision, and the per-user cap would stop a real run at ten.
        drawn = {TOKEN_PREFIX + secrets.token_urlsafe(32) for _ in range(1000)}

        assert len(drawn) == 1000
        assert len({hash_token(token) for token in drawn}) == 1000

    async def test_the_cap_counts_only_active_tokens(self, db_session):
        user = await make_user(db_session)
        first, _ = await create_token(db_session, user.id, "t0", 90)
        for index in range(1, MAX_TOKENS_PER_USER):
            await create_token(db_session, user.id, f"t{index}", 90)

        with pytest.raises(TokenLimitError):
            await create_token(db_session, user.id, "one too many", 90)

        await revoke_token(db_session, user.id, first.id)
        await create_token(db_session, user.id, "fits again", 90)

    async def test_the_cap_is_per_user(self, db_session):
        owner, other = await make_user(db_session), await make_user(db_session)
        for index in range(MAX_TOKENS_PER_USER):
            await create_token(db_session, owner.id, f"t{index}", 90)

        await create_token(db_session, other.id, "mine", 90)


class TestResolve:
    async def test_a_valid_token_resolves_to_its_owner(self, db_session):
        user = await make_user(db_session)
        _, plaintext = await create_token(db_session, user.id, "laptop", 90)

        resolved = await resolve_token(db_session, plaintext)

        assert resolved is not None
        assert resolved.id == user.id

    async def test_a_revoked_token_is_rejected(self, db_session):
        user = await make_user(db_session)
        token, plaintext = await create_token(db_session, user.id, "laptop", 90)
        assert await resolve_token(db_session, plaintext) is not None

        await revoke_token(db_session, user.id, token.id)

        assert await resolve_token(db_session, plaintext) is None

    async def test_an_expired_token_is_rejected(self, db_session):
        user = await make_user(db_session)
        _, plaintext = await create_token(db_session, user.id, "laptop", 30)
        later = datetime.now(UTC) + timedelta(days=31)

        with freeze_time(later, real_asyncio=True):
            assert await resolve_token(db_session, plaintext) is None

    async def test_a_token_is_valid_until_it_expires(self, db_session):
        user = await make_user(db_session)
        _, plaintext = await create_token(db_session, user.id, "laptop", 30)
        before = datetime.now(UTC) + timedelta(days=29)

        with freeze_time(before, real_asyncio=True):
            assert await resolve_token(db_session, plaintext) is not None

    async def test_an_unknown_token_is_rejected(self, db_session):
        assert await resolve_token(db_session, TOKEN_PREFIX + secrets.token_urlsafe(32)) is None

    @pytest.mark.parametrize(
        "presented",
        [
            "",
            "ilm_",
            "ilm_short",
            "no-prefix-" + "a" * 43,
            "ILM_" + "a" * 43,
            "ilm_" + "a" * 42,
            "ilm_" + "a" * 44,
            "ilm_" + "a" * 42 + "!",
            "ilm_" + "a" * 42 + " ",
            "ilm_" + "a" * 42 + "\n",
            "Bearer ilm_" + "a" * 43,
        ],
    )
    async def test_a_malformed_token_is_rejected(self, db_session, presented):
        assert await resolve_token(db_session, presented) is None

    async def test_a_session_jwt_is_not_a_token(self, db_session):
        from app.core.security import create_access_token

        user = await make_user(db_session)

        assert await resolve_token(db_session, create_access_token(str(user.id))) is None

    async def test_a_token_whose_row_is_gone_is_rejected(self, db_session):
        user = await make_user(db_session)
        token, plaintext = await create_token(db_session, user.id, "laptop", 90)
        await db_session.delete(token)
        await db_session.commit()

        assert await resolve_token(db_session, plaintext) is None


class TestLastUsed:
    async def test_the_first_use_sets_it(self, db_session):
        user = await make_user(db_session)
        token, plaintext = await create_token(db_session, user.id, "laptop", None)
        assert token.last_used_at is None

        with freeze_time(START, real_asyncio=True):
            await resolve_token(db_session, plaintext)

        assert (await _fresh(db_session, token.id)).last_used_at == START

    async def test_a_second_use_within_the_minute_does_not_move_it(self, db_session):
        user = await make_user(db_session)
        token, plaintext = await create_token(db_session, user.id, "laptop", None)
        with freeze_time(START, real_asyncio=True):
            await resolve_token(db_session, plaintext)

        inside = START + LAST_USED_THROTTLE - timedelta(seconds=1)
        with freeze_time(inside, real_asyncio=True):
            assert await resolve_token(db_session, plaintext) is not None

        assert (await _fresh(db_session, token.id)).last_used_at == START

    async def test_a_use_after_the_minute_moves_it(self, db_session):
        user = await make_user(db_session)
        token, plaintext = await create_token(db_session, user.id, "laptop", None)
        with freeze_time(START, real_asyncio=True):
            await resolve_token(db_session, plaintext)

        later = START + LAST_USED_THROTTLE + timedelta(seconds=1)
        with freeze_time(later, real_asyncio=True):
            await resolve_token(db_session, plaintext)

        assert (await _fresh(db_session, token.id)).last_used_at == later

    async def test_a_rejected_token_never_records_a_use(self, db_session):
        user = await make_user(db_session)
        token, plaintext = await create_token(db_session, user.id, "laptop", None)
        await revoke_token(db_session, user.id, token.id)

        await resolve_token(db_session, plaintext)

        assert (await _fresh(db_session, token.id)).last_used_at is None


class TestListAndRevoke:
    async def test_list_omits_revoked_and_expired_tokens_and_other_users(self, db_session):
        user, other = await make_user(db_session), await make_user(db_session)
        kept, _ = await create_token(db_session, user.id, "kept", 90)
        gone, _ = await create_token(db_session, user.id, "gone", 90)
        expired, _ = await create_token(db_session, user.id, "expired", 30)
        await create_token(db_session, other.id, "theirs", 90)
        await revoke_token(db_session, user.id, gone.id)
        expired.expires_at = datetime.now(UTC) - timedelta(days=1)
        await db_session.commit()

        listed = await list_tokens(db_session, user.id)

        assert [token.id for token in listed] == [kept.id]

    async def test_revoking_twice_keeps_the_first_timestamp(self, db_session):
        user = await make_user(db_session)
        token, _ = await create_token(db_session, user.id, "laptop", 90)
        await revoke_token(db_session, user.id, token.id)
        first = (await _fresh(db_session, token.id)).revoked_at

        await revoke_token(db_session, user.id, token.id)

        assert first is not None
        assert (await _fresh(db_session, token.id)).revoked_at == first

    async def test_revoking_another_users_token_is_not_found_and_changes_nothing(self, db_session):
        owner, intruder = await make_user(db_session), await make_user(db_session)
        token, _ = await create_token(db_session, owner.id, "laptop", 90)

        with pytest.raises(TokenNotFoundError):
            await revoke_token(db_session, intruder.id, token.id)

        assert (await _fresh(db_session, token.id)).revoked_at is None
