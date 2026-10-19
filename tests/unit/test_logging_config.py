"""Structured logging setup and secret-redaction tests."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import structlog

from craftcord import logging_config


def test_redact_secrets_matches_case_insensitively_and_preserves_other_fields() -> None:
    event = {
        "token": "secret-token",
        "Pterodactyl_Application_API_Key": "secret-app-key",
        "message": "request failed",
    }

    result = logging_config._redact_secrets(Mock(), "info", event)

    assert result == {
        "token": "***REDACTED***",
        "Pterodactyl_Application_API_Key": "***REDACTED***",
        "message": "request failed",
    }


@pytest.mark.parametrize("log_format", ["json", "console"])
@pytest.mark.parametrize("log_level", ["INFO", "DEBUG"])
def test_configure_logging_sets_processor_chain_and_logger_levels(
    monkeypatch: pytest.MonkeyPatch, log_format: str, log_level: str
) -> None:
    root = logging.getLogger()
    discord_logger = logging.getLogger("discord")
    discord_http_logger = logging.getLogger("discord.http")
    original_root_formatters = [handler.formatter for handler in root.handlers]
    original_levels = (root.level, discord_logger.level, discord_http_logger.level)
    monkeypatch.setattr(logging_config.logging, "basicConfig", Mock())

    try:
        logging_config.configure_logging(SimpleNamespace(log_level=log_level, log_format=log_format))

        assert root.handlers
        assert all(
            isinstance(handler.formatter, structlog.stdlib.ProcessorFormatter)
            for handler in root.handlers
        )
        assert root.level == getattr(logging, log_level)
        if log_level == "DEBUG":
            assert discord_logger.level != logging.WARNING
            assert discord_http_logger.level != logging.WARNING
        else:
            assert discord_logger.level == logging.WARNING
            assert discord_http_logger.level == logging.WARNING
    finally:
        for handler, formatter in zip(root.handlers, original_root_formatters, strict=False):
            handler.setFormatter(formatter)
        root.setLevel(original_levels[0])
        discord_logger.setLevel(original_levels[1])
        discord_http_logger.setLevel(original_levels[2])
        structlog.reset_defaults()


def test_get_logger_uses_structlog_logger_name(monkeypatch: pytest.MonkeyPatch) -> None:
    get_logger = Mock(return_value=object())
    monkeypatch.setattr(logging_config.structlog, "get_logger", get_logger)

    assert logging_config.get_logger("craftcord.tests") is get_logger.return_value
    get_logger.assert_called_once_with("craftcord.tests")
