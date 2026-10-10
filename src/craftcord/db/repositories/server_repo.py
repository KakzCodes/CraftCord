"""Repository for the `servers` aggregate."""

from __future__ import annotations

from sqlalchemy import func, select, update

from craftcord.db.models import Server
from craftcord.db.repositories import BaseRepository


class ServerRepository(BaseRepository):
    """Data access for `Server` rows."""

    async def register(
        self,
        guild_id: int,
        name: str,
        uuid: str,
        numeric_id: int,
        mc_version: str,
        is_default: bool,
    ) -> Server:
        """Register a new server for a guild.

        If `is_default` is True, any existing default for the guild is
        cleared first (in the same flush) so the partial unique index on
        `(guild_id) WHERE is_default` is never violated.

        Args:
            guild_id: The owning guild's Discord snowflake.
            name: User-facing server name, unique per guild.
            uuid: The Pterodactyl short UUID identifying the server.
            numeric_id: The Pterodactyl numeric server ID.
            mc_version: The Minecraft version string.
            is_default: Whether this should become the guild's default server.

        Returns:
            The newly created `Server`.

        Raises:
            sqlalchemy.exc.IntegrityError: if `name` or `uuid` collides with
                an existing row. Callers should catch this and translate it
                into `ServerAlreadyRegistered` (see `cogs/admin.py`).
        """
        if is_default:
            await self._clear_default(guild_id)

        server = Server(
            guild_id=guild_id,
            name=name,
            pterodactyl_uuid=uuid,
            pterodactyl_numeric_id=numeric_id,
            mc_version=mc_version,
            is_default=is_default,
        )
        self.session.add(server)
        await self.session.flush()
        return server

    async def get_default_for_guild(self, guild_id: int) -> Server | None:
        """Return the guild's default server, or `None` if it has none set.

        Args:
            guild_id: The guild's Discord snowflake.
        """
        stmt = select(Server).where(Server.guild_id == guild_id, Server.is_default.is_(True))
        return await self.session.scalar(stmt)

    async def get_by_name(self, guild_id: int, name: str) -> Server | None:
        """Look up a server by its user-facing name within a guild.

        Args:
            guild_id: The guild's Discord snowflake.
            name: The server's user-facing name (case-sensitive match).
        """
        stmt = select(Server).where(Server.guild_id == guild_id, Server.name == name)
        return await self.session.scalar(stmt)

    async def list_for_guild(self, guild_id: int) -> list[Server]:
        """Return every server registered to a guild, ordered by name.

        Args:
            guild_id: The guild's Discord snowflake.
        """
        stmt = select(Server).where(Server.guild_id == guild_id).order_by(Server.name)
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def count_all(self) -> int:
        """Return the total number of servers registered across every guild.

        NOTE: not in the original method list, but needed to implement
        `/botinfo`'s "number of registered servers" field.
        """
        stmt = select(func.count()).select_from(Server)
        result = await self.session.scalar(stmt)
        return result or 0

    async def count_for_guild(self, guild_id: int) -> int:
        """Return the number of servers registered to a guild.

        Used by `@requires_admin`-gated registration to enforce the
        grass-tier limit of 1 server per guild.

        Args:
            guild_id: The guild's Discord snowflake.
        """
        servers = await self.list_for_guild(guild_id)
        return len(servers)

    async def unregister(self, server_id: int) -> None:
        """Delete a server by its surrogate ID.

        Cascades to `server_sessions` via `ON DELETE CASCADE`; sets
        `audit_log.server_id` to NULL via `ON DELETE SET NULL`.

        Args:
            server_id: The server's surrogate primary key.
        """
        server = await self.session.get(Server, server_id)
        if server is not None:
            await self.session.delete(server)
            await self.session.flush()

    async def set_default(self, guild_id: int, server_id: int) -> None:
        """Set `server_id` as the guild's default, clearing any prior default.

        Both updates happen in the same flush so the partial unique index
        is never transiently violated.

        Args:
            guild_id: The guild's Discord snowflake.
            server_id: The surrogate ID of the server to make default.
        """
        await self._clear_default(guild_id)
        server = await self.session.get(Server, server_id)
        if server is not None:
            server.is_default = True
        await self.session.flush()

    async def _clear_default(self, guild_id: int) -> None:
        """Clear `is_default` on every server for a guild (internal helper)."""
        stmt = (
            update(Server)
            .where(Server.guild_id == guild_id, Server.is_default.is_(True))
            .values(is_default=False)
        )
        await self.session.execute(stmt)
