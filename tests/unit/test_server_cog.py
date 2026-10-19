"""Tests for the registered-server command callbacks."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from craftcord.cogs import server as server_module
from craftcord.cogs.server import ServerCog
from craftcord.core.pterodactyl import PterodactylResources
from craftcord.db.models import Guild, Server


class _SessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_: object) -> bool:
        return False


def _interaction() -> Mock:
    interaction = Mock(spec=discord.Interaction)
    interaction.user = Mock(spec=discord.User)
    interaction.user.id = 71
    interaction.response = Mock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup = Mock()
    interaction.followup.send = AsyncMock()
    return interaction


def _callback(command: object):
    callback = command.callback
    while hasattr(callback, "__wrapped__"):
        callback = callback.__wrapped__
    return callback


def _guild() -> Guild:
    return Guild(id=1, name="Test Guild", tier="grass")


def _server() -> Server:
    server = Server(id=10, guild_id=1, name="Survival", pterodactyl_uuid="uuid", pterodactyl_numeric_id=5)
    server.guild = _guild()
    return server


@pytest.mark.asyncio
async def test_start_sends_power_and_opens_uptime_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_module, "get_session", _SessionContext)
    opened: list[tuple[int, int]] = []

    class SessionRepo:
        def __init__(self, _session: object) -> None:
            pass

        async def open(self, server_id: int, discord_id: int) -> None:
            opened.append((server_id, discord_id))

    monkeypatch.setattr(server_module, "SessionRepository", SessionRepo)
    ptero = SimpleNamespace(send_power=AsyncMock())
    interaction = _interaction()

    await _callback(ServerCog.start)(
        ServerCog(SimpleNamespace(pterodactyl=ptero)),
        interaction,
        guild_row=_guild(),
        server_row=_server(),
    )

    ptero.send_power.assert_awaited_once_with("uuid", "start")
    assert opened == [(10, 71)]
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_restart_sends_restart_power_signal() -> None:
    ptero = SimpleNamespace(send_power=AsyncMock())
    interaction = _interaction()

    await _callback(ServerCog.restart)(
        ServerCog(SimpleNamespace(pterodactyl=ptero)),
        interaction,
        guild_row=_guild(),
        server_row=_server(),
    )

    ptero.send_power.assert_awaited_once_with("uuid", "restart")
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_status_renders_resources_and_degrades_when_rcon_is_down() -> None:
    from craftcord.core.exceptions import RconError

    resources = PterodactylResources(
        state="running",
        cpu_percent=8.5,
        memory_bytes=1024,
        memory_limit_bytes=2048,
        disk_bytes=512,
        disk_limit_bytes=4096,
        uptime_ms=60000,
    )
    ptero = SimpleNamespace(get_resources=AsyncMock(return_value=resources))
    rcon = SimpleNamespace(list_players=AsyncMock(side_effect=RconError("not ready")))
    interaction = _interaction()

    await _callback(ServerCog.status)(
        ServerCog(SimpleNamespace(pterodactyl=ptero, rcon=rcon, rcon_config=object())),
        interaction,
        guild_row=_guild(),
        server_row=_server(),
    )

    ptero.get_resources.assert_awaited_once_with("uuid")
    assert interaction.followup.send.call_args.kwargs["embed"].title == "Survival"


@pytest.mark.asyncio
async def test_info_uses_recent_uptime_total(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_module, "get_session", _SessionContext)
    since_values: list[datetime] = []

    class SessionRepo:
        def __init__(self, _session: object) -> None:
            pass

        async def total_uptime_seconds(self, server_id: int, since: datetime) -> int:
            assert server_id == 10
            since_values.append(since)
            return 3600

    monkeypatch.setattr(server_module, "SessionRepository", SessionRepo)
    interaction = _interaction()

    await _callback(ServerCog.info)(
        ServerCog(None), interaction, guild_row=_guild(), server_row=_server()
    )

    assert since_values[0].tzinfo is UTC
    assert interaction.followup.send.call_args.kwargs["embed"].title == "Survival"


@pytest.mark.asyncio
async def test_list_sends_empty_state_and_server_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_module, "get_session", _SessionContext)
    rows: list[Server] = []

    class ServerRepo:
        def __init__(self, _session: object) -> None:
            pass

        async def list_for_guild(self, _guild_id: int) -> list[Server]:
            return rows

    monkeypatch.setattr(server_module, "ServerRepository", ServerRepo)
    cog = ServerCog(None)
    interaction = _interaction()

    await _callback(ServerCog.list_servers)(cog, interaction, guild_row=_guild())
    assert "No servers" in interaction.followup.send.call_args.kwargs["embed"].description

    rows.append(_server())
    interaction = _interaction()
    await _callback(ServerCog.list_servers)(cog, interaction, guild_row=_guild())
    assert "Survival" in interaction.followup.send.call_args.kwargs["embed"].description


@pytest.mark.asyncio
async def test_ip_shows_allocation_address_and_missing_allocation() -> None:
    allocation = SimpleNamespace(ip="127.0.0.1", port=25565)
    ptero = SimpleNamespace(get_server=AsyncMock(return_value=SimpleNamespace(default_allocation=allocation)))
    interaction = _interaction()
    cog = ServerCog(SimpleNamespace(pterodactyl=ptero))

    await _callback(ServerCog.ip)(cog, interaction, guild_row=_guild(), server_row=_server())
    assert "127.0.0.1:25565" in interaction.followup.send.call_args.kwargs["embed"].description

    ptero.get_server.return_value = SimpleNamespace(default_allocation=None)
    interaction = _interaction()
    await _callback(ServerCog.ip)(cog, interaction, guild_row=_guild(), server_row=_server())
    assert interaction.followup.send.call_args.kwargs["ephemeral"] is True
