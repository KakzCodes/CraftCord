"""Configuration parsing and validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from craftcord.config import Settings, get_settings

_REQUIRED_ENV = {
    "DISCORD_TOKEN": "test-token",
    "PTERODACTYL_URL": "https://panel.test/",
    "PTERODACTYL_API_KEY": "ptlc_test_key",
    "DATABASE_URL": "postgresql+asyncpg://user:pass@db:5432/craftcord",
    "RCON_HOST": "mc-server",
    "RCON_PASSWORD": "test-password",
}


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(name, value)


def test_settings_normalises_url_and_applies_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    settings = Settings(_env_file=None)

    assert settings.pterodactyl_url == "https://panel.test"
    assert settings.pterodactyl_application_api_key is None
    assert settings.discord_guild_id_dev is None
    assert settings.rcon_port == 25575
    assert settings.log_level == "INFO"
    assert settings.sqlalchemy_database_url == "postgresql+asyncpg://user:pass@db:5432/craftcord"


def test_optional_blank_environment_values_are_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    for name in (
        "DISCORD_GUILD_ID_DEV",
        "PTERODACTYL_APPLICATION_API_KEY",
        "PTERODACTYL_OWNER_USER_ID",
        "PTERODACTYL_EGG_ID",
        "PTERODACTYL_DOCKER_IMAGE",
        "PTERODACTYL_STARTUP_COMMAND",
        "PTERODACTYL_CREATE_ENVIRONMENT",
        "PTERODACTYL_MEMORY_MB",
        "PTERODACTYL_DISK_MB",
        "PTERODACTYL_DEPLOY_LOCATION_IDS",
    ):
        monkeypatch.setenv(name, "  ")

    settings = Settings(_env_file=None)

    assert settings.discord_guild_id_dev is None
    assert settings.pterodactyl_application_api_key is None
    assert settings.pterodactyl_owner_user_id is None


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("PTERODACTYL_URL", "panel.test", "must start with http:// or https://"),
        ("PTERODACTYL_API_KEY", "ptla_admin_key", "not an application key"),
        ("PTERODACTYL_APPLICATION_API_KEY", "ptlc_client_key", "application key"),
        ("LOG_LEVEL", "VERBOSE", "LOG_LEVEL must be one of"),
        ("LOG_FORMAT", "plain", "Input should be 'json' or 'console'"),
    ],
)
def test_settings_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str, message: str
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None)


def test_settings_require_core_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    monkeypatch.delenv("PTERODACTYL_URL", raising=False)
    monkeypatch.delenv("PTERODACTYL_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RCON_HOST", raising=False)
    monkeypatch.delenv("RCON_PASSWORD", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_creation_template_parses_environment_and_deploy_locations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("PTERODACTYL_APPLICATION_API_KEY", "ptla_test_key")
    monkeypatch.setenv("PTERODACTYL_OWNER_USER_ID", "12")
    monkeypatch.setenv("PTERODACTYL_EGG_ID", "34")
    monkeypatch.setenv("PTERODACTYL_DOCKER_IMAGE", "ghcr.io/example/yolk")
    monkeypatch.setenv("PTERODACTYL_STARTUP_COMMAND", "java -jar server.jar")
    monkeypatch.setenv("PTERODACTYL_CREATE_ENVIRONMENT", '{"PORT": 25565, "EULA": true}')
    monkeypatch.setenv("PTERODACTYL_MEMORY_MB", "2048")
    monkeypatch.setenv("PTERODACTYL_DISK_MB", "8192")
    monkeypatch.setenv("PTERODACTYL_DEPLOY_LOCATION_IDS", " 1, 2 ,, 3 ")

    settings = Settings(_env_file=None)

    assert settings.creation_template_is_configured() is True
    assert settings.parsed_create_environment() == {"PORT": "25565", "EULA": "True"}
    assert settings.parsed_deploy_location_ids() == [1, 2, 3]


@pytest.mark.parametrize(
    ("environment", "locations"),
    [
        ("{broken", "1"),
        ("[]", "1"),
        ('{"A": 1}', "not-an-id"),
        ('{"A": 1}', " , "),
    ],
)
def test_creation_template_rejects_malformed_optional_payloads(
    monkeypatch: pytest.MonkeyPatch, environment: str, locations: str
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("PTERODACTYL_APPLICATION_API_KEY", "ptla_test_key")
    monkeypatch.setenv("PTERODACTYL_OWNER_USER_ID", "12")
    monkeypatch.setenv("PTERODACTYL_EGG_ID", "34")
    monkeypatch.setenv("PTERODACTYL_DOCKER_IMAGE", "ghcr.io/example/yolk")
    monkeypatch.setenv("PTERODACTYL_STARTUP_COMMAND", "java -jar server.jar")
    monkeypatch.setenv("PTERODACTYL_CREATE_ENVIRONMENT", environment)
    monkeypatch.setenv("PTERODACTYL_MEMORY_MB", "2048")
    monkeypatch.setenv("PTERODACTYL_DISK_MB", "8192")
    monkeypatch.setenv("PTERODACTYL_DEPLOY_LOCATION_IDS", locations)

    settings = Settings(_env_file=None)

    assert settings.creation_template_is_configured() is False


def test_creation_template_is_disabled_when_required_setting_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    settings = Settings(_env_file=None)

    assert settings.creation_template_is_configured() is False
    assert settings.parsed_create_environment() is None
    assert settings.parsed_deploy_location_ids() is None


def test_get_settings_caches_environment_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    get_settings.cache_clear()
    try:
        first = get_settings()
        monkeypatch.setenv("PTERODACTYL_URL", "https://other-panel.test")
        second = get_settings()
    finally:
        get_settings.cache_clear()

    assert second is first
    assert second.pterodactyl_url == "https://panel.test"
