"""Repository for the `guilds` aggregate."""

from __future__ import annotations

from craftcord.db.models import Guild
from craftcord.db.repositories import BaseRepository


class GuildRepository(BaseRepository):
    """Data access for `Guild` rows."""

    async def upsert(self, discord_id: int, name: str) -> Guild:
        """Insert a guild row if it doesn't exist, else update its name.

        Called on every command invocation via `@ensure_guild_registered`
        and on `on_guild_join`, so this is on the hot path — kept as a
        single `get` + conditional `add`/mutate + `flush`, which is cheap
        and avoids a round trip to Postgres for the common case where the
        name hasn't changed.

        NOTE: this is a read-then-write, not an atomic `INSERT ... ON
        CONFLICT`. A true race (the same brand-new guild upserted by two
        concurrent commands in the same instant) is vanishingly unlikely
        in practice and would simply raise a unique-violation on the
        losing flush, which bubbles up as a retryable error rather than
        corrupting data.

        Args:
            discord_id: The Discord guild snowflake (used as primary key).
            name: The guild's current display name.

        Returns:
            The persisted `Guild` (new or existing).
        """
        guild = await self.session.get(Guild, discord_id)
        if guild is None:
            guild = Guild(id=discord_id, name=name)
            self.session.add(guild)
        elif guild.name != name:
            guild.name = name
        await self.session.flush()
        return guild

    async def get_by_id(self, discord_id: int) -> Guild | None:
        """Fetch a guild by its Discord snowflake, or `None` if unregistered.

        Args:
            discord_id: The Discord guild snowflake.
        """
        return await self.session.get(Guild, discord_id)
