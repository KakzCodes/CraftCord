"""Alembic migration environment, wired for an async (asyncpg) engine.

NOTE: this pulls the database URL from `craftcord.config.get_settings()`,
the same `Settings` model the bot itself uses — which means *every*
required env var (Discord token, Pterodactyl credentials, RCON
credentials, not just `DATABASE_URL`) must be set for `alembic upgrade
head` to run, not only the database ones. This is a deliberate
simplification: Docker Compose is the only supported deployment path for
this iteration (per the project scope), and `scripts/entrypoint.sh` always
runs migrations inside the same container that has the full `.env`
loaded, so the coupling costs nothing in practice. A standalone
migration-only settings model would be the fix if a bare CI/local
migration workflow (without the rest of the bot's secrets) is ever needed.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from craftcord.config import get_settings
from craftcord.db import models  # noqa: F401 - import side effect: populates Base.metadata
from craftcord.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().sqlalchemy_database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emits SQL to stdout; no DB connection)."""
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
    """Configure the migration context against a live sync-style connection and run it."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode using an async engine.

    `async_engine_from_config` + `connection.run_sync(...)` is the
    standard pattern for driving Alembic (which is fundamentally
    sync-API) against an async SQLAlchemy engine.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
