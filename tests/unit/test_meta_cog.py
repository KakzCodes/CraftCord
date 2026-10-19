"""Tests for the user-facing meta commands and help pagination."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from craftcord.cogs.meta import HelpView, MetaCog
from craftcord.core.exceptions import PterodactylError


def _interaction(user_id: int = 7) -> Mock:
    interaction = Mock(spec=discord.Interaction)
    interaction.user = Mock(spec=discord.User)
    interaction.user.id = user_id
    interaction.response = Mock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.followup = Mock()
    interaction.followup.send = AsyncMock()
    return interaction


@pytest.mark.asyncio
async def test_help_command_sends_first_category_page() -> None:
    interaction = _interaction()

    await MetaCog.help_command.callback.__wrapped__(None, interaction)

    kwargs = interaction.response.send_message.call_args.kwargs
    assert kwargs["ephemeral"] is True
    assert kwargs["embed"].title == "CraftCord Help — Server"
    assert isinstance(kwargs["view"], HelpView)


@pytest.mark.asyncio
async def test_help_view_paginates_and_restricts_other_users() -> None:
    view = HelpView(author_id=7)
    interaction = _interaction(user_id=8)

    assert await view.interaction_check(interaction) is False
    interaction.response.send_message.assert_awaited_once()

    interaction = _interaction()
    await view.next_page.callback(interaction)
    assert view.page_index == 1
    interaction.response.edit_message.assert_awaited_once()

    await view.previous_page.callback(interaction)
    assert view.page_index == 0


@pytest.mark.asyncio
async def test_ping_reports_gateway_and_panel_unreachable() -> None:
    pterodactyl = SimpleNamespace(list_servers=AsyncMock(side_effect=PterodactylError("offline")))
    cog = MetaCog(SimpleNamespace(latency=0.042, pterodactyl=pterodactyl))
    interaction = _interaction()

    await MetaCog.ping.callback.__wrapped__(cog, interaction)

    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    description = interaction.followup.send.call_args.kwargs["embed"].description
    assert "42ms" in description
    assert "unreachable" in description


@pytest.mark.asyncio
async def test_ping_reports_successful_panel_round_trip() -> None:
    pterodactyl = SimpleNamespace(list_servers=AsyncMock())
    cog = MetaCog(SimpleNamespace(latency=0.001, pterodactyl=pterodactyl))
    interaction = _interaction()

    await MetaCog.ping.callback.__wrapped__(cog, interaction)

    description = interaction.followup.send.call_args.kwargs["embed"].description
    assert "Pterodactyl API:**" in description
    assert "unreachable" not in description


@pytest.mark.asyncio
async def test_invite_rejects_bot_without_user() -> None:
    from craftcord.core.exceptions import CraftCordError

    cog = MetaCog(SimpleNamespace(user=None))
    with pytest.raises(CraftCordError):
        await MetaCog.invite.callback.__wrapped__(cog, _interaction())


@pytest.mark.asyncio
async def test_invite_builds_oauth_link() -> None:
    cog = MetaCog(SimpleNamespace(user=SimpleNamespace(id=1234)))
    interaction = _interaction()

    await MetaCog.invite.callback.__wrapped__(cog, interaction)

    description = interaction.followup.send.call_args.kwargs["embed"].description
    assert "discord.com/oauth2/authorize" in description
    assert "applications.commands" in description


@pytest.mark.asyncio
async def test_botinfo_includes_process_and_pool_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    from craftcord.cogs import meta

    class SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_: object) -> bool:
            return False

    class Repository:
        def __init__(self, _session: object) -> None:
            pass

        async def count_all(self) -> int:
            return 3

    monkeypatch.setattr(meta, "get_session", SessionContext)
    monkeypatch.setattr(meta, "ServerRepository", Repository)
    monkeypatch.setattr(
        meta,
        "get_engine",
        lambda: SimpleNamespace(pool=SimpleNamespace(checkedout=lambda: 1, size=lambda: 5)),
    )
    cog = MetaCog(
        SimpleNamespace(
            started_at=datetime.now(UTC) - timedelta(seconds=61), guilds=[1, 2]
        )
    )
    interaction = _interaction()

    await MetaCog.botinfo.callback.__wrapped__(cog, interaction)

    description = interaction.followup.send.call_args.kwargs["embed"].description
    assert "Guilds:** 2" in description
    assert "Registered Servers:** 3" in description
    assert "1/5 connections" in description
