"""Structured logging configuration, built on `structlog`.

Call `configure_logging()` once, as early as possible in `__main__.py`,
before any other module-level code emits logs.

Per-command context (`guild_id`, `discord_id`, `command_name`,
`request_id`) is bound via `structlog.contextvars`, which makes it
automatically appear on every log line emitted during that command's
execution — including from deep inside the Pterodactyl/RCON clients and
repositories — without threading a logger instance through every call.
See `utils/decorators.py::audit` for where that binding happens.
"""

from __future__ import annotations

import logging
import sys

import structlog

from craftcord.config import Settings

_SECRET_KEYS = frozenset(
    {
        "token",
        "discord_token",
        "api_key",
        "pterodactyl_api_key",
        "pterodactyl_application_api_key",
        "rcon_password",
        "password",
        "authorization",
    }
)


def _redact_secrets(
    _logger: structlog.types.WrappedLogger,
    _method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Redact well-known secret keys from the event dict before rendering.

    Belt-and-suspenders: callers should never pass secrets into a log call
    in the first place, but this processor ensures a stray `token=...`
    kwarg never ends up in the logs or a log aggregator.
    """
    for key in list(event_dict.keys()):
        if key.lower() in _SECRET_KEYS:
            event_dict[key] = "***REDACTED***"
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Configure `structlog` and the stdlib `logging` root logger.

    Args:
        settings: Application settings; `log_level` and `log_format` drive
            the configuration.
    """
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level),
    )

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact_secrets,
    ]

    if settings.log_format == "json":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.setFormatter(formatter)

    # discord.py is chatty at INFO; keep it at WARNING unless we're debugging.
    if settings.log_level != "DEBUG":
        logging.getLogger("discord").setLevel(logging.WARNING)
        logging.getLogger("discord.http").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound to `name` (conventionally `__name__`)."""
    return structlog.get_logger(name)
