"""Application configuration.

Settings are loaded from environment variables (and a local `.env` file in
development) using `pydantic-settings`. Validation happens at import/call
time of `get_settings()`, so misconfiguration fails fast and loudly at
startup rather than surfacing as a confusing error later.

Use `get_settings()` everywhere a `Settings` instance is needed. It is
memoized with `functools.lru_cache`, so the environment is only parsed once
per process.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings, sourced from the environment.

    Any required field that is missing or malformed raises a
    `pydantic.ValidationError` when `Settings()` is constructed, which
    `get_settings()` lets propagate so the bot fails fast on startup
    instead of crashing later with a confusing runtime error.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- Discord ---------------------------------------------------------
    discord_token: str = Field(..., alias="DISCORD_TOKEN")
    discord_guild_id_dev: int | None = Field(default=None, alias="DISCORD_GUILD_ID_DEV")

    # --- Pterodactyl (client API — power actions, status, existing servers) -----
    pterodactyl_url: str = Field(..., alias="PTERODACTYL_URL")
    pterodactyl_api_key: str = Field(..., alias="PTERODACTYL_API_KEY")

    # --- Pterodactyl (application API — on-demand server creation) -----------
    # All optional: `/admin create-server` is only enabled once every one of
    # these is set (see Settings.creation_template_is_configured()). A
    # deployment that only ever links pre-existing servers via
    # `/admin register-server` never needs to configure any of this.
    pterodactyl_application_api_key: str | None = Field(default=None, alias="PTERODACTYL_APPLICATION_API_KEY")
    pterodactyl_owner_user_id: int | None = Field(default=None, alias="PTERODACTYL_OWNER_USER_ID")
    pterodactyl_egg_id: int | None = Field(default=None, alias="PTERODACTYL_EGG_ID")
    pterodactyl_docker_image: str | None = Field(default=None, alias="PTERODACTYL_DOCKER_IMAGE")
    pterodactyl_startup_command: str | None = Field(default=None, alias="PTERODACTYL_STARTUP_COMMAND")
    # Raw JSON object string of egg-specific environment variables, e.g.
    # '{"MINECRAFT_VERSION":"1.20.4","SERVER_JARFILE":"server.jar"}'. Kept as
    # a single opaque JSON blob (rather than individual settings) because
    # every Pterodactyl egg defines its own, different set of variables.
    pterodactyl_create_environment: str | None = Field(default=None, alias="PTERODACTYL_CREATE_ENVIRONMENT")
    pterodactyl_memory_mb: int | None = Field(default=None, alias="PTERODACTYL_MEMORY_MB")
    pterodactyl_swap_mb: int = Field(default=0, alias="PTERODACTYL_SWAP_MB")
    pterodactyl_disk_mb: int | None = Field(default=None, alias="PTERODACTYL_DISK_MB")
    pterodactyl_cpu_percent: int = Field(default=0, alias="PTERODACTYL_CPU_PERCENT")
    pterodactyl_io_weight: int = Field(default=500, alias="PTERODACTYL_IO_WEIGHT")
    pterodactyl_databases_limit: int = Field(default=0, alias="PTERODACTYL_DATABASES_LIMIT")
    pterodactyl_backups_limit: int = Field(default=0, alias="PTERODACTYL_BACKUPS_LIMIT")
    # Comma-separated Pterodactyl location IDs Pterodactyl may auto-deploy
    # newly created servers into, e.g. "1,2".
    pterodactyl_deploy_location_ids: str | None = Field(default=None, alias="PTERODACTYL_DEPLOY_LOCATION_IDS")
    pterodactyl_default_mc_version: str = Field(default="1.20.4", alias="PTERODACTYL_DEFAULT_MC_VERSION")

    # --- Database ------------------------------------------------------------
    database_url: PostgresDsn = Field(..., alias="DATABASE_URL")

    # --- RCON ------------------------------------------------------------------
    rcon_host: str = Field(..., alias="RCON_HOST")
    rcon_port: int = Field(default=25575, alias="RCON_PORT")
    rcon_password: str = Field(..., alias="RCON_PASSWORD")

    # --- Logging ------------------------------------------------------------------
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: Literal["json", "console"] = Field(default="json", alias="LOG_FORMAT")

    @field_validator("pterodactyl_url")
    @classmethod
    def _validate_pterodactyl_url(cls, value: str) -> str:
        """Ensure the panel URL has no trailing slash and a valid scheme."""
        if not value.startswith(("http://", "https://")):
            raise ValueError("PTERODACTYL_URL must start with http:// or https://")
        return value.rstrip("/")

    @field_validator("pterodactyl_api_key")
    @classmethod
    def _validate_pterodactyl_api_key(cls, value: str) -> str:
        """Ensure the configured key is a *client* API key, not an app key.

        Pterodactyl distinguishes application keys (`ptla_`, full admin
        access to the panel) from client keys (`ptlc_`, scoped to the
        servers a specific panel user can access). CraftCord is designed
        to operate with a client key.
        """
        if not value.startswith("ptlc_"):
            raise ValueError(
                "PTERODACTYL_API_KEY must be a Pterodactyl *client* API key "
                "(it should start with 'ptlc_'), not an application key."
            )
        return value

    @field_validator("pterodactyl_application_api_key")
    @classmethod
    def _validate_pterodactyl_application_api_key(cls, value: str | None) -> str | None:
        """If set, ensure it's an *application* key — distinct from the client key above."""
        if value is not None and not value.startswith("ptla_"):
            raise ValueError("PTERODACTYL_APPLICATION_API_KEY must start with 'ptla_' (an application key).")
        return value

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        """Normalise and validate against Python's standard logging levels."""
        normalized = value.upper()
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if normalized not in valid:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(valid)}, got {value!r}")
        return normalized

    @property
    def sqlalchemy_database_url(self) -> str:
        """Return the database URL as a plain string for SQLAlchemy's engine factory."""
        return str(self.database_url)

    def creation_template_is_configured(self) -> bool:
        """Return whether every setting `/admin create-server` needs is present and well-formed.

        Deliberately plain (no import of `core.pterodactyl.ServerCreationTemplate`
        here, to avoid a config <-> core.pterodactyl import cycle — see
        `CraftCordBot.__init__`, which is where the actual template object
        gets built from these parsed pieces once, at startup.
        """
        required = (
            self.pterodactyl_application_api_key,
            self.pterodactyl_owner_user_id,
            self.pterodactyl_egg_id,
            self.pterodactyl_docker_image,
            self.pterodactyl_startup_command,
            self.pterodactyl_create_environment,
            self.pterodactyl_memory_mb,
            self.pterodactyl_disk_mb,
            self.pterodactyl_deploy_location_ids,
        )
        if any(value is None for value in required):
            return False
        return self.parsed_create_environment() is not None and self.parsed_deploy_location_ids() is not None

    def parsed_create_environment(self) -> dict[str, str] | None:
        """Parse `PTERODACTYL_CREATE_ENVIRONMENT`'s JSON, or `None` if unset/malformed."""
        if self.pterodactyl_create_environment is None:
            return None
        try:
            parsed = json.loads(self.pterodactyl_create_environment)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        return {str(key): str(value) for key, value in parsed.items()}

    def parsed_deploy_location_ids(self) -> list[int] | None:
        """Parse `PTERODACTYL_DEPLOY_LOCATION_IDS`'s comma-separated list, or `None` if unset/malformed."""
        if self.pterodactyl_deploy_location_ids is None:
            return None
        try:
            ids = [int(part.strip()) for part in self.pterodactyl_deploy_location_ids.split(",") if part.strip()]
        except ValueError:
            return None
        return ids or None


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide `Settings` singleton, constructing it on first call.

    Raises:
        pydantic.ValidationError: if any required environment variable is
            missing or fails validation. This is intentionally allowed to
            propagate so the process exits immediately with a clear error
            rather than starting in a half-configured state.
    """
    return Settings()  # type: ignore[call-arg]  # values are sourced from the environment
