"""Repository tests, run against a real (throwaway, testcontainers-managed) Postgres.

Constraint enforcement — unique constraints, the partial unique index, and
`ON DELETE CASCADE` — needs a real Postgres to verify faithfully, which is
why these aren't mocked.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from craftcord.db.repositories import GuildRepository, ServerRepository, SessionRepository, UserRepository


async def test_guild_upsert_is_idempotent_and_updates_name(async_session) -> None:
    repo = GuildRepository(async_session)

    first = await repo.upsert(discord_id=1, name="My Guild")
    assert first.name == "My Guild"

    second = await repo.upsert(discord_id=1, name="Renamed Guild")
    assert second.id == first.id
    assert second.name == "Renamed Guild"

    fetched = await repo.get_by_id(1)
    assert fetched is not None
    assert fetched.name == "Renamed Guild"


async def test_get_by_id_returns_none_for_unregistered_guild(async_session) -> None:
    repo = GuildRepository(async_session)
    assert await repo.get_by_id(999) is None


async def test_server_name_unique_per_guild(async_session) -> None:
    guild_repo = GuildRepository(async_session)
    server_repo = ServerRepository(async_session)
    await guild_repo.upsert(discord_id=1, name="Guild")
    await server_repo.register(1, "Survival", "uuid-1", 1, "1.20.4", False)

    with pytest.raises(IntegrityError):
        await server_repo.register(1, "Survival", "uuid-2", 2, "1.20.4", False)


async def test_only_one_default_server_per_guild(async_session) -> None:
    guild_repo = GuildRepository(async_session)
    server_repo = ServerRepository(async_session)
    await guild_repo.upsert(discord_id=1, name="Guild")

    await server_repo.register(1, "Survival", "uuid-1", 1, "1.20.4", True)
    second = await server_repo.register(1, "Creative", "uuid-2", 2, "1.20.4", True)

    # register() clears any prior default before inserting the new one, so
    # this should succeed, with exactly the newest server left as default.
    default = await server_repo.get_default_for_guild(1)
    assert default is not None
    assert default.id == second.id

    first_refetched = await server_repo.get_by_name(1, "Survival")
    assert first_refetched is not None
    assert first_refetched.is_default is False


async def test_set_default_clears_prior_default_transactionally(async_session) -> None:
    guild_repo = GuildRepository(async_session)
    server_repo = ServerRepository(async_session)
    await guild_repo.upsert(discord_id=1, name="Guild")
    first = await server_repo.register(1, "Survival", "uuid-1", 1, "1.20.4", True)
    second = await server_repo.register(1, "Creative", "uuid-2", 2, "1.20.4", False)

    await server_repo.set_default(1, second.id)

    default = await server_repo.get_default_for_guild(1)
    assert default is not None
    assert default.id == second.id

    first_refetched = await server_repo.get_by_name(1, "Survival")
    assert first_refetched is not None
    assert first_refetched.id == first.id
    assert first_refetched.is_default is False


async def test_cascade_delete_removes_servers_when_guild_removed(async_session) -> None:
    guild_repo = GuildRepository(async_session)
    server_repo = ServerRepository(async_session)
    guild = await guild_repo.upsert(discord_id=1, name="Guild")
    await server_repo.register(1, "Survival", "uuid-1", 1, "1.20.4", False)

    await async_session.delete(guild)
    await async_session.flush()

    assert await server_repo.get_by_name(1, "Survival") is None


async def test_unregister_server_cascades_to_sessions(async_session) -> None:
    guild_repo = GuildRepository(async_session)
    server_repo = ServerRepository(async_session)
    session_repo = SessionRepository(async_session)
    await guild_repo.upsert(discord_id=1, name="Guild")
    server = await server_repo.register(1, "Survival", "uuid-1", 1, "1.20.4", False)
    await session_repo.open(server.id, started_by=42)

    # If ON DELETE CASCADE weren't wired up correctly, this would raise a
    # foreign-key violation instead of succeeding.
    await server_repo.unregister(server.id)

    assert await server_repo.get_by_name(1, "Survival") is None


async def test_user_link_lowercases_username_for_case_insensitive_lookup(async_session) -> None:
    repo = UserRepository(async_session)
    await repo.link(discord_id=1, mc_username="Notch", mc_uuid=None)

    found = await repo.get_by_minecraft("NOTCH")

    assert found is not None
    assert found.minecraft_username == "notch"


async def test_user_minecraft_username_unique_case_insensitively(async_session) -> None:
    repo = UserRepository(async_session)
    await repo.link(discord_id=1, mc_username="Notch", mc_uuid=None)

    with pytest.raises(IntegrityError):
        await repo.link(discord_id=2, mc_username="notch", mc_uuid=None)


async def test_session_repo_open_and_close_latest(async_session) -> None:
    guild_repo = GuildRepository(async_session)
    server_repo = ServerRepository(async_session)
    session_repo = SessionRepository(async_session)
    await guild_repo.upsert(discord_id=1, name="Guild")
    server = await server_repo.register(1, "Survival", "uuid-1", 1, "1.20.4", False)

    opened = await session_repo.open(server.id, started_by=42)
    assert opened.stopped_at is None

    await session_repo.close_latest(server.id)
    await async_session.refresh(opened)

    assert opened.stopped_at is not None
