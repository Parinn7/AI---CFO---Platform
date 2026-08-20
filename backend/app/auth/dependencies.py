"""Auth dependencies — resolve the current user from a Bearer JWT.

`get_current_user` is the building block every protected endpoint (from Phase 2.3
onward) depends on; it turns the `Authorization: Bearer <token>` header into a
loaded `User`, raising 401 on any failure.
"""

from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.security import decode_access_token
from app.auth.service import get_user_by_id
from app.core.database import get_db

# auto_error=False so we can raise a consistent 401 with WWW-Authenticate below.
_bearer = HTTPBearer(auto_error=False)

_credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise _credentials_exception

    subject = decode_access_token(credentials.credentials)
    if subject is None:
        raise _credentials_exception

    try:
        user_id = uuid.UUID(subject)
    except ValueError:
        raise _credentials_exception

    user = await get_user_by_id(db, user_id)
    if user is None:
        raise _credentials_exception
    return user
