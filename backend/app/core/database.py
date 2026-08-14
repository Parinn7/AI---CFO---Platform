"""Database connection layer.

Provides the async SQLAlchemy engine, session factory, a declarative `Base`
for models (populated from Phase 2 onward), and a `get_db` FastAPI dependency.

No Postgres instance is provisioned yet, so the engine is created lazily and
`check_connection()` degrades gracefully — the app boots even with no DB
reachable, and the health endpoint reports the real status.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from app.core.config import settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models (defined in later phases)."""


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine | None:
    """Return the shared async engine, or None if no DATABASE_URL is set."""
    global _engine, _session_factory
    if not settings.database_url:
        return None
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.environment == "development",
            pool_pre_ping=True,
        )
        _session_factory = async_sessionmaker(
            _engine, expire_on_commit=False, class_=AsyncSession
        )
    return _engine


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async DB session."""
    if get_engine() is None or _session_factory is None:
        raise RuntimeError(
            "DATABASE_URL is not configured — no database connection available."
        )
    async with _session_factory() as session:
        yield session


async def check_connection() -> str:
    """Report DB connectivity for the health endpoint.

    Returns one of: 'connected', 'not_configured', 'unreachable'.
    Never raises — a down database must not break the health check.
    """
    engine = get_engine()
    if engine is None:
        return "not_configured"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "connected"
    except Exception:
        return "unreachable"


async def dispose_engine() -> None:
    """Dispose the engine on shutdown."""
    if _engine is not None:
        await _engine.dispose()
