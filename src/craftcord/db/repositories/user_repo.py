"""Repository for the `users` (Minecraft account link) aggregate."""

from __future__ import annotations

from sqlalchemy import select

from craftcord.db.models import User
from craftcord.db.repositories import BaseRepository


class UserRepository(BaseRepository):
    """Data access for `User` rows (Discord ↔ Minecraft account links)."""

    async def link(self, discord_id: int, mc_username: str, mc_uuid: str | None) -> User:
        """Create or update a Discord user's linked Minecraft account.

        The username is always lowercased before storage so the UNIQUE
        constraint on `minecraft_username` behaves case-insensitively, per
        the schema's documented convention.

        Args:
            discord_id: The linking Discord user's snowflake.
            mc_username: The Minecraft username (will be lowercased).
            mc_uuid: The Mojang UUID, if already resolved; `None` if Mojang
                lookup failed or was skipped and will be backfilled later.

        Returns:
            The persisted `User`.
        """
        normalized_username = mc_username.lower()
        user = await self.session.get(User, discord_id)
        if user is None:
            user = User(
                discord_id=discord_id,
                minecraft_username=normalized_username,
                minecraft_uuid=mc_uuid,
            )
            self.session.add(user)
        else:
            user.minecraft_username = normalized_username
            user.minecraft_uuid = mc_uuid
        await self.session.flush()
        return user

    async def unlink(self, discord_id: int) -> None:
        """Remove a Discord user's Minecraft link, if one exists.

        Args:
            discord_id: The Discord user's snowflake.
        """
        user = await self.session.get(User, discord_id)
        if user is not None:
            await self.session.delete(user)
            await self.session.flush()

    async def get_by_discord(self, discord_id: int) -> User | None:
        """Look up a link by Discord user ID.

        Args:
            discord_id: The Discord user's snowflake.
        """
        return await self.session.get(User, discord_id)

    async def get_by_minecraft(self, mc_username: str) -> User | None:
        """Look up a link by Minecraft username (case-insensitive).

        Args:
            mc_username: The Minecraft username to search for (any case).
        """
        stmt = select(User).where(User.minecraft_username == mc_username.lower())
        return await self.session.scalar(stmt)
