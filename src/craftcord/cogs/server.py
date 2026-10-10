"""`/server` command group: start, stop, restart, status, info, list, ip.

All power actions talk to Pterodactyl via `bot.pterodactyl`; `/server
status` additionally queries RCON via `bot.rcon` for the live player list,
degrading gracefully (an empty player list) if RCON is unreachable (e.g.
the server is still starting up).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from craftcord.core import embeds
from craftcord.core.exceptions import RconError
from craftcord.db.models import Guild, Server
from craftcord.db.repositories import ServerRepository, SessionRepository
from craftcord.db.session import get_session
from craftcord.logging_config import get_logger
from craftcord.utils.decorators import audit, ensure_guild_registered, requires_server

logger = get_logger(__name__)

_UPTIME_WINDOW = timedelta(days=7)
_CONFIRM_TIMEOUT_SECONDS = 30.0


class StopConfirmView(discord.ui.View):
    """Confirmation buttons for the destructive `/server stop` action.

    Only the original command invoker may press either button;
    `interaction_check` rejects anyone else. `confirmed` is `None` until a
    button is pressed or the view times out (treated as a cancel).
    """

    def __init__(self, *, author_id: int, timeout: float = _CONFIRM_TIMEOUT_SECONDS) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.confirmed: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only the invoking user may interact with these buttons."""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the person who ran this command can confirm it.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Stop Server", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Confirm the stop action."""
        self.confirmed = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Cancel the stop action."""
        self.confirmed = False
        self.stop()
        await interaction.response.defer()


class ServerCog(commands.Cog, name="Server"):
    """Implements the `/server` command group."""

    group = app_commands.Group(name="server", description="Manage registered Minecraft servers")

    def __init__(self, bot: commands.Bot) -> None:
        """Store the bot instance so command bodies can reach shared clients.

        Args:
            bot: The running `CraftCordBot`, which owns the long-lived
                `pterodactyl`, `rcon`, and `mojang` client instances.
        """
        self.bot = bot

    @group.command(name="start", description="Start a Minecraft server")
    @app_commands.describe(server="The server to start (defaults to this guild's default server)")
    @audit("server start")
    @ensure_guild_registered
    @requires_server
    async def start(
        self,
        interaction: discord.Interaction,
        *,
        guild_row: Guild,
        server_row: Server,
        server: str | None = None,
    ) -> None:
        """Send a start power signal and open a new uptime session."""
        await interaction.response.defer()

        await self.bot.pterodactyl.send_power(server_row.pterodactyl_uuid, "start")

        async with get_session() as session:
            await SessionRepository(session).open(server_row.id, interaction.user.id)

        embed = embeds.server_action_embed(server_row, "started", interaction.user)
        await interaction.followup.send(embed=embed)

    @group.command(name="stop", description="Stop a Minecraft server")
    @app_commands.describe(server="The server to stop (defaults to this guild's default server)")
    @audit("server stop")
    @ensure_guild_registered
    @requires_server
    async def stop(
        self,
        interaction: discord.Interaction,
        *,
        guild_row: Guild,
        server_row: Server,
        server: str | None = None,
    ) -> None:
        """Ask for confirmation, then send a stop power signal and close the uptime session."""
        view = StopConfirmView(author_id=interaction.user.id)
        await interaction.response.send_message(
            f"Are you sure you want to stop **{server_row.name}**?", view=view, ephemeral=True
        )
        await view.wait()

        if not view.confirmed:
            await interaction.edit_original_response(content="Stop cancelled.", view=None)
            return

        await self.bot.pterodactyl.send_power(server_row.pterodactyl_uuid, "stop")

        async with get_session() as session:
            await SessionRepository(session).close_latest(server_row.id)

        await interaction.edit_original_response(content="Server stop confirmed.", view=None)

        # Public announcement (per the "success messages are public" rule) — the
        # confirmation prompt above is ephemeral, so the actual result gets its
        # own message in the channel.
        if interaction.channel is not None:
            embed = embeds.server_action_embed(server_row, "stopped", interaction.user)
            await interaction.channel.send(embed=embed)

    @group.command(name="restart", description="Restart a Minecraft server")
    @app_commands.describe(server="The server to restart (defaults to this guild's default server)")
    @audit("server restart")
    @ensure_guild_registered
    @requires_server
    async def restart(
        self,
        interaction: discord.Interaction,
        *,
        guild_row: Guild,
        server_row: Server,
        server: str | None = None,
    ) -> None:
        """Send a restart power signal."""
        await interaction.response.defer()

        await self.bot.pterodactyl.send_power(server_row.pterodactyl_uuid, "restart")

        embed = embeds.server_action_embed(server_row, "restarted", interaction.user)
        await interaction.followup.send(embed=embed)

    @group.command(name="status", description="Show live CPU/RAM/disk/player status for a server")
    @app_commands.describe(server="The server to check (defaults to this guild's default server)")
    @audit("server status")
    @ensure_guild_registered
    @requires_server
    async def status(
        self,
        interaction: discord.Interaction,
        *,
        guild_row: Guild,
        server_row: Server,
        server: str | None = None,
    ) -> None:
        """Fetch Pterodactyl resource usage and RCON player list, then render a status embed."""
        await interaction.response.defer()

        resources = await self.bot.pterodactyl.get_resources(server_row.pterodactyl_uuid)

        players: list[str] = []
        try:
            players = await self.bot.rcon.list_players(self.bot.rcon_config)
        except RconError as exc:
            # Degrade gracefully: the server may simply be starting/stopping,
            # in which case RCON isn't accepting connections yet.
            logger.debug("status_rcon_unavailable", server_id=server_row.id, error=str(exc))

        embed = embeds.server_status_embed(server_row, resources, players)
        await interaction.followup.send(embed=embed)

    @group.command(name="info", description="Show registered metadata for a server")
    @app_commands.describe(server="The server to inspect (defaults to this guild's default server)")
    @audit("server info")
    @ensure_guild_registered
    @requires_server
    async def info(
        self,
        interaction: discord.Interaction,
        *,
        guild_row: Guild,
        server_row: Server,
        server: str | None = None,
    ) -> None:
        """Render registered metadata plus 7-day known uptime, without hitting the panel."""
        await interaction.response.defer()

        since = datetime.now(timezone.utc) - _UPTIME_WINDOW
        async with get_session() as session:
            uptime_seconds = await SessionRepository(session).total_uptime_seconds(server_row.id, since)

        embed = embeds.server_info_embed(server_row, uptime_seconds)
        await interaction.followup.send(embed=embed)

    @group.command(name="list", description="List all servers registered to this guild")
    @audit("server list")
    @ensure_guild_registered
    async def list_servers(self, interaction: discord.Interaction, *, guild_row: Guild) -> None:
        """List every server registered to the invoking guild."""
        await interaction.response.defer()

        async with get_session() as session:
            servers = await ServerRepository(session).list_for_guild(guild_row.id)

        if not servers:
            embed = embeds.info_embed(
                "Registered Servers",
                "No servers are registered yet. An admin can add one with `/admin register-server`.",
            )
            await interaction.followup.send(embed=embed)
            return

        lines = [f"{'⭐ ' if s.is_default else ''}**{s.name}** — {s.mc_version}" for s in servers]
        embed = embeds.info_embed("Registered Servers", "\n".join(lines))
        await interaction.followup.send(embed=embed)

    @group.command(name="ip", description="Get the connect address for a server")
    @app_commands.describe(server="The server to look up (defaults to this guild's default server)")
    @audit("server ip")
    @ensure_guild_registered
    @requires_server
    async def ip(
        self,
        interaction: discord.Interaction,
        *,
        guild_row: Guild,
        server_row: Server,
        server: str | None = None,
    ) -> None:
        """Resolve and display the server's connect address from Pterodactyl."""
        await interaction.response.defer()

        pterodactyl_server = await self.bot.pterodactyl.get_server(server_row.pterodactyl_uuid)
        allocation = pterodactyl_server.default_allocation

        if allocation is None:
            embed = embeds.error_embed("This server has no network allocation configured on the panel.")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        embed = embeds.info_embed(
            f"Connect to {server_row.name}",
            f"```{allocation.ip}:{allocation.port}```",
        )
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    """Entry point used by `bot.load_extension('craftcord.cogs.server')`."""
    await bot.add_cog(ServerCog(bot))
