"""Email/password and GitHub OAuth authentication routes.

Handles user registration, login/logout via httponly session cookies,
current-user lookup, the GitHub OAuth code-exchange flow that links
a GitHub account and stores its access token, and the per-user AI
credential store (BYOK provider/key/model) with a save-time probe.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
)
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.validation import FreeText
from app.core.config import settings
from app.core.database import get_async_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.services.entitlements import FREE_CHAT_MESSAGES, FREE_INGESTIONS
from app.services.llm_config import LLMConfig
from app.services.llm_providers import PROVIDERS, get_provider, suggest_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    """Registration payload with basic length validation."""

    email: EmailStr
    name: FreeText = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    """Email/password login payload."""

    email: EmailStr
    password: str


class MessageResponse(BaseModel):
    """Generic success message envelope."""

    message: str


class UserResponse(BaseModel):
    """Public user profile returned by the /me endpoint.

    The GitHub fields are optional because they are only populated once the account has
    been linked through OAuth; a user who registered with an email and password has None
    for all of them. Declaring them as required made response validation fail for those
    users and turned /me into a 500.

    The AI credential fields and free-tier counters are flattened onto the same
    envelope so a single ``GET /auth/me`` call feeds the navbar, the settings page
    and the chat quota display -- three components today, all reading the same
    shape. ``has_ai_key`` is the boolean the UI actually renders; the raw key is
    never returned.
    """

    id: uuid.UUID
    email: str
    name: str
    avatar_url: str | None = None
    github_id: str | None = None
    ai_provider: str | None = None
    ai_model: str | None = None
    has_ai_key: bool = False
    free_ingestions_used: int = 0
    free_chat_messages_used: int = 0
    free_ingestions_limit: int = FREE_INGESTIONS
    free_chat_messages_limit: int = FREE_CHAT_MESSAGES

    model_config = ConfigDict(from_attributes=True)


@router.post("/register", response_model=MessageResponse, status_code=201)
async def register(
    body: RegisterRequest, response: Response, db: AsyncSession = Depends(get_async_db)
):
    """Register a new user and set the session cookie.

    Args:
        body: Registration payload with email, name, and password.
        response: Response used to set the httponly session cookie.
        db: Async database session.

    Returns:
        Success message confirming registration.

    Raises:
        HTTPException: 400 if the email is already registered.
    """
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=body.email,
        name=body.name,
        password=hash_password(body.password),
        github_access_token=None,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(subject=str(user.id))
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.ENVIRONMENT == "production",
        domain=settings.DOMAIN,
    )
    return MessageResponse(message="Registered successfully")


@router.post("/login", response_model=MessageResponse)
async def login(body: LoginRequest, response: Response, db: AsyncSession = Depends(get_async_db)):
    """Authenticate a user and set the session cookie.

    Args:
        body: Login payload with email and password.
        response: Response used to set the httponly session cookie.
        db: Async database session.

    Returns:
        Success message confirming login.

    Raises:
        HTTPException: 401 if credentials are invalid.
    """
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(subject=str(user.id))
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.ENVIRONMENT == "production",
        domain=settings.DOMAIN,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    return MessageResponse(message="Logged in successfully")


@router.post("/logout", response_model=MessageResponse)
async def logout(response: Response):
    """Clear the session cookie.

    Args:
        response: Response used to delete the session cookie.

    Returns:
        Success message confirming logout.
    """
    response.delete_cookie(
        key="access_token",
        httponly=True,
        samesite="lax",
        secure=settings.ENVIRONMENT == "production",
        domain=settings.DOMAIN,
    )
    return MessageResponse(message="Logged out successfully")


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user.

    The response is built explicitly rather than returned from the row,
    because ``has_ai_key`` is a derived boolean (``ai_api_key`` is the
    raw column) and pydantic's ``from_attributes`` only fills declared
    fields from matching attributes -- it does not invent a ``has_ai_key``
    getter from the ``ai_api_key`` column.

    Args:
        current_user: User resolved by the auth dependency.

    Returns:
        The current user's profile.
    """
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        avatar_url=current_user.avatar_url,
        github_id=current_user.github_id,
        ai_provider=current_user.ai_provider,
        ai_model=current_user.ai_model,
        has_ai_key=bool(current_user.ai_api_key),
        free_ingestions_used=current_user.free_ingestions_used,
        free_chat_messages_used=current_user.free_chat_messages_used,
        free_ingestions_limit=FREE_INGESTIONS,
        free_chat_messages_limit=FREE_CHAT_MESSAGES,
    )


@router.get("/github")
async def github_login(state: str | None = None):
    """Redirect to GitHub's OAuth authorization page.

    Args:
        state: Caller-supplied opaque value that GitHub echoes back on the
            callback. The mobile app uses this to carry a deep-link URI;
            :func:`_select_redirect_target` validates it against
            ``settings.OAUTH_REDIRECT_ALLOWLIST`` once the code arrives.
            Anything not on the list is silently coerced to ``FRONTEND_URL``,
            so a state that starts out as a near-miss is no worse than no
            state at all.

    Returns:
        Redirect to GitHub with client ID, redirect URI, scopes, and the
        echoed ``state``.
    """
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": settings.GITHUB_REDIRECT_URL,
        "scope": "user:email repo",
    }
    if state:
        params["state"] = state
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(f"https://github.com/login/oauth/authorize?{query}")


def _select_redirect_target(redirect_uri: str | None) -> str:
    """Return the post-auth redirect target, allowlisting ``redirect_uri``.

    Args:
        redirect_uri: Caller-supplied override, or ``None`` for the default.

    Returns:
        ``settings.FRONTEND_URL`` by default; ``redirect_uri`` exactly when it
        appears in ``settings.OAUTH_REDIRECT_ALLOWLIST``. Anything not on the
        list -- including a near miss -- falls back to ``FRONTEND_URL``.

    Note:
        No prefix matching, per the open-redirect guidance. The allowlist is
        the only thing that gets trusted, and only verbatim.
    """
    if redirect_uri is None:
        return settings.FRONTEND_URL
    if redirect_uri in settings.OAUTH_REDIRECT_ALLOWLIST:
        return redirect_uri
    return settings.FRONTEND_URL


def _is_mobile_client(request_headers) -> bool:
    """Return True when the caller opts in to the native auth contract.

    Args:
        request_headers: An iterable of header tuples (or a mapping) that
            supports ``.get`` on lowercase keys.

    Returns:
        ``True`` only when the header is present and matches the documented
        value. Any other value (including a near-miss string) is treated as a
        web caller.
    """
    if hasattr(request_headers, "get"):
        value = request_headers.get("x-illume-client")
    else:
        value = next(
            (v for k, v in request_headers if k.lower() == "x-illume-client"),
            None,
        )
    return value == "mobile"


async def _exchange_github_code(code: str, redirect_uri: str) -> tuple[str, dict, list]:
    """Exchange an OAuth code for a GitHub access token, the user profile, and emails.

    Args:
        code: The OAuth code returned by GitHub.
        redirect_uri: The redirect_uri that was used to start the flow. Must
            match what was passed to GitHub or the exchange is rejected.

    Returns:
        ``(github_token, github_user, emails)``: the raw GitHub access token,
        the ``/user`` profile body, and the list of email records. The caller
        stores the first argument on the linked ``User`` row and picks the
        verified primary email out of the third.

    Raises:
        HTTPException: 400 if GitHub does not return an access token.
    """
    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        token_data = token_res.json()

    github_token = token_data.get("access_token")
    if not github_token:
        raise HTTPException(status_code=400, detail="GitHub auth failed")

    async with httpx.AsyncClient() as client:
        user_res = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {github_token}"},
        )
        github_user = user_res.json()

        email_res = await client.get(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {github_token}"},
        )
        emails = email_res.json()

    return github_token, github_user, emails


@router.get("/github/callback")
async def github_callback(
    code: str,
    response: Response,
    request: Request,
    state: str | None = None,
    db: AsyncSession = Depends(get_async_db),
):
    """Complete GitHub OAuth and link the GitHub account.

    Exchanges the OAuth code for an access token, fetches the GitHub
    profile and verified primary email, then creates or links the local
    user and sets the session cookie.

    Args:
        code: OAuth authorization code from GitHub.
        response: The raw ASGI response -- currently unused; cookie state is
            attached to whatever redirect shape the call resolves to.
        request: Used to read ``X-Illume-Client`` and any caller-supplied
            headers.
        state: Echoed from the ``/github`` call. When on the allowlist, the
            callback redirects to this deep link instead of ``FRONTEND_URL``;
            anything else is coerced to ``FRONTEND_URL`` (see
            :func:`_select_redirect_target`).
        db: Async database session.

    Returns:
        For web callers, the byte-identical ``RedirectResponse`` to
        ``FRONTEND_URL`` with the session cookie attached.

        For native callers (``X-Illume-Client: mobile``), the access token
        in the response body so a deep-link return path can store it; the
        cookie is still set for parity. The response shape differs across
        these two contracts, by design -- web clients never see the token.

    Raises:
        HTTPException: 400 if token exchange fails or no verified email exists.
    """
    github_token, github_user, emails = await _exchange_github_code(
        code, settings.GITHUB_REDIRECT_URL
    )

    # Pick the verified primary email; GitHub may return several addresses.
    primary_email = next(
        (e["email"] for e in emails if e["primary"] and e["verified"]),
        None,
    )
    if not primary_email:
        raise HTTPException(status_code=400, detail="No verified email on GitHub account")

    github_id = str(github_user["id"])

    result = await db.execute(select(User).where(User.github_id == github_id))
    user = result.scalar_one_or_none()

    # Fall back to email matching so an existing password account gets linked
    # to GitHub instead of creating a duplicate user.
    if not user:
        result = await db.execute(select(User).where(User.email == primary_email))
        user = result.scalar_one_or_none()

    is_mobile = _is_mobile_client(request.headers)
    is_deep_link_state = state is not None and state in settings.OAUTH_REDIRECT_ALLOWLIST
    # Deep-link callers are native by definition: the only path that lands a
    # deep link in ``state`` is the mobile login button, so its token must be
    # the long-lived one. Web callers without a header get the short expiry.
    expires_minutes = (
        settings.MOBILE_TOKEN_EXPIRE_MINUTES
        if is_mobile or is_deep_link_state
        else settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )

    if user:
        user.github_id = github_id
        user.github_access_token = github_token
        user.avatar_url = github_user.get("avatar_url")
    else:
        user = User(
            email=primary_email,
            name=github_user.get("name") or github_user.get("login"),
            password=None,
            github_id=github_id,
            github_access_token=github_token,
            avatar_url=github_user.get("avatar_url"),
        )
        db.add(user)

    await db.commit()
    await db.refresh(user)

    is_deep_link = state is not None and state in settings.OAUTH_REDIRECT_ALLOWLIST
    token = create_access_token(
        subject=str(user.id),
        expires_delta=timedelta(minutes=expires_minutes),
    )

    if is_mobile and not is_deep_link:
        # Native callers without a deep-link state asked for a JSON token in
        # the response body (no cookie jar in this flow). The deep-link
        # path below covers the common case; this branch is here for
        # callers that hit the callback directly with the header and no
        # cookie.
        return JSONResponse(
            {
                "access_token": token,
                "token_type": "Bearer",
                "expires_in": expires_minutes * 60,
                "redirect_uri": settings.FRONTEND_URL,
            }
        )

    if is_deep_link:
        # The whole flow ran in a system browser, so we have no header and
        # no cookie jar. Bundle the token into the redirect target so the
        # native deep-link handler can pick it up. The plan flags this as a
        # known exposure (token-in-URL) acceptable for the resume build.
        from urllib.parse import urlencode, urlparse, urlunparse

        target = _select_redirect_target(state)
        parsed = urlparse(target)
        query = {
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": str(expires_minutes * 60),
        }
        target_with_token = urlunparse(parsed._replace(query=urlencode(query)))
        return RedirectResponse(url=target_with_token, status_code=302)

    target = _select_redirect_target(state)
    redirect = RedirectResponse(url=target, status_code=302)
    redirect.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.ENVIRONMENT == "production",
        domain=settings.DOMAIN,
        max_age=expires_minutes * 60,
    )

    return redirect


# --- AI credentials (BYOK) --------------------------------------------------
#
# Three endpoints on the same ``/me`` namespace as ``/auth/me`` so the client
# already has the route shape cached. The save flow probes the credential before
# it writes -- a half-saved key is worse than no key, because the next ingestion
# would 401 mid-pipeline and leave the user without a free allowance either.


# Provider keys we accept. Anything else is a 422. The list is what the user
# sees as the picker options; the registry (``app.services.llm_providers``)
# is the source of truth for the matching base URL and default model.
_ALLOWED_PROVIDER_KEYS: tuple[str, ...] = tuple(PROVIDERS.keys())


class AICredentialsResponse(BaseModel):
    """Public view of the user's saved AI credential.

    Never the key. ``validated_at`` is the timestamp of the last successful
    probe -- the client renders it so a user can tell a key that has been
    working for a year from one that was never tested.
    """

    provider: str | None = None
    model: str | None = None
    has_key: bool = False
    validated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class AICredentialsPutRequest(BaseModel):
    """Payload for saving or replacing the user's AI credential.

    ``api_key`` is the raw value the user pastes into the form. The route
    probes it before persisting -- see :func:`_probe_credentials`.
    """

    provider: str
    api_key: str = Field(min_length=8, max_length=512)
    model: FreeText


def _provider_mismatch_hint(provider: str, api_key: str, model: str) -> str:
    """Build the "wrong provider selected" half of a probe failure message.

    A rejected key is the most common way a user discovers they left the
    Provider field on its previous value: the key and model they pasted both
    belong to a different preset, and the bare failure text names only the
    provider that refused them. The hint names the preset the evidence points
    at, so the fix ("change the Provider field") is in the message rather than
    something the user has to infer from a 400.

    Args:
        provider: The preset the user selected.
        api_key: The submitted credential.
        model: The submitted model id.

    Returns:
        A leading-space sentence to append to a failure detail, or an empty
        string when the submitted values look consistent with the selection --
        that case is a genuinely wrong key, and guessing a provider for it
        would be noise.
    """
    suggestion = suggest_provider(provider, model=model, api_key=api_key)
    if suggestion is None:
        return ""

    suggested, reason = suggestion
    evidence = (
        f"{model!r} is {suggested.label}'s default model."
        if reason == "model"
        else f"That key looks like a {suggested.label} key."
    )
    return f" {evidence} If you meant to use {suggested.label}, change the Provider field."


async def _probe_credentials(provider: str, api_key: str, model: str) -> None:
    """Issue a 16-token ``responses.create`` to confirm the credential works.

    Uses the same :class:`LLMConfig` shape the four generation services use,
    so an incompatible combination of provider/model/reasoning-support is
    caught at the form rather than as silently empty artefacts later.

    The route layer is responsible for rejecting unknown providers with a
    422 before this is called -- see :func:`put_ai_credentials`. Keeping
    the validation in one place means the helper can ``get_provider``
    without catching ``KeyError`` and re-raising as ``HTTPException``.

    Args:
        provider: A key into :data:`app.services.llm_providers.PROVIDERS`.
            Must be a known preset.
        api_key: The user-supplied credential.
        model: The user-supplied model id.

    Raises:
        HTTPException: 400 with a provider-specific message on failure. The
            caller is responsible for *not* persisting anything when this
            raises -- the half-saved case is the one the test pins.
    """
    preset = get_provider(provider)

    config = LLMConfig(
        api_key=api_key,
        model=model,
        base_url=preset.base_url,
        supports_reasoning=preset.supports_reasoning,
        source="user",
    )

    # ``timeout=15`` bounds the wait; ``max_retries=0`` so a transient failure
    # surfaces immediately rather than retrying past the user's patience. The
    # 16-token cap mirrors the documentation: enough text to confirm the key
    # is accepted, short enough to be cheap even on a failing provider.
    client = AsyncOpenAI(timeout=15, max_retries=0, **config.client_kwargs())

    try:
        await client.responses.create(
            model=model,
            **config.response_kwargs("minimal"),
            input="ping",
            max_output_tokens=16,
        )
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Incorrect API key for {preset.label}."
                f"{_provider_mismatch_hint(provider, api_key, model)}"
            ),
        ) from exc
    except APIStatusError as exc:
        # The SDK uses status errors for any 4xx/5xx response other than
        # auth -- 404 from a provider that doesn't have the requested model
        # is the common case the plan calls out.
        raise HTTPException(
            status_code=400,
            detail=(
                f"That model isn't available on {preset.label}."
                f"{_provider_mismatch_hint(provider, api_key, model)}"
            ),
        ) from exc
    except (APIConnectionError, APITimeoutError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not reach {preset.label}.",
        ) from exc


@router.get("/me/ai-credentials", response_model=AICredentialsResponse)
async def get_ai_credentials(current_user: User = Depends(get_current_user)):
    """Return the current user's saved AI credential, if any.

    Always 200, even when no credential is saved -- the settings page needs
    to render the unconfigured state, and a 404 would force a separate
    query to tell "no key" from "not signed in".

    Args:
        current_user: User resolved by the auth dependency.

    Returns:
        The provider, model, and ``has_key`` flag (never the key itself).
    """
    return AICredentialsResponse(
        provider=current_user.ai_provider,
        model=current_user.ai_model,
        has_key=bool(current_user.ai_api_key),
        validated_at=current_user.ai_key_validated_at,
    )


@router.put("/me/ai-credentials", response_model=AICredentialsResponse)
async def put_ai_credentials(
    body: AICredentialsPutRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """Probe a new credential, then persist it on success.

    The probe runs first and **before** any column is touched. A probe
    failure raises a 400 without writing anything, so a bad key never
    strands the user's existing setup or burns the free allowance with
    a stale half-written row.

    Args:
        body: Provider key, raw API key, and model id from the form.
        db: Async database session.
        current_user: User resolved by the auth dependency.

    Returns:
        The newly saved credential, in the same shape as ``GET``.

    Raises:
        HTTPException: 422 if the provider is unknown; 400 with the
            provider's label on a probe failure.
    """
    if body.provider not in _ALLOWED_PROVIDER_KEYS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown provider: {body.provider!r}. Choose one of {_ALLOWED_PROVIDER_KEYS}.",
        )

    # Probe first; persist only on success.
    await _probe_credentials(body.provider, body.api_key, body.model)

    current_user.ai_provider = body.provider
    current_user.ai_api_key = body.api_key
    current_user.ai_model = body.model
    current_user.ai_key_validated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(current_user)

    return AICredentialsResponse(
        provider=current_user.ai_provider,
        model=current_user.ai_model,
        has_key=bool(current_user.ai_api_key),
        validated_at=current_user.ai_key_validated_at,
    )


@router.delete("/me/ai-credentials", response_model=AICredentialsResponse)
async def delete_ai_credentials(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """Clear the saved credential.

    Existing artefacts (glossary, reading order, embeddings, brief) survive
    -- they were generated and persisted independently of the key. The free
    allowance does not come back: the counters (``free_ingestions_used``,
    ``free_chat_messages_used``) are untouched, so a user who deletes their
    key still cannot re-ingest or ask another ten questions.

    Args:
        db: Async database session.
        current_user: User resolved by the auth dependency.

    Returns:
        The cleared credential envelope (all None, ``has_key=False``).
    """
    current_user.ai_provider = None
    current_user.ai_api_key = None
    current_user.ai_model = None
    current_user.ai_key_validated_at = None
    await db.commit()
    await db.refresh(current_user)

    return AICredentialsResponse(
        provider=None,
        model=None,
        has_key=False,
        validated_at=None,
    )
