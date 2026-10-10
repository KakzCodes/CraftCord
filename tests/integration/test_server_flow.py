"""End-to-end integration test: register a guild, register a server, then
drive the same calls `/server start` makes (Pterodactyl mocked via respx)
and assert a `ServerSession` was opened and an `audit_log` row was written.

NOTE on scope: this exercises the repository + `PterodactylClient` calls
`cogs/server.py::ServerCog.start` makes, against a real (throwaway)
Postgres and a mocked Pterodactyl API, rather than constructing a real
`discord.Interaction` — faking a slice of discord.py's gateway/HTTP
internals would add a lot of test code for little additional signal, since
the actual business logic under test lives in the repositories and the
Pterodactyl client, not in Discord's own plumbing.
"""

from __future__ import annotations

import httpx
from sqlalchemy import select

from craftcord.core.pterodactyl import PterodactylClient
from craftcord.db.models import AuditLog
from craftcord.db.repositories import AuditRepository, GuildRepository, ServerRepository, SessionRepository


async def test_server_start_flow_opens_session_and_writes_audit_row(async_session, respx_mock) -> None:
    guild_repo = GuildRepository(async_session)
    server_repo = ServerRepository(async_session)
    session_repo = SessionRepository(async_session)
    audit_repo = AuditRepository(async_session)

    guild = await guild_repo.upsert(discord_id=1001, name="Integration Test Guild")
    server = await server_repo.register(
        guild.id, "Survival", "pterodactyl-uuid-123", 42, "1.20.4", is_default=True
    )

    power_route = respx_mock.post(
        f"https://panel.test/api/client/servers/{server.pterodactyl_uuid}/power"
    ).mock(return_value=httpx.Response(204))

    pterodactyl = PterodactylClient("https://panel.test", "ptlc_test_key")
    invoking_discord_id = 2002
    success = True
    error: str | None = None
    opened_session = None

    try:
        # --- mirrors ServerCog.start's body -----------------------------
        await pterodactyl.send_power(server.pterodactyl_uuid, "start")
        opened_session = await session_repo.open(server.id, invoking_discord_id)
    except Exception as exc:  # pragma: no cover - this test path should always succeed
        success = False
        error = str(exc)
        raise
    finally:
        await audit_repo.log(
            guild_id=guild.id,
            discord_id=invoking_discord_id,
            command_name="server start",
            server_id=server.id,
            success=success,
            error=error,
            duration_ms=10,
        )
        await pterodactyl.aclose()

    assert power_route.called
    assert opened_session is not None
    assert opened_session.stopped_at is None
    assert opened_session.started_by_discord_id == invoking_discord_id

    audit_rows = (
        await async_session.scalars(
            select(AuditLog).where(
                AuditLog.guild_id == guild.id, AuditLog.command_name == "server start"
            )
        )
    ).all()
    assert len(audit_rows) == 1
    assert audit_rows[0].success is True
    assert audit_rows[0].server_id == server.id
    assert audit_rows[0].discord_id == invoking_discord_id
