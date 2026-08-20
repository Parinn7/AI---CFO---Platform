"""Password hashing and JWT helpers for authentication (task 2.2).

Two concerns, deliberately deterministic and free of any DB/HTTP dependency so
they can be unit-tested in isolation:

  * Password hashing with bcrypt (NFR-2 — never store plaintext).
  * Signed JWT access tokens for session auth (FR-1.2).

bcrypt only considers the first 72 bytes of a password; we truncate explicitly
so long passphrases hash consistently instead of raising on newer bcrypt
releases.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

_BCRYPT_MAX_BYTES = 72


def _prepare(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    """Return a bcrypt hash (with embedded salt) for `password`."""
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Check a plaintext password against a stored bcrypt hash. Never raises."""
    try:
        return bcrypt.checkpw(_prepare(password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(
    subject: str, expires_delta: timedelta | None = None
) -> str:
    """Create a signed JWT whose `sub` claim is the user id (a UUID string)."""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload = {"sub": subject, "exp": expire, "iat": datetime.now(timezone.utc)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str | None:
    """Return the `sub` (user id) from a valid token, or None if invalid/expired."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None
