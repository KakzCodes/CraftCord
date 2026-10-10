"""The `CraftCordBot` class: process lifecycle, shared clients, and top-level event handlers.

`setup_hook()` is where everything gets wired together — the database
engine, the long-lived HTTP/RCON clients (constructed in `__init__` so
they exist before `setup_hook` runs, but only actually opened lazily on
first use), the four cogs, the tree-level error handler, and the slash
command sync.
"""

from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from craftcord.config import Settings
from craftcord.core import embeds
from craftcord.core.mojang import MojangClient
from craftcord.core.pterodactyl import PterodactylApplicationClient, PterodactylClient, ServerCreationTemplate
from craftcord.core.rcon import RconClient, RconConfig
from craftcord.db.repositories import GuildRepository
from craftcord.db.session import dispose_engine, get_session, init_engine
from craftcord.logging_config import get_logger

logger = get_logger(__name__)

_COGS = ("server", "players", "admin", "meta")


class CraftCordBot(commands.Bot):
    """CraftCord's Discord bot process.

    Owns the long-lived `PterodactylClient`, `RconClient`, and
    `MojangClient` instances that every cog reaches via `self.bot.<name>`,
    plus the shared `RconConfig` built once from settings (see the NOTE in
    `core/rcon.py` about why RCON config is currently global rather than
    per-server).

    `pterodactyl_app` and `creation_template` back `/admin create-server`
    (on-demand server provisioning). Both are `None` unless every setting
    the template needs is configured — see
    `Settings.creation_template_is_configured` — so a deployment that only
    ever links pre-existing servers via `/admin register-server` never
    needs to set any of that up.
    """

    def __init__(self, settings: Settings) -> None:
        """Construct the bot and its shared clients.

        Args:
            settings: Application settings (already validated by
                `config.get_settings()`).
        """
        intents = discord.Intents.default()  # No message content needed for Iteration 1.
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)

        self.settings = settings
        self.started_at = datetime.now(timezone.utc)

        self.pterodactyl = PterodactylClient(settings.pterodactyl_url, settings.pterodactyl_api_key)
        self.rcon = RconClient()
        self.rcon_config = RconConfig(
            host=settings.rcon_host, port=settings.rcon_port, password=settings.rcon_password
        )
        self.mojang = MojangClient()

        self.pterodactyl_app: PterodactylApplicationClient | None = None
        self.creation_template: ServerCreationTemplate | None = None
        if settings.creation_template_is_configured():
            # The `is not None` assertions below are redundant with
            # creation_template_is_configured()'s own check, but keep this
            # block type-checker-clean without a bunch of `# type: ignore`s.
            assert settings.pterodactyl_application_api_key is not None
            assert settings.pterodactyl_owner_user_id is not None
            assert settings.pterodactyl_egg_id is not None
            assert settings.pterodactyl_docker_image is not None
            assert settings.pterodactyl_startup_command is not None
            assert settings.pterodactyl_memory_mb is not None
            assert settings.pterodactyl_disk_mb is not None

            self.pterodactyl_app = PterodactylApplicationClient(
                settings.pterodactyl_url, settings.pterodactyl_application_api_key
            )
            self.creation_template = ServerCreationTemplate(
                owner_user_id=settings.pterodactyl_owner_user_id,
                egg_id=settings.pterodactyl_egg_id,
                docker_image=settings.pterodactyl_docker_image,
                startup_command=settings.pterodactyl_startup_command,
                environment=settings.parsed_create_environment() or {},
                memory_mb=settings.pterodactyl_memory_mb,
                swap_mb=settings.pterodactyl_swap_mb,
                disk_mb=settings.pterodactyl_disk_mb,
                cpu_percent=settings.pterodactyl_cpu_percent,
                io_weight=settings.pterodactyl_io_weight,
                databases_limit=settings.pterodactyl_databases_limit,
                backups_limit=settings.pterodactyl_backups_limit,
                deploy_location_ids=settings.parsed_deploy_location_ids() or [],
            )

    async def setup_hook(self) -> None:
        """Wire up the engine, error handling, cogs, and slash command sync."""
        # 1. Initialise the engine.
        init_engine(self.settings)
        logger.info("on_demand_creation_configured", enabled=self.creation_template is not None)

        # 2. Register the audit-logging app command middleware: a tree-level
        #    catch-all for errors raised before a command's own @audit wrapper
        #    ever runs (e.g. Discord-side option parsing/transformation failures).
        self.tree.on_error = self._on_app_command_error

        # 3. Load cogs.
        for extension in _COGS:
            await self.load_extension(f"craftcord.cogs.{extension}")
        logger.info("cogs_loaded", cogs=_COGS)

        # 4. Sync slash commands — to the dev guild for fast iteration if
        #    configured, globally (can take up to an hour to propagate) otherwise.
        if self.settings.discord_guild_id_dev is not None:
            guild = discord.Object(id=self.settings.discord_guild_id_dev)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info(
                "slash_commands_synced",
                scope="dev_guild",
                guild_id=self.settings.discord_guild_id_dev,
                count=len(synced),
            )
        else:
            synced = await self.tree.sync()
            logger.info("slash_commands_synced", scope="global", count=len(synced))

    async def close(self) -> None:
        """Dispose the engine and close HTTP clients cleanly, then shut down the gateway connection."""
        await self.pterodactyl.aclose()
        if self.pterodactyl_app is not None:
            await self.pterodactyl_app.aclose()
        await self.mojang.aclose()
        await dispose_engine()
        await super().close()
        logger.info("bot_shutdown_complete")

    async def _on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """Tree-level fallback for app command errors that bypass a command's `@audit` wrapper."""
        logger.error("app_command_tree_error", error=str(error), exc_info=error)
        embed = embeds.error_embed("Something went wrong processing that command.")
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.HTTPException as exc:
            logger.warning("failed_to_send_tree_error_response", error=str(exc))

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Upsert the joining guild's row and post a welcome message."""
        async with get_session() as session:
            await GuildRepository(session).upsert(guild.id, guild.name)
        logger.info("guild_joined", guild_id=guild.id, guild_name=guild.name)

        channel = guild.system_channel
        if channel is None or guild.me is None or not channel.permissions_for(guild.me).send_messages:
            return

        embed = embeds.success_embed(
            "Thanks for adding CraftCord! 🌱",
            "Get started with `/admin register-server` to link a server you already have on the "
            "panel (or `/admin create-server` if on-demand creation is set up), then run `/help` "
            "to see everything CraftCord can do.",
        )
        try:
            await channel.send(embed=embed)
        except discord.HTTPException as exc:
            logger.warning("welcome_message_failed", guild_id=guild.id, error=str(exc))

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        """Log the removal. Deliberately soft: no rows are deleted.

        If the bot is re-invited later, the guild's registered servers,
        audit log, and session history are all still there.
        """
        logger.info("guild_removed", guild_id=guild.id, guild_name=guild.name)
