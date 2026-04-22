from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_password,
    verify_token,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limiter import limiter
from app.models.user import User

router = APIRouter()


class RegisterBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class UserPublic(BaseModel):
    user_id: str
    email: str
    tier: str


def _is_secure() -> bool:
    if settings.COOKIES_SECURE is not None:
        return settings.COOKIES_SECURE
    return settings.ENVIRONMENT != "development"


def _set_auth_cookies(response: Response, user_id):
    access = create_access_token(user_id)
    refresh = create_refresh_token(user_id)
    secure = _is_secure()
    response.set_cookie(
        "access_token",
        access,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=secure,
        samesite="lax",
    )
    response.set_cookie(
        "refresh_token",
        refresh,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        httponly=True,
        secure=secure,
        samesite="lax",
    )


@router.post("/register", response_model=UserPublic, status_code=201)
@limiter.limit("5/minute")
async def register(request: Request, body: RegisterBody, response: Response, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="email already registered")
    user = User(email=body.email, hashed_password=get_password_hash(body.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    _set_auth_cookies(response, user.id)
    return UserPublic(user_id=str(user.id), email=user.email, tier=user.tier)


@router.post("/login", response_model=UserPublic)
@limiter.limit("10/minute")
async def login(request: Request, body: LoginBody, response: Response, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not user.hashed_password or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="invalid credentials")
    _set_auth_cookies(response, user.id)
    return UserPublic(user_id=str(user.id), email=user.email, tier=user.tier)


@router.post("/refresh")
async def refresh(response: Response, refresh_token: Optional[str] = Cookie(default=None)):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="missing refresh token")
    payload = verify_token(refresh_token, expected_type="refresh")
    from uuid import UUID

    user_id = UUID(payload["sub"])
    access = create_access_token(user_id)
    response.set_cookie(
        "access_token",
        access,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=_is_secure(),
        samesite="lax",
    )
    return {"message": "refreshed"}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return {"message": "logged out"}
