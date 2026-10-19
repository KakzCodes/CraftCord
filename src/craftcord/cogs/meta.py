"""Meta/utility commands: help, ping, invite, botinfo.

NOTE: the command descriptions/permissions shown by `/help` are hand-kept
in `_HELP_PAGES` below and should stay in sync with `COMMANDS.md`. For an
MVP this manual duplication is acceptable; a later iteration could
generate both from a single source of truth (e.g. by introspecting the
command tree at startup).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import discord
from discord import app_commands
from discord.ext import commands

import craftcord
from craftcord.core import embeds
from craftcord.core.exceptions import CraftCordError, PterodactylError
from craftcord.db.repositories import ServerRepository
from craftcord.db.session import get_engine, get_session
from craftcord.logging_config import get_logger
from craftcord.utils.decorators import audit
from craftcord.utils.formatters import format_uptime

logger = get_logger(__name__)

# (category, [(command, description, required permission), ...])
_HELP_PAGES: list[tuple[str, list[tuple[str, str, str]]]] = [
    (
        "Server",
        [
            ("/server start [server]", "Start a Minecraft server.", "None"),
            ("/server stop [server]", "Stop a Minecraft server (asks for confirmation).", "None"),
            ("/server restart [server]", "Restart a Minecraft server.", "None"),
            ("/server status [server]", "Show live CPU/RAM/disk/player status.", "None"),
            ("/server info [server]", "Show registered metadata and 7-day uptime.", "None"),
            ("/server list", "List all servers registered to this guild.", "None"),
            ("/server ip [server]", "Get the server's connect address.", "None"),
        ],
    ),
    (
        "Players",
        [
            ("/link <minecraft_username>", "Link your Discord account to a Minecraft username.", "None"),
            ("/unlink", "Remove your linked Minecraft account.", "None"),
            ("/whois [discord_user]", "Show a user's linked Minecraft account.", "None"),
            ("/online [server]", "List players currently online.", "None"),
            ("/locate <minecraft_username> [server]", "Find a player's coordinates.", "None"),
        ],
    ),
    (
        "Admin",
        [
            (
                "/admin register-server <name> <uuid> <numeric_id> [mc_version] [is_default]",
                "Link a Minecraft server that already exists on the panel.",
                "Manage Server (or bot-admin role)",
            ),
            (
                "/admin create-server <name> [is_default]",
                "Provision a brand-new server from a fixed template (if configured).",
                "Manage Server (or bot-admin role)",
            ),
            (
                "/admin unregister-server <name>",
                "Remove a registered server (asks for confirmation).",
                "Manage Server (or bot-admin role)",
            ),
            (
                "/admin set-default <name>",
                "Set a server as this guild's default.",
                "Manage Server (or bot-admin role)",
            ),
        ],
    ),
    (
        "Meta",
        [
            ("/help", "Show this help menu.", "None"),
            ("/ping", "Check gateway and Pterodactyl latency.", "None"),
            ("/invite", "Get the bot's invite link.", "None"),
            ("/botinfo", "Show version, uptime, and bot stats.", "None"),
        ],
    ),
]


class HelpView(discord.ui.View):
    """Paginated `/help` menu, one page per command category."""

    def __init__(self, *, author_id: int, timeout: float = 120.0) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.page_index = 0

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only the invoking user may page through this menu."""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the person who ran `/help` can navigate this menu.", ephemeral=True
            )
            return False
        return True

    def build_embed(self) -> discord.Embed:
        """Render the embed for the current page."""
        category, command_rows = _HELP_PAGES[self.page_index]
        description = "\n\n".join(
            f"**{name}**\n{desc}\n*Permission: {perm}*" for name, desc, perm in command_rows
        )
        embed = embeds.info_embed(f"CraftCord Help — {category}", description)
        embed.set_footer(text=f"Page {self.page_index + 1} of {len(_HELP_PAGES)}")
        return embed

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Go to the previous category page, wrapping around."""
        self.page_index = (self.page_index - 1) % len(_HELP_PAGES)
        await interaction.response.edit_message(embed=self.build_embed())

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Go to the next category page, wrapping around."""
        self.page_index = (self.page_index + 1) % len(_HELP_PAGES)
        await interaction.response.edit_message(embed=self.build_embed())


class MetaCog(commands.Cog, name="Meta"):
    """Implements `/help`, `/ping`, `/invite`, `/botinfo`."""

    def __init__(self, bot: commands.Bot) -> None:
        """Store the bot instance for access to shared clients and startup time.

        Args:
            bot: The running `CraftCordBot`.
        """
        self.bot = bot

    @app_commands.command(name="help", description="Show CraftCord's commands, grouped by category")
    @audit("help")
    async def help_command(self, interaction: discord.Interaction) -> None:
        """Show a paginated embed of every command, grouped by category."""
        view = HelpView(author_id=interaction.user.id)
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)

    @app_commands.command(name="ping", description="Check gateway and Pterodactyl latency")
    @audit("ping")
    async def ping(self, interaction: discord.Interaction) -> None:
        """Report Discord gateway latency and a live Pterodactyl API round-trip."""
        await interaction.response.defer(ephemeral=True)

        gateway_ms = round(self.bot.latency * 1000)

        pterodactyl_ms: int | None = None
        started = time.monotonic()
        try:
            await self.bot.pterodactyl.list_servers()
            pterodactyl_ms = int((time.monotonic() - started) * 1000)
        except PterodactylError as exc:
            logger.debug("ping_pterodactyl_unreachable", error=str(exc))

        lines = [f"**Gateway:** {gateway_ms}ms"]
        if pterodactyl_ms is not None:
            lines.append(f"**Pterodactyl API:** {pterodactyl_ms}ms")
        else:
            lines.append("**Pterodactyl API:** unreachable")

        embed = embeds.info_embed("Pong! 🏓", "\n".join(lines))
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="invite", description="Get the bot's invite link")
    @audit("invite")
    async def invite(self, interaction: discord.Interaction) -> None:
        """Build and show an OAuth2 invite link with the `bot` and `applications.commands` scopes."""
        await interaction.response.defer(ephemeral=True)

        if self.bot.user is None:
            raise CraftCordError(
                user_message="The bot isn't fully ready yet — please try again in a moment."
            )

        permissions = discord.Permissions(
            send_messages=True,
            embed_links=True,
            read_message_history=True,
            use_external_emojis=True,
        )
        url = discord.utils.oauth_url(
            self.bot.user.id, permissions=permissions, scopes=("bot", "applications.commands")
        )

        embed = embeds.info_embed(
            "Invite CraftCord", f"[Click here to invite CraftCord to your server]({url})"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="botinfo", description="Show CraftCord version, uptime, and stats")
    @audit("botinfo")
    async def botinfo(self, interaction: discord.Interaction) -> None:
        """Show version, process uptime, guild count, registered-server count, and DB pool status."""
        await interaction.response.defer(ephemeral=True)

        uptime_ms = int((datetime.now(UTC) - self.bot.started_at).total_seconds() * 1000)

        async with get_session() as session:
            total_servers = await ServerRepository(session).count_all()

        pool = get_engine().pool
        pool_status = f"{pool.checkedout()}/{pool.size()} connections in use"

        lines = [
            f"**Version:** {craftcord.__version__}",
            f"**Uptime:** {format_uptime(uptime_ms)}",
            f"**Guilds:** {len(self.bot.guilds)}",
            f"**Registered Servers:** {total_servers}",
            f"**DB Pool:** {pool_status}",
        ]
        embed = embeds.info_embed("CraftCord", "\n".join(lines))
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Entry point used by `bot.load_extension('craftcord.cogs.meta')`."""
    await bot.add_cog(MetaCog(bot))
