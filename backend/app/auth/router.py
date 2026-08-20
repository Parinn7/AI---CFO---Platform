"""Authentication endpoints (tasks 2.2, 2.4) — signup, login, current user,
password reset.

Mounted under `{api_v1_prefix}/auth` in `app.main`. Returns a JWT the frontend
stores and sends as a Bearer token on subsequent requests (FR-1.1, FR-1.2).
Password reset (FR-1.4) has no email service wired up, so the reset link is
logged server-side and (in development only) returned in the response.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.auth.schemas import (
    LoginRequest,
    MessageResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    PasswordResetRequestResponse,
    SignupRequest,
    TokenResponse,
    UserRead,
)
from app.auth.security import create_access_token
from app.auth.service import (
    EmailAlreadyRegisteredError,
    authenticate_user,
    create_password_reset,
    create_user,
    reset_password,
)
from app.core.config import settings
from app.core.database import get_db

logger = logging.getLogger("app.auth")

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


@router.post("/password-reset/request", response_model=PasswordResetRequestResponse)
async def request_password_reset(
    data: PasswordResetRequest, db: AsyncSession = Depends(get_db)
) -> PasswordResetRequestResponse:
    """Start a password reset. Always responds identically (no account
    enumeration); the reset link is logged and, in development, returned inline
    since no email service is configured (FR-1.4)."""
    token = await create_password_reset(db, data.email)
    message = (
        "If an account exists for that email, a password reset link has been sent."
    )
    if token is None:
        return PasswordResetRequestResponse(message=message)

    reset_link = f"{settings.frontend_base_url}/reset-password?token={token}"
    # No email provider wired up — "send" the link by logging it.
    logger.info("Password reset requested for %s — link: %s", data.email, reset_link)

    if settings.environment == "development":
        return PasswordResetRequestResponse(
            message=message, reset_token=token, reset_link=reset_link
        )
    return PasswordResetRequestResponse(message=message)


@router.post("/password-reset/confirm", response_model=MessageResponse)
async def confirm_password_reset(
    data: PasswordResetConfirm, db: AsyncSession = Depends(get_db)
) -> MessageResponse:
    """Complete a password reset using a token from the request step."""
    if not await reset_password(db, data.token, data.new_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This password reset link is invalid or has expired.",
        )
    return MessageResponse(message="Your password has been reset. You can now log in.")
