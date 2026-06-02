import uuid

import httpx
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_async_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class MessageResponse(BaseModel):
    message: str


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    avatar_url: str
    github_id: str
    github_access_token: str

    model_config = ConfigDict(from_attributes=True)


@router.post("/register", response_model=MessageResponse, status_code=201)
async def register(
    body: RegisterRequest, response: Response, db: AsyncSession = Depends(get_async_db)
):
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
async def login(
    body: LoginRequest, response: Response, db: AsyncSession = Depends(get_async_db)
):
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
    )
    return MessageResponse(message="Logged in successfully")


@router.post("/logout", response_model=MessageResponse)
async def logout(response: Response):
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
    return current_user


@router.get("/github")
async def github_login():
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": settings.GITHUB_REDIRECT_URL,
        "scope": "user:email repo",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(f"https://github.com/login/oauth/authorize?{query}")


@router.get("/github/callback")
async def github_callback(
    code: str,
    response: Response,
    db: AsyncSession = Depends(get_async_db),
):
    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": settings.GITHUB_REDIRECT_URL,
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
        print("STATUS:", email_res.status_code)
        print("BODY:", emails)

    primary_email = next(
        (e["email"] for e in emails if e["primary"] and e["verified"]),
        None,
    )
    if not primary_email:
        raise HTTPException(
            status_code=400, detail="No verified email on GitHub account"
        )

    github_id = str(github_user["id"])

    result = await db.execute(select(User).where(User.github_id == github_id))
    user = result.scalar_one_or_none()

    if not user:
        result = await db.execute(select(User).where(User.email == primary_email))
        user = result.scalar_one_or_none()

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

    redirect = RedirectResponse(url=settings.FRONTEND_URL, status_code=302)
    token = create_access_token(subject=str(user.id))
    redirect.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.ENVIRONMENT == "production",
        domain=settings.DOMAIN,
    )

    return redirect
