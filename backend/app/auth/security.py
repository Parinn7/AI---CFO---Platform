"""Password hashing and JWT helpers for authentication (tasks 2.2, 2.4).

Two concerns, deliberately deterministic and free of any DB/HTTP dependency so
they can be unit-tested in isolation:

  * Password hashing with bcrypt (NFR-2 — never store plaintext).
  * Signed JWT tokens: session access tokens (FR-1.2) and short-lived
    password-reset tokens (FR-1.4).

Every token carries a `type` claim (`access` vs `reset`) and each decoder
verifies it, so a reset token can never be replayed as a session token or vice
versa. Reset tokens additionally embed a fingerprint of the user's current
password hash (`pwf`); once the password changes the fingerprint no longer
matches, which makes each reset link effectively single-use — without needing a
DB table to track issued tokens.

bcrypt only considers the first 72 bytes of a password; we truncate explicitly
so long passphrases hash consistently instead of raising on newer bcrypt
releases.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

_BCRYPT_MAX_BYTES = 72

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_RESET = "reset"


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


def _encode(payload: dict) -> str:
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode(token: str) -> dict | None:
    try:
        return jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        return None


def create_access_token(
    subject: str, expires_delta: timedelta | None = None
) -> str:
    """Create a signed session JWT whose `sub` claim is the user id (a UUID string)."""
    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    return _encode(
        {"sub": subject, "type": TOKEN_TYPE_ACCESS, "exp": expire, "iat": now}
    )


def decode_access_token(token: str) -> str | None:
    """Return the `sub` (user id) from a valid access token, or None if invalid."""
    payload = _decode(token)
    if payload is None or payload.get("type") != TOKEN_TYPE_ACCESS:
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None


def password_fingerprint(password_hash: str) -> str:
    """Short, non-reversible fingerprint of a bcrypt hash, embedded in reset
    tokens so a token stops working once the password (and thus hash) changes."""
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def create_password_reset_token(
    subject: str, password_hash: str, expires_delta: timedelta | None = None
) -> str:
    """Create a short-lived, single-use password-reset JWT for a user."""
    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta or timedelta(minutes=settings.reset_token_expire_minutes)
    )
    return _encode(
        {
            "sub": subject,
            "type": TOKEN_TYPE_RESET,
            "pwf": password_fingerprint(password_hash),
            "exp": expire,
            "iat": now,
        }
    )


def decode_password_reset_token(token: str) -> tuple[str, str] | None:
    """Return `(sub, pwf)` from a valid reset token, or None if invalid/expired.

    The caller must still check `pwf` against the user's *current* password
    fingerprint to enforce single use.
    """
    payload = _decode(token)
    if payload is None or payload.get("type") != TOKEN_TYPE_RESET:
        return None
    subject = payload.get("sub")
    fingerprint = payload.get("pwf")
    if not isinstance(subject, str) or not isinstance(fingerprint, str):
        return None
    return subject, fingerprint
