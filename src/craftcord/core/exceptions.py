"""Domain exception hierarchy for CraftCord.

Every exception that should ever be presented to a Discord user carries a
`user_message` attribute: a short, human-friendly string that is safe to
render directly inside an ephemeral error embed. Internal details (stack
traces, raw HTTP bodies, SQL errors) must never leak into `user_message`;
those belong in the structured logs instead.

The `@audit` decorator (see `utils/decorators.py`) catches `CraftCordError`
and renders `user_message` to the invoking user, then re-logs the full
exception for operators.
"""

from __future__ import annotations


class CraftCordError(Exception):
    """Base class for all domain errors raised within CraftCord.

    Attributes:
        user_message: A short, human-friendly message safe to show in an
            ephemeral Discord embed. Falls back to `str(self)` if not
            provided explicitly.
    """

    default_message = "Something went wrong. Please try again, or contact an admin."

    def __init__(self, message: str | None = None, *, user_message: str | None = None) -> None:
        """Initialise the error.

        Args:
            message: Internal/developer-facing message (used for `str(exc)`
                and logging). Defaults to `user_message` or
                `default_message` if omitted.
            user_message: Human-friendly message safe to show to a Discord
                user. Defaults to `default_message` if omitted.
        """
        self.user_message = user_message or self.default_message
        super().__init__(message or self.user_message)


# --- Pterodactyl -------------------------------------------------------------


class PterodactylError(CraftCordError):
    """Base class for errors returned by the Pterodactyl panel API."""

    default_message = "The Pterodactyl panel returned an unexpected error."


class PterodactylNotFound(PterodactylError):
    """Raised when the panel returns 404 for a server/resource lookup."""

    default_message = "That server could not be found on the Pterodactyl panel."


class PterodactylAuthError(PterodactylError):
    """Raised when the panel returns 401/403 (bad or insufficient API key)."""

    default_message = (
        "CraftCord isn't authorized to talk to the Pterodactyl panel. "
        "An admin should check the configured API key."
    )


class PterodactylRateLimited(PterodactylError):
    """Raised when the panel returns 429 after exhausting retries."""

    default_message = "The Pterodactyl panel is rate-limiting requests right now. Please try again shortly."


class PterodactylValidationError(PterodactylError):
    """Raised when the panel rejects a request body as invalid (422).

    Most commonly hit when provisioning a new server from a misconfigured
    creation template (bad egg ID, docker image, or deploy location) — see
    `/admin create-server` and `core/pterodactyl.py::PterodactylApplicationClient`.
    """

    default_message = (
        "The Pterodactyl panel rejected this as invalid. An admin should double-check "
        "the server-creation template configuration."
    )


# --- RCON ---------------------------------------------------------------------


class RconError(CraftCordError):
    """Base class for RCON-related errors."""

    default_message = "Couldn't communicate with the Minecraft server's RCON interface."


class RconConnectionError(RconError):
    """Raised on socket-level failures connecting to the RCON interface."""

    default_message = (
        "Couldn't connect to the Minecraft server's RCON interface. "
        "It may be offline or RCON may be misconfigured."
    )


class RconCommandError(RconError):
    """Raised when an RCON command fails or returns an unparseable response."""

    default_message = "The Minecraft server rejected that RCON command."


# --- Mojang ---------------------------------------------------------------------


class MojangLookupError(CraftCordError):
    """Raised when the Mojang API fails with a server-side (5xx) error."""

    default_message = "The Mojang API is currently unavailable. Please try again later."


# --- Domain / application state --------------------------------------------------


class ServerNotRegistered(CraftCordError):
    """Raised when a guild has no matching registered server."""

    default_message = (
        "No matching server is registered for this guild. "
        "An admin can register one with `/admin register-server`."
    )


class ServerAlreadyRegistered(CraftCordError):
    """Raised when attempting to register a server name/UUID that already exists."""

    default_message = "A server with that name or Pterodactyl UUID is already registered."


class UserNotLinked(CraftCordError):
    """Raised when an action requires a linked Minecraft account that doesn't exist."""

    default_message = "That Discord account doesn't have a linked Minecraft username yet. Use `/link` first."


class PermissionDenied(CraftCordError):
    """Raised when a user lacks the permission required for a command."""

    default_message = "You don't have permission to use this command."


class TierLimitExceeded(CraftCordError):
    """Raised when an action would exceed the limits of the guild's current tier."""

    default_message = (
        "This action exceeds what's allowed on the guild's current tier. "
        "Grass-tier guilds are limited to 1 registered server."
    )
