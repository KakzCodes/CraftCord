"""CraftCord's process entry point: `python -m craftcord`.

Order matters here: settings are loaded — and validated, which is where a
missing or malformed environment variable fails the process fast, before
anything else happens — then logging is configured from those settings,
and only then is the bot constructed. Every log line the bot emits during
startup is therefore already structured.

NOTE: a `Settings` validation failure happens before `configure_logging()`
runs (it can't be otherwise — `LOG_LEVEL`/`LOG_FORMAT` themselves come
from `Settings`), so that one specific failure mode prints a plain
pydantic traceback to stderr rather than a structured log line. This is an
acceptable trade-off for a fail-fast startup check.
"""

from __future__ import annotations

import asyncio
import sys

from craftcord.bot import CraftCordBot
from craftcord.config import get_settings
from craftcord.logging_config import configure_logging, get_logger


async def _run() -> None:
    """Load settings, configure logging, and run the bot until it stops."""
    settings = get_settings()
    configure_logging(settings)
    logger = get_logger(__name__)

    logger.info("craftcord_starting", log_level=settings.log_level, log_format=settings.log_format)

    bot = CraftCordBot(settings)
    async with bot:
        await bot.start(settings.discord_token)


def main() -> None:
    """Synchronous entry point. Run via `python -m craftcord`."""
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
