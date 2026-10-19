"""Database engine and transaction lifecycle tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from craftcord.db import session as session_module


@pytest.fixture
def uninitialised_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_module, "_engine", None)
    monkeypatch.setattr(session_module, "_sessionmaker", None)


def test_get_engine_requires_initialisation(uninitialised_engine: None) -> None:
    with pytest.raises(RuntimeError, match="init_engine"):
        session_module.get_engine()


def test_init_engine_creates_async_engine_and_sessionmaker(
    monkeypatch: pytest.MonkeyPatch, uninitialised_engine: None
) -> None:
    engine = Mock()
    create_engine = Mock(return_value=engine)
    factory = Mock()
    make_sessionmaker = Mock(return_value=factory)
    monkeypatch.setattr(session_module, "create_async_engine", create_engine)
    monkeypatch.setattr(session_module, "async_sessionmaker", make_sessionmaker)
    settings = SimpleNamespace(sqlalchemy_database_url="postgresql+asyncpg://db/craftcord")

    result = session_module.init_engine(settings)

    assert result is engine
    assert session_module.get_engine() is engine
    create_engine.assert_called_once_with(
        "postgresql+asyncpg://db/craftcord",
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=5,
        echo=False,
    )
    make_sessionmaker.assert_called_once_with(bind=engine, expire_on_commit=False, autoflush=False)


@pytest.mark.asyncio
async def test_get_session_commits_on_success(
    monkeypatch: pytest.MonkeyPatch, uninitialised_engine: None
) -> None:
    db_session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    context = _SessionContext(db_session)
    monkeypatch.setattr(session_module, "_sessionmaker", Mock(return_value=context))

    async with session_module.get_session() as yielded:
        assert yielded is db_session

    db_session.commit.assert_awaited_once()
    db_session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_session_rolls_back_and_reraises_on_error(
    monkeypatch: pytest.MonkeyPatch, uninitialised_engine: None
) -> None:
    db_session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    monkeypatch.setattr(session_module, "_sessionmaker", Mock(return_value=_SessionContext(db_session)))

    with pytest.raises(ValueError, match="abort"):
        async with session_module.get_session():
            raise ValueError("abort")

    db_session.commit.assert_not_awaited()
    db_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispose_engine_closes_and_resets_global_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(session_module, "_engine", engine)
    monkeypatch.setattr(session_module, "_sessionmaker", Mock())

    await session_module.dispose_engine()

    engine.dispose.assert_awaited_once()
    assert session_module._engine is None
    assert session_module._sessionmaker is None


@pytest.mark.asyncio
async def test_dispose_engine_is_safe_before_initialisation(uninitialised_engine: None) -> None:
    await session_module.dispose_engine()
    assert session_module._engine is None
    assert session_module._sessionmaker is None


@pytest.mark.asyncio
async def test_get_session_requires_initialisation(uninitialised_engine: None) -> None:
    with pytest.raises(RuntimeError, match="init_engine"):
        async with session_module.get_session():
            pytest.fail("session should not be yielded")


class _SessionContext:
    def __init__(self, session: object) -> None:
        self.session = session

    async def __aenter__(self) -> object:
        return self.session

    async def __aexit__(self, *exc_info: object) -> bool:
        return False
