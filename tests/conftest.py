"""Shared pytest fixtures.

- `postgres_container`: a session-scoped, throwaway Postgres container.
- `migrated_engine`: a session-scoped async engine, migrated once via the
  project's real Alembic migrations (not `create_all()` — we want test
  coverage of the actual migration path, matching the "no create_all()"
  rule the application itself follows).
- `async_session`: a function-scoped `AsyncSession` bound to a connection
  whose outer transaction is rolled back after every test, so tests never
  need to clean up their own rows. Uses SQLAlchemy 2.0's
  `join_transaction_mode="create_savepoint"` so that even a repository
  calling `session.commit()` (which happens inside the app's own
  `get_session()`, and transitively inside every repository test here)
  only creates/releases a SAVEPOINT rather than ending the outer
  transaction early.
- `respx_mock`: a `respx` router for mocking `httpx` calls to Pterodactyl/Mojang.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
import respx
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from craftcord.config import get_settings

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Dummy values for every *other* required setting, so `Settings()` validates
# successfully in the test process — only DATABASE_URL needs to point at the
# real (containerized) database.
_DUMMY_ENV = {
    "DISCORD_TOKEN": "test-token",
    "PTERODACTYL_URL": "https://panel.test",
    "PTERODACTYL_API_KEY": "ptlc_test_key",
    "RCON_HOST": "localhost",
    "RCON_PASSWORD": "test-password",
    "LOG_FORMAT": "console",
}


@pytest.fixture(scope="session")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    """A session-scoped event loop, so session-scoped async fixtures can share one."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    """A throwaway Postgres 16 container, alive for the whole test session."""
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def _test_database_url(postgres_container: PostgresContainer) -> str:
    """The container's connection URL, rewritten to use the asyncpg driver."""
    sync_url = postgres_container.get_connection_url()
    return sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")


@pytest.fixture(scope="session")
def _apply_migrations(_test_database_url: str) -> None:
    """Run the project's real `alembic upgrade head` against the test container, once.

    `env.py` sources its URL from `craftcord.config.get_settings()`, so the
    required env vars are patched directly (not via the function-scoped
    `monkeypatch` fixture, since this fixture is session-scoped) before
    invoking Alembic, and `get_settings`'s cache is cleared first so it
    re-reads them.
    """
    import os

    patched = {**_DUMMY_ENV, "DATABASE_URL": _test_database_url}
    previous = {key: os.environ.get(key) for key in patched}
    os.environ.update(patched)
    get_settings.cache_clear()
    try:
        config = Config(str(_PROJECT_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(_PROJECT_ROOT / "alembic"))
        command.upgrade(config, "head")
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


@pytest_asyncio.fixture(scope="session")
async def migrated_engine(_test_database_url: str, _apply_migrations: None):
    """A session-scoped async engine against the migrated test database."""
    engine = create_async_engine(_test_database_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def async_session(migrated_engine) -> AsyncIterator[AsyncSession]:
    """A per-test `AsyncSession` whose changes are rolled back when the test ends."""
    connection = await migrated_engine.connect()
    transaction = await connection.begin()
    sessionmaker = async_sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    session = sessionmaker()
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest.fixture
def respx_mock() -> Iterator[respx.MockRouter]:
    """A respx router for mocking `httpx` calls made by `PterodactylClient`/`MojangClient`."""
    with respx.mock(assert_all_called=False) as mock:
        yield mock
