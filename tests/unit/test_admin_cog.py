"""Tests for administrative server registration and provisioning commands."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from craftcord.cogs import admin as admin_module
from craftcord.cogs.admin import AdminCog
from craftcord.core.exceptions import CraftCordError, ServerNotRegistered, TierLimitExceeded
from craftcord.db.models import Guild


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
    interaction.edit_original_response = AsyncMock()
    return interaction


def _callback(command: object):
    callback = command.callback
    while hasattr(callback, "__wrapped__"):
        callback = callback.__wrapped__
    return callback


def _guild(tier: str = "grass") -> Guild:
    return Guild(id=1, name="Test Guild", tier=tier)


@pytest.mark.asyncio
async def test_register_server_validates_panel_then_persists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin_module, "get_session", _SessionContext)
    registrations: list[tuple[object, ...]] = []

    class ServerRepo:
        def __init__(self, _session: object) -> None:
            pass

        async def count_for_guild(self, _guild_id: int) -> int:
            return 0

        async def register(self, *args: object) -> None:
            registrations.append(args)

    monkeypatch.setattr(admin_module, "ServerRepository", ServerRepo)
    ptero = SimpleNamespace(get_server=AsyncMock())
    interaction = _interaction()

    await _callback(AdminCog.register_server)(
        AdminCog(SimpleNamespace(pterodactyl=ptero)),
        interaction,
        guild_row=_guild(),
        name="Survival",
        pterodactyl_uuid="srv-uuid",
        pterodactyl_numeric_id=99,
        mc_version="1.21",
        is_default=True,
    )

    ptero.get_server.assert_awaited_once_with("srv-uuid")
    assert registrations == [(1, "Survival", "srv-uuid", 99, "1.21", True)]
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_server_checks_limit_before_panel_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_module, "get_session", _SessionContext)

    class ServerRepo:
        def __init__(self, _session: object) -> None:
            pass

        async def count_for_guild(self, _guild_id: int) -> int:
            return 1

    monkeypatch.setattr(admin_module, "ServerRepository", ServerRepo)
    create_server = AsyncMock()
    bot = SimpleNamespace(
        pterodactyl_app=SimpleNamespace(create_server=create_server),
        creation_template=object(),
    )
    interaction = _interaction()

    with pytest.raises(TierLimitExceeded):
        await _callback(AdminCog.create_server)(
            AdminCog(bot), interaction, guild_row=_guild(), name="Second"
        )

    create_server.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_server_reports_missing_provisioning_configuration() -> None:
    ptero_app = SimpleNamespace(create_server=AsyncMock())
    cog = AdminCog(
        SimpleNamespace(pterodactyl_app=ptero_app, creation_template=None)
    )

    with pytest.raises(CraftCordError, match="isn't configured"):
        await _callback(AdminCog.create_server)(cog, _interaction(), guild_row=_guild(), name="Survival")

    ptero_app.create_server.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_server_provisions_then_registers_panel_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_module, "get_session", _SessionContext)
    registered: list[tuple[object, ...]] = []

    class ServerRepo:
        def __init__(self, _session: object) -> None:
            pass

        async def count_for_guild(self, _guild_id: int) -> int:
            return 0

        async def get_by_name(self, _guild_id: int, _name: str) -> None:
            return None

        async def register(self, *args: object) -> None:
            registered.append(args)

    monkeypatch.setattr(admin_module, "ServerRepository", ServerRepo)
    template = object()
    created = SimpleNamespace(identifier="created-uuid", id=98)
    create_server = AsyncMock(return_value=created)
    bot = SimpleNamespace(
        pterodactyl_app=SimpleNamespace(create_server=create_server),
        creation_template=template,
        settings=SimpleNamespace(pterodactyl_default_mc_version="1.21.4"),
    )
    interaction = _interaction()

    await _callback(AdminCog.create_server)(
        AdminCog(bot), interaction, guild_row=_guild(tier="paid"), name="New World", is_default=True
    )

    create_server.assert_awaited_once_with("New World", template)
    assert registered == [(1, "New World", "created-uuid", 98, "1.21.4", True)]
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_default_updates_existing_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin_module, "get_session", _SessionContext)
    calls: list[tuple[int, int]] = []

    class ServerRepo:
        def __init__(self, _session: object) -> None:
            pass

        async def get_by_name(self, guild_id: int, name: str) -> object:
            assert (guild_id, name) == (1, "Survival")
            return SimpleNamespace(id=10)

        async def set_default(self, guild_id: int, server_id: int) -> None:
            calls.append((guild_id, server_id))

    monkeypatch.setattr(admin_module, "ServerRepository", ServerRepo)
    interaction = _interaction()

    await _callback(AdminCog.set_default)(
        AdminCog(None), interaction, guild_row=_guild(), name="Survival"
    )

    assert calls == [(1, 10)]
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_default_rejects_unknown_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin_module, "get_session", _SessionContext)

    class ServerRepo:
        def __init__(self, _session: object) -> None:
            pass

        async def get_by_name(self, _guild_id: int, _name: str) -> None:
            return None

    monkeypatch.setattr(admin_module, "ServerRepository", ServerRepo)

    with pytest.raises(ServerNotRegistered):
        await _callback(AdminCog.set_default)(
            AdminCog(None), _interaction(), guild_row=_guild(), name="Missing"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmed", [False, True])
async def test_unregister_requires_confirmation_before_deleting(
    monkeypatch: pytest.MonkeyPatch, confirmed: bool
) -> None:
    monkeypatch.setattr(admin_module, "get_session", _SessionContext)
    removed: list[int] = []

    class ServerRepo:
        def __init__(self, _session: object) -> None:
            pass

        async def get_by_name(self, _guild_id: int, _name: str) -> object:
            return SimpleNamespace(id=10, name="Survival")

        async def unregister(self, server_id: int) -> None:
            removed.append(server_id)

    class Confirm:
        def __init__(self, **_: object) -> None:
            self.confirmed = confirmed

        async def wait(self) -> None:
            return None

    monkeypatch.setattr(admin_module, "ServerRepository", ServerRepo)
    monkeypatch.setattr(admin_module, "ConfirmView", Confirm)
    interaction = _interaction()

    await _callback(AdminCog.unregister_server)(
        AdminCog(None), interaction, guild_row=_guild(), name="Survival"
    )

    assert removed == ([10] if confirmed else [])
    interaction.edit_original_response.assert_awaited_once()
