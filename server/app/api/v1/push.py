"""Device push-token registration routes.

The native app registers the Expo push token of each device it runs on, and
asks here whether it has already done so. The server owns the tokens: the
client cannot be trusted to keep a registry in step with itself across
reinstalls, sign-outs, and the account a device is signed in to changing.

The routes are deliberately thin. They validate the token, store it, and
report what is registered -- the decision about *when* a device is actually
notified belongs to :mod:`app.services.push`, which is the only place that
knows the difference between a sync the user asked for and one the
auto-update sweep picked up.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.validation import FreeText
from app.core.database import get_async_db
from app.models.user import User
from app.services.push import (
    list_push_tokens,
    register_push_token,
    remove_push_token,
)

router = APIRouter(prefix="/api/v1/push", tags=["push"])


class PushTokenRequest(BaseModel):
    """A device registering its push token.

    The token's shape is not pinned to Expo's ``ExponentPushToken[...]``
    format: the value is opaque to the server, and a future client talking
    to a different push provider would be rejected by a shape check for no
    benefit. The bounds are what matter -- an unbounded token would be an
    unbounded row, and a token with a control character in it is not a
    token at all.
    """

    token: FreeText = Field(min_length=1, max_length=512)
    platform: Literal["android", "ios"]


class PushTokenRemovalRequest(BaseModel):
    """A device removing its push token, as it does when it signs out."""

    token: FreeText = Field(min_length=1, max_length=512)


class PushTokenStatusResponse(BaseModel):
    """What the signed-in user has registered."""

    registered: bool
    token_count: int


@router.post("/token", response_model=PushTokenStatusResponse)
async def register_token(
    payload: PushTokenRequest,
    db: Annotated[AsyncSession, Depends(get_async_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> PushTokenStatusResponse:
    """Register or refresh the push token of the calling user's device.

    Registering the same token twice refreshes the stored row rather than
    adding a second one, so a client that registers on every launch does not
    fill the table with copies of itself.

    Args:
        payload: The device's token and platform.
        db: Async database session.
        current_user: The signed-in user.

    Returns:
        The user's registration state after the call.
    """
    await register_push_token(
        db,
        user_id=current_user.id,
        token=payload.token,
        platform=payload.platform,
    )
    tokens = await list_push_tokens(db, user_id=current_user.id)
    return PushTokenStatusResponse(registered=bool(tokens), token_count=len(tokens))


@router.delete("/token", response_model=PushTokenStatusResponse)
async def delete_token(
    payload: PushTokenRemovalRequest,
    db: Annotated[AsyncSession, Depends(get_async_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> PushTokenStatusResponse:
    """Remove one of the calling user's push tokens.

    Only the named token is removed, and only when it belongs to the caller.
    Removing a token that is not registered is not an error: a device
    signing out should not have to know whether its registration survived.

    Args:
        payload: The token to remove.
        db: Async database session.
        current_user: The signed-in user.

    Returns:
        The user's registration state after the call.
    """
    await remove_push_token(db, user_id=current_user.id, token=payload.token)
    tokens = await list_push_tokens(db, user_id=current_user.id)
    return PushTokenStatusResponse(registered=bool(tokens), token_count=len(tokens))


@router.get("/token", response_model=PushTokenStatusResponse)
async def get_token_status(
    db: Annotated[AsyncSession, Depends(get_async_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> PushTokenStatusResponse:
    """Report whether the calling user has any registered device.

    Args:
        db: Async database session.
        current_user: The signed-in user.

    Returns:
        The user's registration state.
    """
    tokens = await list_push_tokens(db, user_id=current_user.id)
    return PushTokenStatusResponse(registered=bool(tokens), token_count=len(tokens))
