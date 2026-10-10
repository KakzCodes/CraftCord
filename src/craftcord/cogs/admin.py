"""`/admin` command group: register-server, create-server, unregister-server, set-default.

Every command in this cog is gated by `@requires_admin` (`manage_guild`
permission or the configured bot-admin role).

Two ways to get a server onto a guild, kept deliberately separate:
- `register-server` *links* a server that already exists on the panel.
- `create-server` *provisions a brand-new one* via Pterodactyl's
  application API, from one fixed template, then links it the same way.
Both end up going through `ServerRepository.register`, so they share the
same uniqueness/tier-limit rules.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy.exc import IntegrityError

from craftcord.core import embeds
from craftcord.core.exceptions import (
    CraftCordError,
    PterodactylNotFound,
    ServerAlreadyRegistered,
    ServerNotRegistered,
    TierLimitExceeded,
)
from craftcord.db.models import Guild
from craftcord.db.repositories import ServerRepository
from craftcord.db.session import get_session
from craftcord.logging_config import get_logger
from craftcord.utils.decorators import audit, ensure_guild_registered, requires_admin

logger = get_logger(__name__)

_GRASS_TIER_SERVER_LIMIT = 1
_CONFIRM_TIMEOUT_SECONDS = 30.0


async def _check_grass_tier_limit(guild_row: Guild, server_repo: ServerRepository) -> None:
    """Raise `TierLimitExceeded` if adding another server would exceed the grass-tier limit.

    Shared by `register_server` and `create_server` — both add a row via
    the same `ServerRepository.register`, so both need the same check.
    """
    if guild_row.tier == "grass":
        existing_count = await server_repo.count_for_guild(guild_row.id)
        if existing_count >= _GRASS_TIER_SERVER_LIMIT:
            raise TierLimitExceeded()


class ConfirmView(discord.ui.View):
    """Generic Confirm/Cancel buttons, scoped to the original command invoker.

    A small, intentionally-duplicated sibling of `server.StopConfirmView` —
    the fixed file structure for this iteration has no shared "UI
    components" module to factor this into, and the two confirmations
    differ slightly (button label), so a second tiny view here is simpler
    than contorting one view to cover both call sites.
    """

    def __init__(self, *, author_id: int, confirm_label: str, timeout: float = _CONFIRM_TIMEOUT_SECONDS) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.confirmed: bool | None = None
        self.confirm_button.label = confirm_label

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only the invoking user may interact with these buttons."""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the person who ran this command can confirm it.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Confirm the pending action."""
        self.confirmed = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Cancel the pending action."""
        self.confirmed = False
        self.stop()
        await interaction.response.defer()


class AdminCog(commands.Cog, name="Admin"):
    """Implements the `/admin` command group."""

    group = app_commands.Group(name="admin", description="Administer CraftCord for this guild")

    def __init__(self, bot: commands.Bot) -> None:
        """Store the bot instance for access to the shared Pterodactyl client.

        Args:
            bot: The running `CraftCordBot`.
        """
        self.bot = bot

    @group.command(name="register-server", description="Register a Minecraft server with CraftCord")
    @app_commands.describe(
        name="A short name for this server (unique within this guild)",
        pterodactyl_uuid="The Pterodactyl identifier used in panel API paths",
        pterodactyl_numeric_id="The Pterodactyl numeric server ID",
        mc_version="The Minecraft version this server runs (default: 1.20.4)",
        is_default="Make this the guild's default server",
    )
    @audit("admin register-server")
    @ensure_guild_registered
    @requires_admin
    async def register_server(
        self,
        interaction: discord.Interaction,
        *,
        guild_row: Guild,
        name: str,
        pterodactyl_uuid: str,
        pterodactyl_numeric_id: int,
        mc_version: str = "1.20.4",
        is_default: bool = False,
    ) -> None:
        """Validate the server exists on the panel, then persist it (enforcing the grass-tier limit)."""
        await interaction.response.defer(ephemeral=True)

        try:
            await self.bot.pterodactyl.get_server(pterodactyl_uuid)
        except PterodactylNotFound as exc:
            raise CraftCordError(
                user_message=f"No server with UUID `{pterodactyl_uuid}` was found on the Pterodactyl panel."
            ) from exc

        async with get_session() as session:
            server_repo = ServerRepository(session)
            await _check_grass_tier_limit(guild_row, server_repo)

            try:
                await server_repo.register(
                    guild_row.id, name, pterodactyl_uuid, pterodactyl_numeric_id, mc_version, is_default
                )
            except IntegrityError as exc:
                raise ServerAlreadyRegistered() from exc

        embed = embeds.success_embed("Server Registered", f"**{name}** has been registered to this guild.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @group.command(name="create-server", description="Provision a brand-new Minecraft server for this guild")
    @app_commands.describe(
        name="A short name for this server (unique within this guild)",
        is_default="Make this the guild's default server",
    )
    @audit("admin create-server")
    @ensure_guild_registered
    @requires_admin
    async def create_server(
        self,
        interaction: discord.Interaction,
        *,
        guild_row: Guild,
        name: str,
        is_default: bool = False,
    ) -> None:
        """Provision a new server on the panel from the fixed creation template, then register it.

        Unlike `register_server`, there's no existing UUID to validate —
        the UUID/numeric ID come back from the panel's own creation
        response. The grass-tier limit and the name-uniqueness check both
        run *before* calling the panel, specifically to avoid the common
        case of creating a real (billable) server on the panel only to
        then fail to register it locally.

        NOTE: if `ServerRepository.register` still fails after that
        pre-check (e.g. a genuine race with a concurrent registration),
        the server that was just created on the panel is left in place,
        untracked by CraftCord — automatic cleanup on that failure path is
        a reasonable Iteration 2 follow-up, not implemented here.
        """
        await interaction.response.defer(ephemeral=True)

        if self.bot.pterodactyl_app is None or self.bot.creation_template is None:
            raise CraftCordError(
                user_message=(
                    "On-demand server creation isn't configured on this bot. An admin can either "
                    "set up the creation template in CraftCord's `.env`, or use "
                    "`/admin register-server` to link a server created manually on the panel."
                )
            )

        async with get_session() as session:
            server_repo = ServerRepository(session)
            await _check_grass_tier_limit(guild_row, server_repo)
            if await server_repo.get_by_name(guild_row.id, name) is not None:
                raise ServerAlreadyRegistered()

        created = await self.bot.pterodactyl_app.create_server(name, self.bot.creation_template)

        async with get_session() as session:
            server_repo = ServerRepository(session)
            try:
                await server_repo.register(
                    guild_row.id,
                    name,
                    created.identifier,
                    created.id,
                    self.bot.settings.pterodactyl_default_mc_version,
                    is_default,
                )
            except IntegrityError as exc:
                raise ServerAlreadyRegistered() from exc

        embed = embeds.success_embed(
            "Server Created",
            f"**{name}** is being provisioned on the panel now. Pterodactyl installs new servers "
            "in the background, which can take a few minutes — `/server status` will show it "
            "once it's ready.",
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @group.command(name="unregister-server", description="Remove a registered server")
    @app_commands.describe(name="The server to remove")
    @audit("admin unregister-server")
    @ensure_guild_registered
    @requires_admin
    async def unregister_server(
        self,
        interaction: discord.Interaction,
        *,
        guild_row: Guild,
        name: str,
    ) -> None:
        """Ask for confirmation, then permanently remove a registered server."""
        async with get_session() as session:
            server_row = await ServerRepository(session).get_by_name(guild_row.id, name)
        if server_row is None:
            raise ServerNotRegistered()

        view = ConfirmView(author_id=interaction.user.id, confirm_label="Unregister")
        await interaction.response.send_message(
            f"Are you sure you want to unregister **{server_row.name}**? "
            "This removes its session history and cannot be undone.",
            view=view,
            ephemeral=True,
        )
        await view.wait()

        if not view.confirmed:
            await interaction.edit_original_response(content="Unregister cancelled.", view=None)
            return

        async with get_session() as session:
            await ServerRepository(session).unregister(server_row.id)

        await interaction.edit_original_response(
            content=f"**{server_row.name}** has been unregistered.", view=None
        )

    @group.command(name="set-default", description="Set a server as this guild's default")
    @app_commands.describe(name="The server to make default")
    @audit("admin set-default")
    @ensure_guild_registered
    @requires_admin
    async def set_default(
        self,
        interaction: discord.Interaction,
        *,
        guild_row: Guild,
        name: str,
    ) -> None:
        """Set a server as the guild's default, clearing any prior default transactionally."""
        await interaction.response.defer(ephemeral=True)

        async with get_session() as session:
            repo = ServerRepository(session)
            server_row = await repo.get_by_name(guild_row.id, name)
            if server_row is None:
                raise ServerNotRegistered()
            await repo.set_default(guild_row.id, server_row.id)

        embed = embeds.success_embed(
            "Default Server Updated", f"**{name}** is now this guild's default server."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Entry point used by `bot.load_extension('craftcord.cogs.admin')`."""
    await bot.add_cog(AdminCog(bot))
