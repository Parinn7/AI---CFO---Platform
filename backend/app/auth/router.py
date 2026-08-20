"""Authentication endpoints (task 2.2) — signup, login, current user.

Mounted under `{api_v1_prefix}/auth` in `app.main`. Returns a JWT the frontend
stores and sends as a Bearer token on subsequent requests (FR-1.1, FR-1.2).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.auth.schemas import LoginRequest, SignupRequest, TokenResponse, UserRead
from app.auth.security import create_access_token
from app.auth.service import (
    EmailAlreadyRegisteredError,
    authenticate_user,
    create_user,
)
from app.core.database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(subject=str(user.id)),
        user=UserRead.model_validate(user),
    )


@router.post(
    "/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED
)
async def signup(
    data: SignupRequest, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    """Register a new user and return an access token (auto-login)."""
    try:
        user = await create_user(db, data)
    except EmailAlreadyRegisteredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )
    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    data: LoginRequest, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    """Authenticate credentials and return an access token."""
    user = await authenticate_user(db, data.email, data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )
    return _token_response(user)


@router.get("/me", response_model=UserRead)
async def read_current_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Return the profile of the currently authenticated user."""
    return current_user
