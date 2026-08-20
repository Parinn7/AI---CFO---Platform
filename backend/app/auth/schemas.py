"""Pydantic request/response schemas for authentication (task 2.2).

Kept separate from the SQLAlchemy `User` model: these define the API contract
(what clients send and receive), and never expose `password_hash`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    # bcrypt considers only the first 72 bytes; cap length to keep behaviour clear.
    password: str = Field(min_length=8, max_length=72)
    full_name: str | None = Field(default=None, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetRequestResponse(BaseModel):
    """Always returned regardless of whether the email exists (no enumeration).

    `reset_token`/`reset_link` are populated only in development, where there's
    no email service to deliver the link — they let the reset flow be completed
    (and demoed) without a real inbox. In production both stay null.
    """

    message: str
    reset_token: str | None = None
    reset_link: str | None = None


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=72)


class MessageResponse(BaseModel):
    message: str
