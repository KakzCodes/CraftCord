"""Pure formatting helpers for rendering numbers as Discord-friendly strings.

Every function here is side-effect-free and has no dependency on discord.py
or the database, so they're trivially unit-testable in isolation (see
`tests/unit/test_embeds.py`, which exercises these indirectly through the
embeds that use them).
"""

from __future__ import annotations

_BYTE_UNITS = ("B", "KB", "MB", "GB", "TB")


def format_uptime(ms: int) -> str:
    """Format a millisecond duration as a compact `"3d 4h 12m"`-style string.

    Args:
        ms: Duration in milliseconds. Negative values are treated as 0.

    Returns:
        A compact human-readable duration, e.g. `"3d 4h 12m"`, `"45m"`, or
        `"<1m"` for durations under a minute.
    """
    total_seconds = max(ms, 0) // 1000
    days, remainder = divmod(total_seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, _ = divmod(remainder, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")

    if not parts:
        return "<1m"
    return " ".join(parts)


def format_bytes(b: int) -> str:
    """Format a byte count using binary (1024-based) units, e.g. `"512.3 MB"`.

    Args:
        b: Byte count. Negative values are treated as 0.
    """
    value = float(max(b, 0))
    unit = _BYTE_UNITS[0]
    for unit in _BYTE_UNITS:  # noqa: B007 - `unit` is read after the loop, once it settles on the final unit
        if value < 1024.0:
            break
        value /= 1024.0
    if unit == "B":
        return f"{int(value)} {unit}"
    return f"{value:.1f} {unit}"


def format_usage_bar(used: int, total: int, width: int = 10) -> str:
    """Render a text progress bar, e.g. `"████░░░░░░ 42%"`.

    Args:
        used: The current/used amount.
        total: The maximum amount. If 0 or negative, the bar renders empty
            at 0% rather than raising a division error (a server with no
            configured resource limit shouldn't crash status rendering).
        width: Number of block characters in the bar.

    Returns:
        A string combining filled (`█`) and empty (`░`) blocks followed by
        a percentage, clamped to `[0, 100]`.
    """
    if total <= 0:
        percent = 0
    else:
        percent = round((used / total) * 100)
    percent = max(0, min(100, percent))

    filled = round((percent / 100) * width)
    filled = max(0, min(width, filled))
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar} {percent}%"


def format_player_list(players: list[str], linked: dict[str, int]) -> str:
    """Render online players as a newline-separated list, mentioning linked users.

    Args:
        players: Online Minecraft usernames, as returned by RCON `list`.
        linked: Mapping of lowercased Minecraft username -> Discord user ID,
            for players who have run `/link`.

    Returns:
        A newline-separated string, one entry per player, in the form
        `"- Notch (<@123456789>)"` for linked players or `"- Notch"` for
        unlinked ones. Returns `"*No players online.*"` if `players` is empty.
    """
    if not players:
        return "*No players online.*"

    lines: list[str] = []
    for player in players:
        discord_id = linked.get(player.lower())
        if discord_id is not None:
            lines.append(f"- {player} (<@{discord_id}>)")
        else:
            lines.append(f"- {player}")
    return "\n".join(lines)
