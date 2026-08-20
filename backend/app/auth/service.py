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
from app.auth.security import hash_password, verify_password


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
