"""Keep the implemented Discord slash-command inventory explicit and stable."""

from __future__ import annotations

from discord import app_commands

from craftcord.cogs.admin import AdminCog
from craftcord.cogs.meta import MetaCog
from craftcord.cogs.players import PlayersCog
from craftcord.cogs.server import ServerCog


def test_cogs_register_the_documented_twenty_commands() -> None:
    expected = {
        "/server start",
        "/server stop",
        "/server restart",
        "/server status",
        "/server info",
        "/server list",
        "/server ip",
        "/link",
        "/unlink",
        "/whois",
        "/online",
        "/locate",
        "/admin register-server",
        "/admin create-server",
        "/admin unregister-server",
        "/admin set-default",
        "/help",
        "/ping",
        "/invite",
        "/botinfo",
    }

    actual: set[str] = set()
    for cog in (ServerCog, PlayersCog, AdminCog, MetaCog):
        for command in cog.__cog_app_commands__:
            if isinstance(command, app_commands.Group):
                actual.update(f"/{command.name} {child.name}" for child in command.commands)
            else:
                actual.add(f"/{command.name}")

    assert actual == expected
    assert len(actual) == 20
