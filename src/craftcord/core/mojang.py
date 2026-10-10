"""Async client for the Mojang API (Minecraft username → UUID lookups).

Lookups are cached in-process with a 24-hour TTL since a username's UUID
almost never changes and Mojang's API is rate-limited. The cache is a
plain dict guarded by nothing more than single-threaded asyncio — fine for
a single bot process; a multi-instance deployment would want a shared
cache (e.g. Redis), which is out of scope for this iteration.
"""

from __future__ import annotations

import time

import httpx

from craftcord.core.exceptions import MojangLookupError
from craftcord.logging_config import get_logger

logger = get_logger(__name__)

_CACHE_TTL_SECONDS = 24 * 60 * 60
_MOJANG_BASE_URL = "https://api.mojang.com"


def _insert_uuid_dashes(raw_uuid: str) -> str:
    """Convert Mojang's undashed 32-char UUID into standard dashed form."""
    return f"{raw_uuid[0:8]}-{raw_uuid[8:12]}-{raw_uuid[12:16]}-{raw_uuid[16:20]}-{raw_uuid[20:32]}"


class MojangClient:
    """Thin async client for `GET /users/profiles/minecraft/{username}`."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(base_url=_MOJANG_BASE_URL, timeout=httpx.Timeout(10.0))
        self._cache: dict[str, tuple[str | None, float]] = {}

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool. Call during bot shutdown."""
        await self._http.aclose()

    async def get_uuid(self, username: str) -> str | None:
        """Resolve a Minecraft username to its dashed Mojang UUID.

        Args:
            username: The Minecraft username to look up (case-insensitive).

        Returns:
            The dashed UUID string, or `None` if no account exists with
            that username (Mojang returned 404).

        Raises:
            MojangLookupError: if Mojang returns a 5xx error. Callers
                (e.g. `/link`) should catch this and degrade gracefully
                rather than blocking the whole command on Mojang being down.
        """
        cache_key = username.lower()
        cached = self._cache.get(cache_key)
        if cached is not None:
            value, expires_at = cached
            if expires_at > time.monotonic():
                return value

        try:
            response = await self._http.get(f"/users/profiles/minecraft/{username}")
        except httpx.TransportError as exc:
            logger.debug("mojang_transport_error", username=username, error=str(exc))
            raise MojangLookupError(f"Transport error calling Mojang API: {exc}") from exc

        if response.status_code == 404:
            self._cache[cache_key] = (None, time.monotonic() + _CACHE_TTL_SECONDS)
            return None

        if response.status_code >= 500:
            raise MojangLookupError(f"Mojang API returned {response.status_code}")

        if response.status_code != 200:
            # Unexpected 4xx other than 404 (e.g. malformed username). Treat as "not found"
            # rather than a hard error, since it isn't something retrying will fix.
            logger.debug("mojang_unexpected_status", username=username, status=response.status_code)
            return None

        body = response.json()
        uuid = _insert_uuid_dashes(body["id"])
        self._cache[cache_key] = (uuid, time.monotonic() + _CACHE_TTL_SECONDS)
        return uuid
