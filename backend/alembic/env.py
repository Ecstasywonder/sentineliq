"""
Alembic environment configuration for SentinelIQ.
Uses async engine via asyncpg for online migrations.
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

# Import all models so Alembic can detect them
from app.db.session import Base  # noqa: F401
import app.models  # noqa: F401 — registers all tables with Base.metadata
from app.config import get_settings
from app.db.migration_compat import remap_legacy_assessment_revision

# Alembic Config object
config = context.config

# Load settings once
settings = get_settings()

# For offline mode use the sync URL as-is (psycopg2 / plain psycopg)
# For online mode we build an asyncpg URL in run_async_migrations()
config.set_main_option("sqlalchemy.url", settings.database_url_sync)

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _async_url() -> str:
    """
    Return the asyncpg-compatible URL for the online migration engine.

    Converts any of:
        postgresql://...
        postgresql+psycopg2://...
        postgresql+psycopg://...
    to:
        postgresql+asyncpg://...

    The DATABASE_URL env var (asyncpg) is preferred when present; otherwise
    the sync URL is re-schemed.
    """
    # Prefer the already-async URL if configured
    if settings.database_url and "+asyncpg" in settings.database_url:
        return settings.database_url

    # Fall back: rewrite the sync URL to asyncpg scheme
    url = settings.database_url_sync
    # Strip any existing driver suffix so we can set asyncpg cleanly
    if "+" in url.split("://")[0]:
        scheme = url.split("://")[0].split("+")[0]
        return url.replace(url.split("://")[0], f"{scheme}+asyncpg", 1)
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL, no live connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # ``0002_assessment_reconstruction_bundle`` was released before its
    # over-length revision identifier was found to exceed Alembic's default
    # VARCHAR(32). Normalize that equivalent legacy stamp before Alembic tries
    # to resolve it against the current revision graph.
    with connection.begin():
        remap_legacy_assessment_revision(connection)
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations using an asyncpg async engine."""
    connectable = create_async_engine(
        _async_url(),
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
