"""Alembic migration environment (async, psycopg 3).

The database URL comes from `app.core.config.settings.database_url` (the
DATABASE_URL env var), so nothing secret lives in `alembic.ini`. All ORM models
are imported here so `Base.metadata` is fully populated for autogenerate.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.database import Base

# Import models for their side effect of registering on Base.metadata.
from app.auth import models as _auth_models  # noqa: F401
from app.companies import models as _company_models  # noqa: F401
from app.transactions import models as _transaction_models  # noqa: F401
from app.financial_engine import models as _financial_models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The DB URL comes straight from settings (env), NOT via config.set_main_option:
# ConfigParser does %-interpolation and would choke on URL-encoded passwords
# (e.g. '%40' for '@'). Keeping it out of the ini avoids that entirely.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Render SQL without a DB connection (`alembic ... --sql`)."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(settings.database_url, poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    if not settings.database_url:
        raise SystemExit(
            "DATABASE_URL is not set — configure your Supabase connection string "
            "in backend/.env before running online migrations."
        )
    asyncio.run(run_migrations_online())
