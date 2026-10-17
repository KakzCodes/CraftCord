"""Unit tests for `craftcord.utils.decorators`.

This is the project's one genuinely "clever" piece of machinery: four
decorators that inject keyword arguments into a command handler while
keeping Discord's slash-command option list clean via `__signature__`
manipulation. It's flagged throughout the project's documentation as
"reasoned through but never tested against a real discord.py tree" — this
file is that test.

The database is never touched: `get_session` and every repository class
used inside `decorators.py` are monkeypatched with small fakes, so these
tests run in isolation and don't need Postgres. `discord.Interaction` and
`discord.Member` are faked with `Mock(spec=...)`, which makes `isinstance`
checks against the real discord.py classes pass — important because
`@requires_admin` does exactly that check.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from craftcord.core.exceptions import CraftCordError, PermissionDenied, ServerNotRegistered
from craftcord.db.models import Guild, Server
from craftcord.utils import decorators as decorators_module
from craftcord.utils.decorators import audit, ensure_guild_registered, requires_admin, requires_server

# --- Fakes / helpers ---------------------------------------------------------


class _FakeAsyncSessionCtx:
    """Stand-in for the object `db.session.get_session()` normally returns."""

    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


def _fake_get_session() -> _FakeAsyncSessionCtx:
    return _FakeAsyncSessionCtx()


@pytest.fixture(autouse=True)
def _patch_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every decorator under test calls `get_session()` — fake it out globally."""
    monkeypatch.setattr(decorators_module, "get_session", _fake_get_session)


def _guild_repo_returning(guild: Guild) -> type:
    class _FakeGuildRepository:
        def __init__(self, session: object) -> None:
            pass

        async def upsert(self, discord_id: int, name: str) -> Guild:
            return guild

    return _FakeGuildRepository


def _server_repo_with(by_name: dict[str, Server] | None = None, default: Server | None = None) -> type:
    names = by_name or {}

    class _FakeServerRepository:
        def __init__(self, session: object) -> None:
            pass

        async def get_by_name(self, guild_id: int, name: str) -> Server | None:
            return names.get(name)

        async def get_default_for_guild(self, guild_id: int) -> Server | None:
            return default

    return _FakeServerRepository


def _audit_repo_recording(sink: list[dict]) -> type:
    class _FakeAuditRepository:
        def __init__(self, session: object) -> None:
            pass

        async def log(self, **kwargs: object) -> None:
            sink.append(kwargs)

    return _FakeAuditRepository


def _make_interaction(*, guild: Mock | None = None, user: Mock | None = None) -> Mock:
    interaction = Mock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.guild_id = guild.id if guild is not None else None
    interaction.user = user if user is not None else Mock(spec=discord.User)
    interaction.response = Mock()
    interaction.response.is_done = Mock(return_value=False)
    interaction.response.send_message = AsyncMock()
    interaction.followup = Mock()
    interaction.followup.send = AsyncMock()
    return interaction


def _make_guild(id_: int = 1, name: str = "Test Guild") -> Mock:
    guild = Mock(spec=discord.Guild)
    guild.id = id_
    guild.name = name
    return guild


def _make_member(*, manage_guild: bool, role_names: list[str] | None = None) -> Mock:
    member = Mock(spec=discord.Member)
    member.id = 42
    member.guild_permissions = SimpleNamespace(manage_guild=manage_guild)
    roles = []
    for n in role_names or []:
        role = Mock()
        role.name = n
        roles.append(role)
    member.roles = roles
    return member


# --- @requires_admin ---------------------------------------------------------


async def test_requires_admin_allows_manage_guild_permission() -> None:
    called = []

    @requires_admin
    async def handler(self: object, interaction: discord.Interaction) -> None:
        called.append(True)

    interaction = _make_interaction(user=_make_member(manage_guild=True))
    await handler(None, interaction)

    assert called == [True]


async def test_requires_admin_allows_configured_role_without_permission() -> None:
    called = []

    @requires_admin
    async def handler(self: object, interaction: discord.Interaction) -> None:
        called.append(True)

    member = _make_member(manage_guild=False, role_names=["CraftCord Admin"])
    await handler(None, _make_interaction(user=member))

    assert called == [True]


async def test_requires_admin_denies_without_permission_or_role() -> None:
    @requires_admin
    async def handler(self: object, interaction: discord.Interaction) -> None:
        pytest.fail("handler should not have been called")

    member = _make_member(manage_guild=False, role_names=["Member"])

    with pytest.raises(PermissionDenied):
        await handler(None, _make_interaction(user=member))


async def test_requires_admin_denies_non_member_user() -> None:
    @requires_admin
    async def handler(self: object, interaction: discord.Interaction) -> None:
        pytest.fail("handler should not have been called")

    # A plain discord.User (e.g. in a DM) is never a discord.Member.
    with pytest.raises(PermissionDenied):
        await handler(None, _make_interaction(user=Mock(spec=discord.User)))


# --- @ensure_guild_registered -------------------------------------------------


async def test_ensure_guild_registered_injects_guild_row(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_guild = Guild(id=1, name="Test Guild", tier="grass")
    monkeypatch.setattr(decorators_module, "GuildRepository", _guild_repo_returning(fake_guild))

    received = {}

    @ensure_guild_registered
    async def handler(self: object, interaction: discord.Interaction, *, guild_row: Guild) -> None:
        received["guild_row"] = guild_row

    await handler(None, _make_interaction(guild=_make_guild()))

    assert received["guild_row"] is fake_guild


async def test_ensure_guild_registered_strips_guild_row_from_public_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(decorators_module, "GuildRepository", _guild_repo_returning(Guild(id=1, name="G")))

    @ensure_guild_registered
    async def handler(self: object, interaction: discord.Interaction, *, guild_row: Guild) -> None:
        pass

    public_params = list(inspect.signature(handler).parameters)

    assert "guild_row" not in public_params
    assert public_params == ["self", "interaction"]


async def test_ensure_guild_registered_raises_outside_a_guild(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(decorators_module, "GuildRepository", _guild_repo_returning(Guild(id=1, name="G")))

    @ensure_guild_registered
    async def handler(self: object, interaction: discord.Interaction, *, guild_row: Guild) -> None:
        pytest.fail("handler should not have been called")

    with pytest.raises(CraftCordError):
        await handler(None, _make_interaction(guild=None))


# --- @requires_server ---------------------------------------------------------


async def test_requires_server_resolves_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_server = Server(id=10, guild_id=1, name="Survival", pterodactyl_uuid="abc", pterodactyl_numeric_id=1)
    repo = _server_repo_with(by_name={"Survival": fake_server})
    monkeypatch.setattr(decorators_module, "ServerRepository", repo)

    received = {}

    @requires_server
    async def handler(
        self: object,
        interaction: discord.Interaction,
        *,
        guild_row: Guild,
        server_row: Server,
        server: str | None = None,
    ) -> None:
        received["server_row"] = server_row

    await handler(None, _make_interaction(), guild_row=Guild(id=1, name="G"), server="Survival")

    assert received["server_row"] is fake_server


async def test_requires_server_falls_back_to_default_when_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_default = Server(id=11, guild_id=1, name="Default", pterodactyl_uuid="def", pterodactyl_numeric_id=2)
    monkeypatch.setattr(decorators_module, "ServerRepository", _server_repo_with(default=fake_default))

    received = {}

    @requires_server
    async def handler(
        self: object,
        interaction: discord.Interaction,
        *,
        guild_row: Guild,
        server_row: Server,
        server: str | None = None,
    ) -> None:
        received["server_row"] = server_row

    await handler(None, _make_interaction(), guild_row=Guild(id=1, name="G"))

    assert received["server_row"] is fake_default


async def test_requires_server_raises_when_nothing_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(decorators_module, "ServerRepository", _server_repo_with())

    @requires_server
    async def handler(
        self: object,
        interaction: discord.Interaction,
        *,
        guild_row: Guild,
        server_row: Server,
        server: str | None = None,
    ) -> None:
        pytest.fail("handler should not have been called")

    with pytest.raises(ServerNotRegistered):
        await handler(None, _make_interaction(), guild_row=Guild(id=1, name="G"))


async def test_requires_server_strips_server_row_but_keeps_server_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(decorators_module, "ServerRepository", _server_repo_with())

    @requires_server
    async def handler(
        self: object,
        interaction: discord.Interaction,
        *,
        guild_row: Guild,
        server_row: Server,
        server: str | None = None,
    ) -> None:
        pass

    public_params = list(inspect.signature(handler).parameters)

    assert "server_row" not in public_params
    assert "server" in public_params
    assert "guild_row" in public_params  # only the next layer up strips this one


# --- @audit ---------------------------------------------------------------


async def test_audit_logs_success(monkeypatch: pytest.MonkeyPatch) -> None:
    logged: list[dict] = []
    monkeypatch.setattr(decorators_module, "AuditRepository", _audit_repo_recording(logged))
    monkeypatch.setattr(decorators_module, "ServerRepository", _server_repo_with())

    @audit("ping")
    async def handler(self: object, interaction: discord.Interaction) -> None:
        return None

    await handler(None, _make_interaction(guild=_make_guild()))

    assert len(logged) == 1
    assert logged[0]["command_name"] == "ping"
    assert logged[0]["success"] is True
    assert logged[0]["error"] is None


async def test_audit_converts_domain_error_to_ephemeral_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    logged: list[dict] = []
    monkeypatch.setattr(decorators_module, "AuditRepository", _audit_repo_recording(logged))
    monkeypatch.setattr(decorators_module, "ServerRepository", _server_repo_with())

    @audit("server start")
    async def handler(self: object, interaction: discord.Interaction) -> None:
        raise ServerNotRegistered()

    interaction = _make_interaction(guild=_make_guild())
    await handler(None, interaction)  # must NOT raise -- audit swallows domain errors

    interaction.response.send_message.assert_awaited_once()
    assert interaction.response.send_message.call_args.kwargs["ephemeral"] is True
    assert logged[0]["success"] is False
    assert "register" in logged[0]["error"].lower()


async def test_audit_handles_unexpected_exception_without_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    logged: list[dict] = []
    monkeypatch.setattr(decorators_module, "AuditRepository", _audit_repo_recording(logged))
    monkeypatch.setattr(decorators_module, "ServerRepository", _server_repo_with())

    @audit("ping")
    async def handler(self: object, interaction: discord.Interaction) -> None:
        raise ValueError("boom")

    interaction = _make_interaction(guild=_make_guild())
    await handler(None, interaction)  # must NOT raise

    assert logged[0]["success"] is False
    interaction.response.send_message.assert_awaited_once()


async def test_audit_uses_followup_when_response_already_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(decorators_module, "AuditRepository", _audit_repo_recording([]))
    monkeypatch.setattr(decorators_module, "ServerRepository", _server_repo_with())

    @audit("server stop")
    async def handler(self: object, interaction: discord.Interaction) -> None:
        raise ServerNotRegistered()

    interaction = _make_interaction(guild=_make_guild())
    interaction.response.is_done = Mock(return_value=True)

    await handler(None, interaction)

    interaction.followup.send.assert_awaited_once()
    interaction.response.send_message.assert_not_awaited()


# --- Full stack, composed exactly as every real command does ------------------


async def test_full_decorator_stack_composes_correctly(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: @audit + @ensure_guild_registered + @requires_server, stacked
    exactly as every real `/server` command stacks them, resolving a server by
    name, injecting both rows, and exposing only `(self, interaction, server)`
    to whatever would introspect it for Discord's option list.
    """
    fake_guild = Guild(id=1, name="Test Guild", tier="grass")
    fake_server = Server(id=10, guild_id=1, name="Survival", pterodactyl_uuid="abc", pterodactyl_numeric_id=1)
    logged: list[dict] = []

    monkeypatch.setattr(decorators_module, "GuildRepository", _guild_repo_returning(fake_guild))
    monkeypatch.setattr(decorators_module, "ServerRepository", _server_repo_with(default=fake_server))
    monkeypatch.setattr(decorators_module, "AuditRepository", _audit_repo_recording(logged))

    received = {}

    @audit("server start")
    @ensure_guild_registered
    @requires_server
    async def start(
        self: object,
        interaction: discord.Interaction,
        *,
        guild_row: Guild,
        server_row: Server,
        server: str | None = None,
    ) -> None:
        received["guild_row"] = guild_row
        received["server_row"] = server_row

    # This is exactly what app_commands.command() would see when building
    # the slash-command option list -- neither injected row should appear.
    assert list(inspect.signature(start).parameters) == ["self", "interaction", "server"]

    await start(None, _make_interaction(guild=_make_guild()))

    assert received["guild_row"] is fake_guild
    assert received["server_row"] is fake_server
    assert logged[0]["success"] is True
    assert logged[0]["command_name"] == "server start"
