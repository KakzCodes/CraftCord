"""Repository for the `server_sessions` aggregate (uptime tracking)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_, select

from craftcord.db.models import ServerSession
from craftcord.db.repositories import BaseRepository


class SessionRepository(BaseRepository):
    """Data access for `ServerSession` rows."""

    async def open(self, server_id: int, started_by: int) -> ServerSession:
        """Open a new uptime session for a server (called from `/server start`).

        Args:
            server_id: The server's surrogate ID.
            started_by: The Discord snowflake of the user who started it.

        Returns:
            The newly created, still-open `ServerSession`.
        """
        session_row = ServerSession(server_id=server_id, started_by_discord_id=started_by)
        self.session.add(session_row)
        await self.session.flush()
        return session_row

    async def close_latest(self, server_id: int) -> None:
        """Close the most recent open session for a server (called from `/server stop`).

        A no-op if there is no open session — this can legitimately happen
        if the server was stopped directly via the panel rather than
        through CraftCord.

        Args:
            server_id: The server's surrogate ID.
        """
        stmt = (
            select(ServerSession)
            .where(ServerSession.server_id == server_id, ServerSession.stopped_at.is_(None))
            .order_by(ServerSession.started_at.desc())
            .limit(1)
        )
        open_session = await self.session.scalar(stmt)
        if open_session is not None:
            open_session.stopped_at = datetime.now(timezone.utc)
            await self.session.flush()

    async def total_uptime_seconds(self, server_id: int, since: datetime) -> float:
        """Sum uptime (in seconds) for a server across all sessions since `since`.

        NOTE: not in the original method list, but needed to implement
        `/server info`'s "uptime of bot's knowledge ... over last 7 days"
        field. Overlap with the `[since, now)` window is computed in
        Python rather than in SQL, which is fine at this data volume (a
        handful of sessions per server) and keeps the query simple.

        Args:
            server_id: The server's surrogate ID.
            since: The start of the window to sum uptime over.

        Returns:
            Total seconds the server was known to be running within the window.
        """
        stmt = select(ServerSession).where(
            ServerSession.server_id == server_id,
            or_(ServerSession.stopped_at.is_(None), ServerSession.stopped_at >= since),
        )
        result = await self.session.scalars(stmt)
        now = datetime.now(timezone.utc)

        total_seconds = 0.0
        for row in result:
            window_start = max(row.started_at, since)
            window_end = row.stopped_at or now
            if window_end > window_start:
                total_seconds += (window_end - window_start).total_seconds()
        return total_seconds
