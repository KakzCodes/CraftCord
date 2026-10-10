"""All `discord.Embed` construction lives here.

Cogs must never build a raw `discord.Embed` themselves — every embed a
user sees should come from one of these builder functions, so the visual
design system (colors, footer, thumbnail, timestamp) stays consistent
without being duplicated across four cog modules.

NOTE on `BLOCK_TEXTURE_URL`: the spec calls for a "block texture URL" as
the thumbnail on every server embed but doesn't pin a specific asset.
A grass-block texture is used as a generic, on-theme default; swap this
constant for a hosted asset of your choosing (or make it configurable per
guild tier) without touching any call site.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord

from craftcord.utils.formatters import format_bytes, format_player_list, format_uptime, format_usage_bar

if TYPE_CHECKING:
    from craftcord.core.pterodactyl import PterodactylResources
    from craftcord.db.models import Server

TIER_COLORS: dict[str, int] = {
    "grass": 0x4CAF50,
    "iron": 0x9E9E9E,
    "gold": 0xFFD700,
    "diamond": 0x00BCD4,
}
ERROR_COLOR = 0xF44336
INFO_COLOR = 0x2196F3
# Success embeds reuse the "grass" green — it's already the palette's
# positive-connotation color and there's no dedicated success entry.
SUCCESS_COLOR = TIER_COLORS["grass"]

BLOCK_TEXTURE_URL = "https://minecraft.wiki/images/Grass_Block_JE7_BE6.png"


def _footer_text(guild_name: str) -> str:
    return f"CraftCord • {guild_name}"


def _apply_server_chrome(embed: discord.Embed, server: Server, guild_name: str) -> discord.Embed:
    """Apply the shared server-embed chrome: title, thumbnail, footer, timestamp.

    Every embed that's *about* a specific server (status, action
    confirmations, etc.) goes through this so they look consistent.
    """
    embed.title = server.name
    embed.set_thumbnail(url=BLOCK_TEXTURE_URL)
    embed.set_footer(text=_footer_text(guild_name))
    embed.timestamp = datetime.now(timezone.utc)
    return embed


def success_embed(title: str, description: str) -> discord.Embed:
    """Build a generic success embed (green).

    Args:
        title: Short embed title.
        description: Body text.
    """
    return discord.Embed(title=title, description=description, color=SUCCESS_COLOR)


def error_embed(description: str) -> discord.Embed:
    """Build a generic error embed (red). Always sent ephemerally by callers.

    Args:
        description: The error's `user_message` (never a raw exception string).
    """
    return discord.Embed(title="Error", description=description, color=ERROR_COLOR)


def info_embed(title: str, description: str) -> discord.Embed:
    """Build a generic informational embed (blue).

    Args:
        title: Short embed title.
        description: Body text.
    """
    return discord.Embed(title=title, description=description, color=INFO_COLOR)


def server_status_embed(
    server: Server,
    resources: PterodactylResources,
    players: list[str],
) -> discord.Embed:
    """Build the `/server status` embed: CPU/RAM/disk bars, uptime, players, state.

    Args:
        server: The registered server (provides name, guild, tier for chrome/color).
        resources: Live resource usage fetched from Pterodactyl.
        players: Currently online player usernames, from RCON `list`.
    """
    color = TIER_COLORS.get(server.guild.tier, INFO_COLOR)
    embed = discord.Embed(color=color)
    _apply_server_chrome(embed, server, server.guild.name)

    embed.add_field(name="State", value=resources.state.title(), inline=True)
    embed.add_field(name="Players Online", value=str(len(players)), inline=True)
    embed.add_field(name="Uptime", value=format_uptime(resources.uptime_ms), inline=True)

    embed.add_field(name="CPU", value=f"{resources.cpu_percent:.1f}%", inline=False)
    embed.add_field(
        name="Memory",
        value=(
            f"{format_usage_bar(resources.memory_bytes, resources.memory_limit_bytes)}\n"
            f"{format_bytes(resources.memory_bytes)} / {format_bytes(resources.memory_limit_bytes)}"
        ),
        inline=False,
    )
    embed.add_field(
        name="Disk",
        value=(
            f"{format_usage_bar(resources.disk_bytes, resources.disk_limit_bytes)}\n"
            f"{format_bytes(resources.disk_bytes)} / {format_bytes(resources.disk_limit_bytes)}"
        ),
        inline=False,
    )
    return embed


def server_info_embed(server: Server, uptime_7d_seconds: float) -> discord.Embed:
    """Build the `/server info` embed: registered metadata, not live panel state.

    Args:
        server: The registered server.
        uptime_7d_seconds: Total known uptime (from `ServerSession` history)
            over the trailing 7 days, in seconds.
    """
    color = TIER_COLORS.get(server.guild.tier, INFO_COLOR)
    embed = discord.Embed(color=color)
    _apply_server_chrome(embed, server, server.guild.name)

    embed.add_field(name="Pterodactyl UUID", value=f"`{server.pterodactyl_uuid}`", inline=False)
    embed.add_field(name="Minecraft Version", value=server.mc_version, inline=True)
    embed.add_field(name="Guild Tier", value=server.guild.tier.title(), inline=True)
    embed.add_field(name="Default Server", value="Yes" if server.is_default else "No", inline=True)
    embed.add_field(
        name="Uptime (last 7 days)",
        value=format_uptime(int(uptime_7d_seconds * 1000)),
        inline=False,
    )
    return embed


def server_action_embed(server: Server, action: str, actor: discord.abc.User) -> discord.Embed:
    """Build the public confirmation embed for a start/stop/restart action.

    Args:
        server: The affected server.
        action: Past-tense-friendly action verb, e.g. `"started"`, `"stopped"`, `"restarted"`.
        actor: The Discord member who triggered the action.
    """
    color = TIER_COLORS.get(server.guild.tier, SUCCESS_COLOR)
    embed = discord.Embed(description=f"{actor.mention} {action} **{server.name}**.", color=color)
    _apply_server_chrome(embed, server, server.guild.name)
    return embed


def players_online_embed(server: Server, players: list[str], linked_map: dict[str, int]) -> discord.Embed:
    """Build the `/online` embed listing currently connected players.

    Args:
        server: The server the players are on (for chrome).
        players: Online Minecraft usernames.
        linked_map: Mapping of lowercased Minecraft username -> Discord user ID.
    """
    color = TIER_COLORS.get(server.guild.tier, INFO_COLOR)
    embed = discord.Embed(
        description=format_player_list(players, linked_map),
        color=color,
    )
    embed.title = f"Online — {server.name}"
    embed.set_footer(text=_footer_text(server.guild.name))
    embed.timestamp = datetime.now(timezone.utc)
    return embed


def player_located_embed(
    mc_username: str,
    discord_mention: str | None,
    x: int,
    y: int,
    z: int,
    dimension: str,
) -> discord.Embed:
    """Build the `/locate` embed showing a player's coordinates.

    Args:
        mc_username: The located player's Minecraft username.
        discord_mention: The linked Discord mention string, if the player
            has a linked account; otherwise `None`.
        x: X coordinate.
        y: Y coordinate.
        z: Z coordinate.
        dimension: The dimension identifier, e.g. `"minecraft:overworld"`.
    """
    who = f"{mc_username} ({discord_mention})" if discord_mention else mc_username
    embed = discord.Embed(
        title=f"📍 {mc_username}",
        description=f"{who} is in **{dimension}**.",
        color=INFO_COLOR,
    )
    embed.add_field(name="Coordinates", value=f"```{x} {y} {z}```", inline=False)
    embed.timestamp = datetime.now(timezone.utc)
    return embed
