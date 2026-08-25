from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas import (
    LoginRequest, RefreshRequest, TokenResponse, AccessTokenResponse, UserResponse, DataResponse,
)
from app.security import verify_password
from shared.auth.jwt_tokens import create_access_token, create_refresh_token, decode_token, TokenError
from shared.auth.config import JWT_EXPIRY_MINUTES
from shared.auth.middleware import get_current_user, CurrentUser

router = APIRouter()


@router.post("/login", response_model=DataResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalars().first()
    if user is None or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="invalid email or password")

    access_token = create_access_token(user.id, user.email, user.role)
    refresh_token = create_refresh_token(user.id, user.email, user.role)
    return DataResponse(
        data=TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in_minutes=JWT_EXPIRY_MINUTES,
        )
    )


@router.post("/refresh", response_model=DataResponse)
async def refresh(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        claims = decode_token(data.refresh_token)
    except TokenError as e:
        raise HTTPException(status_code=401, detail=str(e))
    if claims.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="not a refresh token")

    # Re-fetch the user so a role change or deactivation between issuance
    # and refresh is honored rather than trusting stale token claims.
    result = await db.execute(select(User).where(User.id == claims["sub"]))
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status_code=401, detail="user no longer exists")

    access_token = create_access_token(user.id, user.email, user.role)
    return DataResponse(
        data=AccessTokenResponse(access_token=access_token, expires_in_minutes=JWT_EXPIRY_MINUTES)
    )


@router.get("/me", response_model=DataResponse)
async def me(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status_code=401, detail="user no longer exists")
    return DataResponse(data=UserResponse.model_validate(user))
