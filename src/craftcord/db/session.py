"""Async SQLAlchemy engine and session lifecycle.

CraftCord never calls `Base.metadata.create_all()` — the database schema is
owned entirely by Alembic migrations (`alembic upgrade head`, run by
`scripts/entrypoint.sh` before the bot process starts). This module is only
responsible for the engine/sessionmaker lifecycle at runtime.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from craftcord.config import Settings
from craftcord.logging_config import get_logger

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(settings: Settings) -> AsyncEngine:
    """Create the process-wide async engine and sessionmaker.

    Call once during `bot.setup_hook`. Safe to call again after
    `dispose_engine()` (e.g. in tests).

    Args:
        settings: Application settings providing the database URL.

    Returns:
        The created `AsyncEngine`.
    """
    global _engine, _sessionmaker

    _engine = create_async_engine(
        settings.sqlalchemy_database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=5,
        echo=False,
    )
    _sessionmaker = async_sessionmaker(
        bind=_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    logger.info("db_engine_initialised", pool_size=10, max_overflow=5)
    return _engine


async def dispose_engine() -> None:
    """Dispose the process-wide engine cleanly. Call during bot shutdown."""
    global _engine, _sessionmaker

    if _engine is not None:
        await _engine.dispose()
        logger.info("db_engine_disposed")
    _engine = None
    _sessionmaker = None


def get_engine() -> AsyncEngine:
    """Return the initialised engine, or raise if `init_engine` hasn't run yet."""
    if _engine is None:
        raise RuntimeError("Database engine has not been initialised. Call init_engine() first.")
    return _engine


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Async context manager yielding a transactional `AsyncSession`.

    On successful exit the transaction is committed; on exception it is
    rolled back and the exception re-raised. The session itself owns
    commit/rollback — repositories (see `db/repositories/`) must never call
    `session.commit()` themselves.

    Usage:
        async with get_session() as session:
            repo = GuildRepository(session)
            await repo.upsert(guild_id, name)
            # commit happens automatically on clean exit
    """
    if _sessionmaker is None:
        raise RuntimeError("Database engine has not been initialised. Call init_engine() first.")

    async with _sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
