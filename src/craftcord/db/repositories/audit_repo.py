"""Repository for the `audit_log` aggregate."""

from __future__ import annotations

from craftcord.db.models import AuditLog
from craftcord.db.repositories import BaseRepository


class AuditRepository(BaseRepository):
    """Data access for `AuditLog` rows. Append-only — there is no update/delete."""

    async def log(
        self,
        guild_id: int,
        discord_id: int,
        command_name: str,
        server_id: int | None,
        success: bool,
        error: str | None,
        duration_ms: int | None,
    ) -> None:
        """Write one audit row for a completed command invocation.

        Called from the `@audit` decorator, which wraps every slash
        command. Never raises on its own account for domain-logic
        failures — `error` is just the message to persist, not something
        this method inspects or acts on.

        Args:
            guild_id: The guild the command was invoked in.
            discord_id: The invoking user's Discord snowflake.
            command_name: The fully-qualified command name, e.g. `server start`.
            server_id: The affected server's surrogate ID, if applicable.
            success: Whether the command completed without a domain error.
            error: The error's `user_message`, if `success` is False.
            duration_ms: Wall-clock duration of the command handler, in milliseconds.
        """
        self.session.add(
            AuditLog(
                guild_id=guild_id,
                discord_id=discord_id,
                command_name=command_name,
                server_id=server_id,
                success=success,
                error=error,
                duration_ms=duration_ms,
            )
        )
        await self.session.flush()
