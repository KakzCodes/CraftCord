"""Composable decorators for slash command callbacks.

These four decorators compose around every cog command. Applied in code,
top to bottom, they must appear in this order so that application order
(bottom-most decorator wraps the raw function first) matches the intended
runtime nesting of "outermost = audit":

    @app_commands.command(name="start", description="...")
    @audit("server start")
    @ensure_guild_registered
    @requires_server
    async def start(
        self,
        interaction: discord.Interaction,
        *,
        guild_row: Guild,
        server_row: Server,
        server: str | None = None,
    ) -> None:
        ...

At runtime, `audit` runs first (it's the outermost call Discord makes),
then delegates to `ensure_guild_registered`, which delegates to
`requires_server`, which finally calls the real command body.

### Why `guild_row` / `server_row` don't become phantom Discord options

`ensure_guild_registered` and `requires_server` each *inject* a keyword
argument into the function they wrap (`guild_row`, `server_row`
respectively) — but those must never show up as slash-command options when
`@app_commands.command()` introspects the fully-decorated callback via
`inspect.signature()`.

Each injecting decorator explicitly sets `wrapper.__signature__` to the
inner function's signature *minus* the parameter it injects.
`inspect.signature()` stops unwrapping the `__wrapped__` chain (which
`functools.wraps` maintains) as soon as it finds an object with an
explicit `__signature__`, so the final signature `app_commands.command()`
sees is the raw command's signature with every injected row parameter
removed — exactly the public option list Discord should build. Commands
must declare `guild_row` / `server_row` as keyword-only parameters (after
a bare `*`) so their position never collides with option defaults; see the
example above.

`audit` and `requires_admin` don't inject anything, so they need no
`__signature__` override — the default unwrap behaviour already exposes
the right signature to whatever wraps them.
"""

from __future__ import annotations

import functools
import inspect
import time
from collections.abc import Awaitable, Callable
from typing import Any

import discord

from craftcord.core.embeds import error_embed
from craftcord.core.exceptions import CraftCordError, PermissionDenied, ServerNotRegistered
from craftcord.db.models import Guild
from craftcord.db.repositories import AuditRepository, GuildRepository, ServerRepository
from craftcord.db.session import get_session
from craftcord.logging_config import get_logger

logger = get_logger(__name__)

# NOTE: no per-guild admin-role configuration exists in Iteration 1's schema
# (no column on `guilds`, no env var) — `manage_guild` is the primary gate.
# This conventionally-named role is checked as the documented "or a
# configured bot-admin role" fallback until a real per-guild setting exists.
ADMIN_ROLE_NAME = "CraftCord Admin"

CogCommand = Callable[..., Awaitable[None]]


def _strip_param(sig: inspect.Signature, name: str) -> inspect.Signature:
    """Return `sig` with the parameter named `name` removed, if present."""
    remaining = [p for p_name, p in sig.parameters.items() if p_name != name]
    return sig.replace(parameters=remaining)


def audit(command_name: str) -> Callable[[CogCommand], CogCommand]:
    """Wrap a command: records success/failure/duration, renders domain errors.

    Any `CraftCordError` raised by the wrapped call (or anything it calls)
    is caught here, its `user_message` is shown to the user in an
    ephemeral embed, and the failure is written to `audit_log`. Any other,
    unexpected exception is treated the same way but with a generic
    message and a full traceback at ERROR level — commands should never
    bubble a raw exception up to discord.py.

    Args:
        command_name: The fully-qualified command name to record, e.g.
            `"server start"`.
    """

    def decorator(func: CogCommand) -> CogCommand:
        @functools.wraps(func)
        async def wrapper(self: Any, interaction: discord.Interaction, *args: Any, **kwargs: Any) -> None:
            started = time.monotonic()
            success = True
            error_message: str | None = None

            try:
                await func(self, interaction, *args, **kwargs)
            except CraftCordError as exc:
                success = False
                error_message = exc.user_message
                logger.warning("command_domain_error", command_name=command_name, error=str(exc))
                await _respond_error(interaction, exc.user_message)
            except Exception as exc:  # last-resort handler: commands must never crash the gateway task
                success = False
                error_message = "An unexpected error occurred."
                logger.error(
                    "command_unhandled_error", command_name=command_name, error=str(exc), exc_info=True
                )
                await _respond_error(interaction, error_message)
            finally:
                duration_ms = int((time.monotonic() - started) * 1000)
                await _write_audit_log(interaction, command_name, kwargs, success, error_message, duration_ms)

        return wrapper

    return decorator


async def _respond_error(interaction: discord.Interaction, message: str) -> None:
    """Send `message` as an ephemeral error embed, handling both fresh and deferred interactions."""
    embed = error_embed(message)
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except discord.HTTPException as exc:
        logger.warning("failed_to_send_error_response", error=str(exc))


async def _write_audit_log(
    interaction: discord.Interaction,
    command_name: str,
    kwargs: dict[str, Any],
    success: bool,
    error_message: str | None,
    duration_ms: int,
) -> None:
    """Persist one audit_log row for a completed command invocation."""
    if interaction.guild_id is None:
        return  # Guild-only commands; nothing meaningful to log for a DM invocation.

    async with get_session() as session:
        server_id = await _resolve_server_id_for_audit(session, interaction.guild_id, kwargs)
        await AuditRepository(session).log(
            guild_id=interaction.guild_id,
            discord_id=interaction.user.id,
            command_name=command_name,
            server_id=server_id,
            success=success,
            error=error_message,
            duration_ms=duration_ms,
        )


async def _resolve_server_id_for_audit(session: Any, guild_id: int, kwargs: dict[str, Any]) -> int | None:
    """Best-effort lookup of the server a command acted on, for the audit row.

    Reuses the same name-or-default resolution as `@requires_server`. This
    is deliberately forgiving: a lookup failure here must never prevent
    the audit row (or the user-facing response) from going out, so any
    exception is swallowed and logged as a missing `server_id`.
    """
    try:
        repo = ServerRepository(session)
        server_name = kwargs.get("server")
        if server_name:
            server_row = await repo.get_by_name(guild_id, server_name)
        else:
            server_row = await repo.get_default_for_guild(guild_id)
    except Exception as exc:  # audit logging is best-effort; never block on it
        logger.debug("audit_server_resolution_failed", error=str(exc))
        return None
    return server_row.id if server_row is not None else None


def ensure_guild_registered(func: CogCommand) -> CogCommand:
    """Upsert the invoking guild's row before running the command; injects `guild_row`.

    Raises:
        CraftCordError: if invoked outside a guild (e.g. a DM), which
            should never happen given these are guild-only commands, but
            is handled defensively rather than assumed away.
    """

    @functools.wraps(func)
    async def wrapper(self: Any, interaction: discord.Interaction, *args: Any, **kwargs: Any) -> None:
        if interaction.guild is None:
            raise CraftCordError(user_message="This command can only be used inside a server.")

        async with get_session() as session:
            guild_row = await GuildRepository(session).upsert(interaction.guild.id, interaction.guild.name)

        await func(self, interaction, *args, guild_row=guild_row, **kwargs)

    wrapper.__signature__ = _strip_param(inspect.signature(func), "guild_row")  # type: ignore[attr-defined]
    return wrapper


def requires_server(func: CogCommand) -> CogCommand:
    """Resolve `server_row` from the optional `server` option; injects `server_row`.

    Falls back to the guild's default server when `server` is omitted.

    Raises:
        ServerNotRegistered: if no server matches the given name, or (when
            `server` was omitted) the guild has no default server set.
    """

    @functools.wraps(func)
    async def wrapper(
        self: Any,
        interaction: discord.Interaction,
        *args: Any,
        guild_row: Guild,
        server: str | None = None,
        **kwargs: Any,
    ) -> None:
        async with get_session() as session:
            repo = ServerRepository(session)
            if server is not None:
                server_row = await repo.get_by_name(guild_row.id, server)
            else:
                server_row = await repo.get_default_for_guild(guild_row.id)

        if server_row is None:
            raise ServerNotRegistered()

        await func(self, interaction, *args, guild_row=guild_row, server_row=server_row, server=server, **kwargs)

    wrapper.__signature__ = _strip_param(inspect.signature(func), "server_row")  # type: ignore[attr-defined]
    return wrapper


def requires_admin(func: CogCommand) -> CogCommand:
    """Require `manage_guild` permission or the configured bot-admin role.

    Raises:
        PermissionDenied: if the invoking member has neither.
    """

    @functools.wraps(func)
    async def wrapper(self: Any, interaction: discord.Interaction, *args: Any, **kwargs: Any) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member):
            # Shouldn't happen for guild-only commands, but fail closed rather than assume.
            raise PermissionDenied()

        has_permission = member.guild_permissions.manage_guild
        has_admin_role = any(role.name == ADMIN_ROLE_NAME for role in member.roles)
        if not (has_permission or has_admin_role):
            raise PermissionDenied()

        await func(self, interaction, *args, **kwargs)

    return wrapper
