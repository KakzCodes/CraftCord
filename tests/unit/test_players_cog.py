"""Tests for player linking and RCON-backed player commands."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from craftcord.cogs import players
from craftcord.cogs.players import CopyCoordinatesView, PlayersCog
from craftcord.core.exceptions import MojangLookupError
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
    interaction.user.mention = "<@71>"
    interaction.user.display_name = "Player"
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
    return Server(id=10, guild_id=1, name="Survival", pterodactyl_uuid="uuid", pterodactyl_numeric_id=5)


@pytest.mark.asyncio
async def test_link_saves_account_with_resolved_uuid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(players, "get_session", _SessionContext)
    linked: list[tuple[int, str, str | None]] = []

    class UserRepo:
        def __init__(self, _session: object) -> None:
            pass

        async def link(self, discord_id: int, username: str, uuid: str | None) -> None:
            linked.append((discord_id, username, uuid))

    monkeypatch.setattr(players, "UserRepository", UserRepo)
    cog = PlayersCog(SimpleNamespace(mojang=SimpleNamespace(get_uuid=AsyncMock(return_value="abc123"))))
    interaction = _interaction()

    await _callback(PlayersCog.link)(cog, interaction, guild_row=_guild(), minecraft_username="Steve")

    assert linked == [(71, "Steve", "abc123")]
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_link_degrades_gracefully_when_mojang_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(players, "get_session", _SessionContext)
    linked: list[str | None] = []

    class UserRepo:
        def __init__(self, _session: object) -> None:
            pass

        async def link(self, _discord_id: int, _username: str, uuid: str | None) -> None:
            linked.append(uuid)

    monkeypatch.setattr(players, "UserRepository", UserRepo)
    mojang = SimpleNamespace(get_uuid=AsyncMock(side_effect=MojangLookupError("offline")))
    interaction = _interaction()

    await _callback(PlayersCog.link)(
        PlayersCog(SimpleNamespace(mojang=mojang)),
        interaction,
        guild_row=_guild(),
        minecraft_username="Steve",
    )

    assert linked == [None]
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_unlink_removes_current_users_link(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(players, "get_session", _SessionContext)
    unlinked: list[int] = []

    class UserRepo:
        def __init__(self, _session: object) -> None:
            pass

        async def unlink(self, discord_id: int) -> None:
            unlinked.append(discord_id)

    monkeypatch.setattr(players, "UserRepository", UserRepo)
    interaction = _interaction()

    await _callback(PlayersCog.unlink)(PlayersCog(None), interaction, guild_row=_guild())

    assert unlinked == [71]
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_whois_reports_unlinked_account(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(players, "get_session", _SessionContext)

    class UserRepo:
        def __init__(self, _session: object) -> None:
            pass

        async def get_by_discord(self, _discord_id: int) -> None:
            return None

    monkeypatch.setattr(players, "UserRepository", UserRepo)
    interaction = _interaction()

    await _callback(PlayersCog.whois)(PlayersCog(None), interaction, guild_row=_guild())

    assert "Not Linked" in interaction.followup.send.call_args.kwargs["embed"].title


@pytest.mark.asyncio
async def test_whois_reports_link_and_online_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(players, "get_session", _SessionContext)

    class UserRepo:
        def __init__(self, _session: object) -> None:
            pass

        async def get_by_discord(self, _discord_id: int) -> object:
            return SimpleNamespace(minecraft_username="Steve")

    class ServerRepo:
        def __init__(self, _session: object) -> None:
            pass

        async def get_default_for_guild(self, _guild_id: int) -> object:
            return _server()

    monkeypatch.setattr(players, "UserRepository", UserRepo)
    monkeypatch.setattr(players, "ServerRepository", ServerRepo)
    rcon = SimpleNamespace(list_players=AsyncMock(return_value=["steve", "Alex"]))
    interaction = _interaction()

    await _callback(PlayersCog.whois)(
        PlayersCog(SimpleNamespace(rcon=rcon, rcon_config=object())), interaction, guild_row=_guild()
    )

    description = interaction.followup.send.call_args.kwargs["embed"].description
    assert "Steve" in description
    assert "Online" in description


@pytest.mark.asyncio
async def test_locate_reports_offline_player(monkeypatch: pytest.MonkeyPatch) -> None:
    rcon = SimpleNamespace(get_player_pos=AsyncMock(return_value=None))
    interaction = _interaction()

    with pytest.raises(Exception, match="doesn't appear to be online"):
        await _callback(PlayersCog.locate)(
            PlayersCog(SimpleNamespace(rcon=rcon, rcon_config=object())),
            interaction,
            guild_row=_guild(),
            server_row=_server(),
            minecraft_username="Steve",
        )


@pytest.mark.asyncio
async def test_locate_sends_coordinates_and_copy_view(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(players, "get_session", _SessionContext)

    class UserRepo:
        def __init__(self, _session: object) -> None:
            pass

        async def get_by_minecraft(self, _username: str) -> object:
            return SimpleNamespace(discord_id=71)

    monkeypatch.setattr(players, "UserRepository", UserRepo)
    rcon = SimpleNamespace(get_player_pos=AsyncMock(return_value=(1, 64, -3, "minecraft:overworld")))
    interaction = _interaction()

    await _callback(PlayersCog.locate)(
        PlayersCog(SimpleNamespace(rcon=rcon, rcon_config=object())),
        interaction,
        guild_row=_guild(),
        server_row=_server(),
        minecraft_username="Steve",
    )

    view = interaction.followup.send.call_args.kwargs["view"]
    assert isinstance(view, CopyCoordinatesView)
    assert view._coords_text == "1 64 -3"


@pytest.mark.asyncio
async def test_copy_coordinates_posts_raw_code_block() -> None:
    view = CopyCoordinatesView(x=1, y=64, z=-3)
    interaction = _interaction()

    await view.copy.callback(interaction)

    interaction.response.send_message.assert_awaited_once_with("```1 64 -3```", ephemeral=True)
