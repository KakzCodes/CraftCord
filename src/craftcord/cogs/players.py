"""Player-linking and in-game-info commands: link, unlink, whois, online, locate.

These are plain top-level slash commands (not a Discord command group) —
`players.py` is just the cog module that owns them.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from craftcord.core import embeds
from craftcord.core.exceptions import CraftCordError, MojangLookupError, RconError
from craftcord.db.models import Guild, Server
from craftcord.db.repositories import ServerRepository, UserRepository
from craftcord.db.session import get_session
from craftcord.logging_config import get_logger
from craftcord.utils.decorators import audit, ensure_guild_registered, requires_server

logger = get_logger(__name__)


class CopyCoordinatesView(discord.ui.View):
    """A single "Copy" button for `/locate`.

    NOTE: bots can't reach the OS clipboard directly — there's no Discord
    component that does that. This button instead posts the coordinates as
    an ephemeral, unformatted-for-embeds code block, which is much easier
    to long-press-and-copy (especially on mobile) than selecting text out
    of an embed field.
    """

    def __init__(self, *, x: int, y: int, z: int, timeout: float = 120.0) -> None:
        super().__init__(timeout=timeout)
        self._coords_text = f"{x} {y} {z}"

    @discord.ui.button(label="Copy", style=discord.ButtonStyle.secondary, emoji="📋")
    async def copy(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Post the raw coordinates as easy-to-copy ephemeral text."""
        await interaction.response.send_message(f"```{self._coords_text}```", ephemeral=True)


class PlayersCog(commands.Cog, name="Players"):
    """Implements `/link`, `/unlink`, `/whois`, `/online`, `/locate`."""

    def __init__(self, bot: commands.Bot) -> None:
        """Store the bot instance for access to shared clients.

        Args:
            bot: The running `CraftCordBot`.
        """
        self.bot = bot

    @app_commands.command(name="link", description="Link your Discord account to a Minecraft username")
    @app_commands.describe(minecraft_username="Your Minecraft Java Edition username")
    @audit("link")
    @ensure_guild_registered
    async def link(
        self,
        interaction: discord.Interaction,
        *,
        guild_row: Guild,
        minecraft_username: str,
    ) -> None:
        """Resolve the username's UUID via Mojang (best-effort) and persist the link.

        NOTE: account-linking is treated as a personal/ephemeral action
        (not a "server action"), so its confirmation is ephemeral rather
        than public — the spec's public-success rule is scoped to
        `/server` power actions.
        """
        await interaction.response.defer(ephemeral=True)

        mc_uuid: str | None = None
        try:
            mc_uuid = await self.bot.mojang.get_uuid(minecraft_username)
        except MojangLookupError as exc:
            logger.debug("link_mojang_unavailable", username=minecraft_username, error=str(exc))
            # Degrade gracefully: the link still succeeds without a resolved UUID.

        async with get_session() as session:
            await UserRepository(session).link(interaction.user.id, minecraft_username, mc_uuid)

        embed = embeds.success_embed(
            "Account Linked", f"Your Discord account is now linked to **{minecraft_username}**."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="unlink", description="Remove your linked Minecraft account")
    @audit("unlink")
    @ensure_guild_registered
    async def unlink(self, interaction: discord.Interaction, *, guild_row: Guild) -> None:
        """Remove the invoking user's Minecraft link, if one exists."""
        await interaction.response.defer(ephemeral=True)

        async with get_session() as session:
            await UserRepository(session).unlink(interaction.user.id)

        embed = embeds.success_embed("Account Unlinked", "Your Minecraft account link has been removed.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="whois", description="Show a Discord user's linked Minecraft account")
    @app_commands.describe(discord_user="Whose link to show (defaults to you)")
    @audit("whois")
    @ensure_guild_registered
    async def whois(
        self,
        interaction: discord.Interaction,
        *,
        guild_row: Guild,
        discord_user: discord.User | None = None,
    ) -> None:
        """Show a user's linked Minecraft username and best-effort online status.

        Online status is checked against the guild's default server (this
        command has no `[server]` option per spec). If the guild has no
        default server registered, or RCON is unreachable, status is shown
        as unknown rather than failing the whole command.
        """
        await interaction.response.defer()
        target = discord_user or interaction.user

        async with get_session() as session:
            link = await UserRepository(session).get_by_discord(target.id)

        if link is None:
            embed = embeds.info_embed(
                "Not Linked", f"{target.mention} hasn't linked a Minecraft account yet."
            )
            await interaction.followup.send(embed=embed)
            return

        status = "Unknown"
        async with get_session() as session:
            default_server = await ServerRepository(session).get_default_for_guild(guild_row.id)

        if default_server is not None:
            try:
                online_players = await self.bot.rcon.list_players(self.bot.rcon_config)
                is_online = link.minecraft_username.lower() in {p.lower() for p in online_players}
                status = "Online" if is_online else "Offline"
            except RconError as exc:
                logger.debug("whois_rcon_unavailable", error=str(exc))

        embed = embeds.info_embed(
            f"Linked Account — {target.display_name}",
            f"**Minecraft:** {link.minecraft_username}\n**Status:** {status}",
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="online", description="List players currently online on a server")
    @app_commands.describe(server="The server to check (defaults to this guild's default server)")
    @audit("online")
    @ensure_guild_registered
    @requires_server
    async def online(
        self,
        interaction: discord.Interaction,
        *,
        guild_row: Guild,
        server_row: Server,
        server: str | None = None,
    ) -> None:
        """List online players via RCON, mentioning any who are linked."""
        await interaction.response.defer()

        players = await self.bot.rcon.list_players(self.bot.rcon_config)

        linked_map: dict[str, int] = {}
        async with get_session() as session:
            user_repo = UserRepository(session)
            for player in players:
                link = await user_repo.get_by_minecraft(player)
                if link is not None:
                    linked_map[player.lower()] = link.discord_id

        embed = embeds.players_online_embed(server_row, players, linked_map)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="locate", description="Find a player's current coordinates")
    @app_commands.describe(
        minecraft_username="The player to locate",
        server="The server to check (defaults to this guild's default server)",
    )
    @audit("locate")
    @ensure_guild_registered
    @requires_server
    async def locate(
        self,
        interaction: discord.Interaction,
        *,
        guild_row: Guild,
        server_row: Server,
        minecraft_username: str,
        server: str | None = None,
    ) -> None:
        """Resolve a player's position/dimension via RCON and render it with a Copy button."""
        await interaction.response.defer()

        position = await self.bot.rcon.get_player_pos(self.bot.rcon_config, minecraft_username)
        if position is None:
            raise CraftCordError(
                user_message=f"**{minecraft_username}** doesn't appear to be online on that server."
            )
        x, y, z, dimension = position

        async with get_session() as session:
            link = await UserRepository(session).get_by_minecraft(minecraft_username)
        discord_mention = f"<@{link.discord_id}>" if link is not None else None

        embed = embeds.player_located_embed(minecraft_username, discord_mention, x, y, z, dimension)
        view = CopyCoordinatesView(x=x, y=y, z=z)
        await interaction.followup.send(embed=embed, view=view)


async def setup(bot: commands.Bot) -> None:
    """Entry point used by `bot.load_extension('craftcord.cogs.players')`."""
    await bot.add_cog(PlayersCog(bot))
