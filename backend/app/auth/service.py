"""Auth service layer — DB-backed user creation and credential checks.

Endpoints (`router.py`) stay thin; all queries and the hash/verify calls live
here so the auth logic can be reasoned about (and reused) in one place.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.schemas import SignupRequest
from app.auth.security import (
    create_password_reset_token,
    decode_password_reset_token,
    hash_password,
    password_fingerprint,
    verify_password,
)


class EmailAlreadyRegisteredError(Exception):
    """Raised when signing up with an email that already exists."""


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def create_user(db: AsyncSession, data: SignupRequest) -> User:
    """Create a user, hashing the password. Emails are normalised to lowercase.

    Raises EmailAlreadyRegisteredError if the email is taken.
    """
    email = data.email.lower()
    if await get_user_by_email(db, email) is not None:
        raise EmailAlreadyRegisteredError(email)

    user = User(
        email=email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(
    db: AsyncSession, email: str, password: str
) -> User | None:
    """Return the user if email+password are valid, else None."""
    user = await get_user_by_email(db, email.lower())
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def create_password_reset(db: AsyncSession, email: str) -> str | None:
    """Issue a password-reset token for `email`, or None if no such user.

    Callers must NOT leak the None-vs-token distinction to the client (avoid
    account enumeration) — respond identically either way.
    """
    user = await get_user_by_email(db, email.lower())
    if user is None:
        return None
    return create_password_reset_token(str(user.id), user.password_hash)


async def reset_password(db: AsyncSession, token: str, new_password: str) -> bool:
    """Set a new password if the reset token is valid and unused. Returns success.

    The token's embedded fingerprint must still match the user's current
    password hash; a mismatch means the token was already used (password
    already changed) or is otherwise stale.
    """
    decoded = decode_password_reset_token(token)
    if decoded is None:
        return False
    subject, fingerprint = decoded
    try:
        user_id = uuid.UUID(subject)
    except ValueError:
        return False

    user = await get_user_by_id(db, user_id)
    if user is None:
        return False
    if password_fingerprint(user.password_hash) != fingerprint:
        return False

    user.password_hash = hash_password(new_password)
    await db.commit()
    return True
