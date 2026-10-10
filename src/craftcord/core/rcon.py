"""Async wrapper around `mcrcon` (Minecraft RCON protocol).

`mcrcon` is a synchronous, blocking library, so every call into it is
pushed onto a thread via `asyncio.to_thread` — never call `MCRcon` directly
from an async context.

NOTE on per-server config: the schema (`servers` table) has no per-server
RCON columns — `RCON_HOST` / `RCON_PORT` / `RCON_PASSWORD` are single
global settings (see `config.py`). This is consistent with Iteration 1's
scope (grass tier is limited to one server per guild), but means every
`RconConfig` passed into this client currently comes from the same global
settings regardless of which `Server` row the caller is acting on. Proper
per-server RCON credentials would need a schema change and are a natural
Iteration 2 follow-up once multi-server support matures.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from mcrcon import MCRcon, MCRconException

from craftcord.core.exceptions import RconCommandError, RconConnectionError
from craftcord.logging_config import get_logger

logger = get_logger(__name__)

_RCON_TIMEOUT_SECONDS = 5
_MAX_CONCURRENT_COMMANDS_PER_SERVER = 5

_POS_PATTERN = re.compile(r"\[\s*([-\d.]+)d?\s*,\s*([-\d.]+)d?\s*,\s*([-\d.]+)d?\s*\]")
_DIMENSION_PATTERN = re.compile(r'"([^"]+)"')
_NO_ENTITY_MARKERS = ("no entity was found", "entity is not", "unknown entity")


@dataclass(frozen=True, slots=True)
class RconConfig:
    """Connection parameters for a single RCON server."""

    host: str
    port: int
    password: str


class RconClient:
    """Async-friendly wrapper around the blocking `mcrcon` library.

    A new TCP connection is opened for each call rather than pooled —
    Minecraft RCON connections are cheap to establish, and connection
    pooling (reusing one `MCRcon` instance across calls) would add
    complexity (thread-safety, reconnection-on-drop) that isn't worth it
    for this iteration's command volume. Revisit if RCON latency becomes a
    bottleneck.
    """

    def __init__(self) -> None:
        self._semaphores: dict[tuple[str, int], asyncio.Semaphore] = {}

    def _semaphore_for(self, cfg: RconConfig) -> asyncio.Semaphore:
        """Return (creating if needed) the per-server command semaphore."""
        key = (cfg.host, cfg.port)
        if key not in self._semaphores:
            self._semaphores[key] = asyncio.Semaphore(_MAX_CONCURRENT_COMMANDS_PER_SERVER)
        return self._semaphores[key]

    async def command(self, server_cfg: RconConfig, cmd: str) -> str:
        """Send a raw RCON command and return the server's text response.

        Args:
            server_cfg: Connection parameters for the target server.
            cmd: The raw console command, e.g. `"list"`.

        Returns:
            The server's raw text response.

        Raises:
            RconConnectionError: on socket-level failures (refused,
                timed out, or authentication rejected).
        """
        semaphore = self._semaphore_for(server_cfg)
        async with semaphore:
            return await asyncio.to_thread(self._command_sync, server_cfg, cmd)

    def _command_sync(self, cfg: RconConfig, cmd: str) -> str:
        """Blocking implementation of `command()`, run via `asyncio.to_thread`."""
        try:
            with MCRcon(cfg.host, cfg.password, port=cfg.port, timeout=_RCON_TIMEOUT_SECONDS) as mcr:
                return mcr.command(cmd)
        except MCRconException as exc:
            logger.debug("rcon_auth_or_protocol_error", host=cfg.host, port=cfg.port, error=str(exc))
            raise RconConnectionError(
                f"RCON login/protocol error for {cfg.host}:{cfg.port}: {exc}"
            ) from exc
        except OSError as exc:
            logger.debug("rcon_socket_error", host=cfg.host, port=cfg.port, error=str(exc))
            raise RconConnectionError(
                f"RCON socket error for {cfg.host}:{cfg.port}: {exc}"
            ) from exc

    async def list_players(self, cfg: RconConfig) -> list[str]:
        """Return the list of currently online player names, via RCON `list`.

        Args:
            cfg: Connection parameters for the target server.
        """
        response = await self.command(cfg, "list")
        # Vanilla/Paper format: "There are 2 of a max of 20 players online: Alice, Bob"
        if ":" not in response:
            return []
        _, _, names_part = response.partition(":")
        names = [n.strip() for n in names_part.split(",") if n.strip()]
        return names

    async def get_player_pos(self, cfg: RconConfig, username: str) -> tuple[int, int, int, str] | None:
        """Resolve a player's current position and dimension via RCON `data get entity`.

        Args:
            cfg: Connection parameters for the target server.
            username: The player's Minecraft username.

        Returns:
            `(x, y, z, dimension)` with integer-rounded coordinates, or
            `None` if the player is offline (no matching entity found).

        Raises:
            RconCommandError: if the server responds in a format this
                parser doesn't recognise.
        """
        pos_response = await self.command(cfg, f"data get entity {username} Pos")
        if any(marker in pos_response.lower() for marker in _NO_ENTITY_MARKERS):
            return None

        pos_match = _POS_PATTERN.search(pos_response)
        if pos_match is None:
            raise RconCommandError(f"Couldn't parse Pos NBT from RCON response: {pos_response!r}")
        x, y, z = (round(float(v)) for v in pos_match.groups())

        dim_response = await self.command(cfg, f"data get entity {username} Dimension")
        dim_match = _DIMENSION_PATTERN.search(dim_response)
        dimension = dim_match.group(1) if dim_match else "unknown"

        return (x, y, z, dimension)
