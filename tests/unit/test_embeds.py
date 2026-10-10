"""Unit tests for `craftcord.core.embeds`.

These assert embed *structure* — title, color, field names/values,
footer — rather than pinning exact rendering, so they stay stable against
unrelated copy tweaks while still catching layout regressions.
"""

from __future__ import annotations

import pytest

from craftcord.core import embeds
from craftcord.core.pterodactyl import PterodactylResources
from craftcord.db.models import Guild, Server


class _FakeUser:
    """Minimal duck-typed stand-in for `discord.abc.User` (just needs `.mention`)."""

    def __init__(self, mention: str) -> None:
        self.mention = mention


def _make_server(tier: str = "grass") -> Server:
    guild = Guild(id=1, name="Test Guild", tier=tier)
    server = Server(
        id=1,
        guild_id=1,
        name="Survival",
        pterodactyl_uuid="abc-123",
        pterodactyl_numeric_id=1,
        mc_version="1.20.4",
        is_default=True,
    )
    server.guild = guild
    return server


@pytest.mark.parametrize(
    "tier",
    ["grass", "iron", "gold", "diamond"],
)
def test_server_status_embed_uses_tier_color(tier: str) -> None:
    server = _make_server(tier)
    resources = PterodactylResources(
        state="running",
        cpu_percent=12.5,
        memory_bytes=512 * 1024 * 1024,
        memory_limit_bytes=2048 * 1024 * 1024,
        disk_bytes=1024 * 1024 * 1024,
        disk_limit_bytes=10 * 1024 * 1024 * 1024,
        uptime_ms=3_600_000,
    )

    embed = embeds.server_status_embed(server, resources, ["Alice", "Bob"])

    assert embed.color.value == embeds.TIER_COLORS[tier]
    assert embed.title == "Survival"
    assert embed.footer.text == "CraftCord • Test Guild"


def test_server_status_embed_field_layout_and_values() -> None:
    server = _make_server()
    resources = PterodactylResources(
        state="running",
        cpu_percent=0.0,
        memory_bytes=0,
        memory_limit_bytes=1,
        disk_bytes=0,
        disk_limit_bytes=1,
        uptime_ms=0,
    )

    embed = embeds.server_status_embed(server, resources, ["Alice"])

    field_names = [field.name for field in embed.fields]
    assert field_names == ["State", "Players Online", "Uptime", "CPU", "Memory", "Disk"]

    fields_by_name = {field.name: field.value for field in embed.fields}
    assert fields_by_name["State"] == "Running"
    assert fields_by_name["Players Online"] == "1"


def test_server_info_embed_field_layout() -> None:
    server = _make_server("iron")

    embed = embeds.server_info_embed(server, uptime_7d_seconds=3600.0)

    field_names = [field.name for field in embed.fields]
    assert field_names == [
        "Pterodactyl UUID",
        "Minecraft Version",
        "Guild Tier",
        "Default Server",
        "Uptime (last 7 days)",
    ]
    assert embed.color.value == embeds.TIER_COLORS["iron"]


def test_success_embed_uses_success_color() -> None:
    embed = embeds.success_embed("Done", "It worked.")

    assert embed.color.value == embeds.SUCCESS_COLOR
    assert embed.title == "Done"
    assert embed.description == "It worked."


def test_error_embed_uses_error_color() -> None:
    embed = embeds.error_embed("Something broke.")

    assert embed.color.value == embeds.ERROR_COLOR
    assert embed.description == "Something broke."


def test_server_action_embed_mentions_actor_and_action() -> None:
    server = _make_server()

    embed = embeds.server_action_embed(server, "started", _FakeUser("<@999>"))

    assert "<@999>" in embed.description
    assert "started" in embed.description
    assert "Survival" in embed.description


def test_players_online_embed_mentions_linked_players_only() -> None:
    server = _make_server()

    embed = embeds.players_online_embed(server, ["Alice", "Bob"], {"alice": 111})

    assert "- Alice (<@111>)" in embed.description
    assert "- Bob" in embed.description
    assert "Bob (<@" not in embed.description  # Bob has no link, so no mention should follow his name


def test_player_located_embed_contains_coordinates_and_dimension() -> None:
    embed = embeds.player_located_embed("Steve", "<@123>", 10, 64, -20, "minecraft:overworld")

    assert embed.fields[0].value == "```10 64 -20```"
    assert "minecraft:overworld" in embed.description
    assert "<@123>" in embed.description
