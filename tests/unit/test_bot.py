"""Bot wiring and lifecycle tests without connecting to Discord."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from craftcord import bot as bot_module
from craftcord.bot import CraftCordBot
from craftcord.config import Settings

_BASE_ENV = {
    "DISCORD_TOKEN": "test-token",
    "PTERODACTYL_URL": "https://panel.test",
    "PTERODACTYL_API_KEY": "ptlc_test_key",
    "DATABASE_URL": "postgresql+asyncpg://user:pass@db:5432/craftcord",
    "RCON_HOST": "mc-server",
    "RCON_PASSWORD": "test-password",
    "LOG_FORMAT": "console",
}


def _settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    for name, value in {**_BASE_ENV, **overrides}.items():
        monkeypatch.setenv(name, value)
    return Settings(_env_file=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("guild_id", [None, 12345])
async def test_setup_hook_loads_cogs_and_syncs_commands(
    monkeypatch: pytest.MonkeyPatch, guild_id: int | None
) -> None:
    env = {"DISCORD_GUILD_ID_DEV": str(guild_id)} if guild_id is not None else {}
    settings = _settings(monkeypatch, **env)
    bot = CraftCordBot(settings)
    load_extension = AsyncMock()
    sync = AsyncMock(return_value=[object(), object()])
    copy_global_to = Mock()
    init_engine = Mock()
    dispose_engine = AsyncMock()
    close_pterodactyl = AsyncMock()
    close_mojang = AsyncMock()
    monkeypatch.setattr(bot, "load_extension", load_extension)
    monkeypatch.setattr(bot.tree, "sync", sync)
    monkeypatch.setattr(bot.tree, "copy_global_to", copy_global_to)
    monkeypatch.setattr(bot_module, "init_engine", init_engine)
    monkeypatch.setattr(bot_module, "dispose_engine", dispose_engine)
    monkeypatch.setattr(bot.pterodactyl, "aclose", close_pterodactyl)
    monkeypatch.setattr(bot.mojang, "aclose", close_mojang)

    try:
        await bot.setup_hook()
        init_engine.assert_called_once_with(settings)
        assert [call.args[0] for call in load_extension.await_args_list] == [
            "craftcord.cogs.server",
            "craftcord.cogs.players",
            "craftcord.cogs.admin",
            "craftcord.cogs.meta",
        ]
        assert bot.tree.on_error == bot._on_app_command_error
        if guild_id is None:
            copy_global_to.assert_not_called()
            sync.assert_awaited_once_with()
        else:
            copy_global_to.assert_called_once()
            assert copy_global_to.call_args.kwargs["guild"].id == guild_id
            sync.assert_awaited_once_with(guild=copy_global_to.call_args.kwargs["guild"])
    finally:
        await bot.close()

    close_pterodactyl.assert_awaited_once()
    close_mojang.assert_awaited_once()
    dispose_engine.assert_awaited_once()


@pytest.mark.asyncio
async def test_bot_builds_optional_provisioning_template_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(
        monkeypatch,
        PTERODACTYL_APPLICATION_API_KEY="ptla_test_key",
        PTERODACTYL_OWNER_USER_ID="42",
        PTERODACTYL_EGG_ID="7",
        PTERODACTYL_DOCKER_IMAGE="ghcr.io/example/java:21",
        PTERODACTYL_STARTUP_COMMAND="java -jar server.jar",
        PTERODACTYL_CREATE_ENVIRONMENT='{"SERVER_JARFILE":"server.jar"}',
        PTERODACTYL_MEMORY_MB="2048",
        PTERODACTYL_DISK_MB="8192",
        PTERODACTYL_DEPLOY_LOCATION_IDS="1,2",
    )
    bot = CraftCordBot(settings)
    close_app = AsyncMock()
    monkeypatch.setattr(bot.pterodactyl_app, "aclose", close_app)
    monkeypatch.setattr(bot_module, "dispose_engine", AsyncMock())

    assert bot.pterodactyl_app is not None
    assert bot.creation_template is not None
    assert bot.creation_template.owner_user_id == 42
    assert bot.creation_template.environment == {"SERVER_JARFILE": "server.jar"}
    assert bot.creation_template.deploy_location_ids == [1, 2]

    await bot.close()
    close_app.assert_awaited_once()
