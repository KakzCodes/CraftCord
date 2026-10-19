"""Async clients for the Pterodactyl panel's client and application APIs.

`PterodactylClient` wraps the **client API** (`/api/client/...`) — power
actions, live status, and connect-address lookups for servers the
configured *client* key (`ptlc_...`) can already see. This is the only
client most of the bot uses.

`PterodactylApplicationClient` wraps the **application API**
(`/api/application/...`) — currently just server creation, for
`/admin create-server`. It needs a separate, higher-privilege
*application* key (`ptla_...`) and is only constructed at all if one is
configured (see `config.Settings.creation_template_is_configured`).

Both share the same request/retry/error-mapping logic via the
module-level `_send_request` function — composition over a shared base
class, since the two clients otherwise have nothing in common (different
base paths, different auth, almost entirely different endpoints).

All responses are parsed into typed Pydantic models rather than returned
as raw dicts, and all non-2xx responses are translated into the
`core.exceptions` hierarchy so callers never need to inspect HTTP status
codes themselves.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from craftcord.core.exceptions import (
    PterodactylAuthError,
    PterodactylError,
    PterodactylNotFound,
    PterodactylRateLimited,
    PterodactylValidationError,
)
from craftcord.logging_config import get_logger

logger = get_logger(__name__)

_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 0.5
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_RETRY_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=5.0)

PowerSignal = Literal["start", "stop", "restart", "kill"]


class Allocation(BaseModel):
    """A single network allocation (IP:port) bound to a server."""

    ip: str
    port: int
    is_default: bool = False


class ServerLimits(BaseModel):
    """Resource limits configured for a server. `0` conventionally means unlimited."""

    memory_mb: int
    disk_mb: int


class PterodactylServer(BaseModel):
    """A server as returned by the Pterodactyl client API."""

    uuid: str
    identifier: str
    name: str
    node: str
    limits: ServerLimits
    allocations: list[Allocation] = Field(default_factory=list)

    @property
    def default_allocation(self) -> Allocation | None:
        """Return the allocation flagged as default, falling back to the first one."""
        for allocation in self.allocations:
            if allocation.is_default:
                return allocation
        return self.allocations[0] if self.allocations else None


class PterodactylResources(BaseModel):
    """Live resource usage for a running (or stopped) server."""

    state: str
    cpu_percent: float
    memory_bytes: int
    memory_limit_bytes: int
    disk_bytes: int
    disk_limit_bytes: int
    uptime_ms: int


class ServerCreationTemplate(BaseModel):
    """The fixed template `/admin create-server` provisions every new server from.

    Built once, at startup, from `Settings` (see `CraftCordBot.__init__`) —
    "one fixed template for everyone" per the current product scope. A
    future iteration that lets admins choose a template per guild, or
    lets individual paid-tier users get their own server, would replace
    the single startup-time instance with a per-guild lookup, but the
    shape of the template itself wouldn't need to change.
    """

    owner_user_id: int
    egg_id: int
    docker_image: str
    startup_command: str
    environment: dict[str, str]
    memory_mb: int
    swap_mb: int
    disk_mb: int
    cpu_percent: int
    io_weight: int
    databases_limit: int
    backups_limit: int
    deploy_location_ids: list[int]


class CreatedServer(BaseModel):
    """The identifiers Pterodactyl assigns a newly created server."""

    id: int
    uuid: str
    identifier: str


def _parse_server(raw: dict[str, Any]) -> PterodactylServer:
    """Map a raw `/api/client/servers/{id}` JSON body onto `PterodactylServer`."""
    attrs = raw["attributes"]
    limits_raw = attrs.get("limits", {})
    allocations_raw = attrs.get("relationships", {}).get("allocations", {}).get("data", [])

    allocations = [
        Allocation(
            ip=a["attributes"]["ip"],
            port=a["attributes"]["port"],
            is_default=a["attributes"].get("is_default", False),
        )
        for a in allocations_raw
    ]

    return PterodactylServer(
        uuid=attrs["uuid"],
        identifier=attrs["identifier"],
        name=attrs["name"],
        node=attrs["node"],
        limits=ServerLimits(
            memory_mb=limits_raw.get("memory", 0) or 0,
            disk_mb=limits_raw.get("disk", 0) or 0,
        ),
        allocations=allocations,
    )


def _parse_resources(raw: dict[str, Any], limits: ServerLimits) -> PterodactylResources:
    """Map a raw `/api/client/servers/{id}/resources` JSON body onto `PterodactylResources`.

    The resources endpoint reports current usage only, not configured
    limits, so `limits` (fetched separately via `get_server`) is passed in
    to populate `memory_limit_bytes`/`disk_limit_bytes`.
    """
    attrs = raw["attributes"]
    usage = attrs["resources"]

    return PterodactylResources(
        state=attrs["current_state"],
        cpu_percent=usage.get("cpu_absolute", 0.0),
        memory_bytes=usage.get("memory_bytes", 0),
        memory_limit_bytes=limits.memory_mb * 1024 * 1024,
        disk_bytes=usage.get("disk_bytes", 0),
        disk_limit_bytes=limits.disk_mb * 1024 * 1024,
        uptime_ms=usage.get("uptime", 0),
    )


def _parse_created_server(raw: dict[str, Any]) -> CreatedServer:
    """Map a raw `POST /api/application/servers` JSON body onto `CreatedServer`."""
    attrs = raw["attributes"]
    return CreatedServer(id=attrs["id"], uuid=attrs["uuid"], identifier=attrs["identifier"])


def _extract_validation_detail(response: httpx.Response) -> str | None:
    """Best-effort extraction of the first error detail from a 422 response body.

    Pterodactyl's validation errors look like
    `{"errors": [{"code": "...", "status": "422", "detail": "..."}]}`. If
    the body doesn't match that shape, `None` is returned rather than
    raising — this is purely a nicer-error-message nicety, never load-bearing.
    """
    try:
        body = response.json()
        errors = body.get("errors", [])
        if errors:
            return errors[0].get("detail")
    except (ValueError, AttributeError, TypeError, KeyError):
        pass
    return None


async def _send_request(
    http: httpx.AsyncClient, method: str, path: str, *, json: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Issue one HTTP request with status mapping and safe retries.

    Shared by both `PterodactylClient` and `PterodactylApplicationClient` —
    the error mapping and logging are shared. Only idempotent read methods
    are retried: replaying POST requests could repeat a console command or
    provision duplicate servers if the first response was lost.

    Args:
        http: The calling client's underlying `httpx.AsyncClient`.
        method: HTTP method, e.g. `"GET"`, `"POST"`.
        path: Path relative to `http`'s configured `base_url`.
        json: Optional JSON request body.

    Returns:
        The parsed JSON response body (`{}` for a 204 / empty body).

    Raises:
        PterodactylNotFound: on a 404 response.
        PterodactylAuthError: on a 401 or 403 response.
        PterodactylValidationError: on a 422 response.
        PterodactylRateLimited: on a 429 response.
        PterodactylError: on any other non-2xx response, or a network-
            level failure that persists through all retry attempts.
    """
    last_exc: Exception | None = None
    can_retry = method.upper() in _RETRY_SAFE_METHODS

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        started = time.monotonic()
        try:
            response = await http.request(method, path, json=json)
        except httpx.TransportError as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            logger.debug(
                "pterodactyl_request_transport_error",
                method=method,
                path=path,
                attempt=attempt,
                duration_ms=duration_ms,
                error_type=type(exc).__name__,
            )
            last_exc = exc
            if can_retry and attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
                continue
            raise PterodactylError(
                f"Transport error calling Pterodactyl: {exc}",
                user_message="Couldn't reach the Pterodactyl panel. Please try again shortly.",
            ) from exc

        duration_ms = int((time.monotonic() - started) * 1000)
        logger.debug(
            "pterodactyl_request",
            method=method,
            path=path,
            status=response.status_code,
            attempt=attempt,
            duration_ms=duration_ms,
        )

        if response.status_code < 300:
            if response.status_code == 204 or not response.content:
                return {}
            return response.json()

        if response.status_code == 404:
            raise PterodactylNotFound()
        if response.status_code in (401, 403):
            raise PterodactylAuthError()
        if response.status_code == 422:
            detail = _extract_validation_detail(response)
            raise PterodactylValidationError(
                f"Pterodactyl validation error for {method} {path}: {detail}",
                user_message=(
                    f"The Pterodactyl panel rejected this: {detail}"
                    if detail
                    else PterodactylValidationError.default_message
                ),
            )

        if can_retry and response.status_code in _RETRYABLE_STATUSES and attempt < _MAX_ATTEMPTS:
            await asyncio.sleep(_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
            continue

        if response.status_code == 429:
            raise PterodactylRateLimited()

        raise PterodactylError(f"Pterodactyl returned {response.status_code} for {method} {path}")

    # Unreachable in practice: the loop above always returns or raises.
    raise PterodactylError("Pterodactyl request failed after all retry attempts.") from last_exc


class PterodactylClient:
    """Async client for the Pterodactyl panel's `/api/client` endpoints."""

    def __init__(self, base_url: str, api_key: str) -> None:
        """Create the client and its underlying persistent `httpx.AsyncClient`.

        Args:
            base_url: The panel's base URL, e.g. `https://panel.example.com`
                (no trailing slash — `config.Settings` strips it).
            api_key: A Pterodactyl *client* API key (`ptlc_...`).
        """
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=_DEFAULT_TIMEOUT,
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool. Call during bot shutdown."""
        await self._http.aclose()

    async def get_server(self, uuid: str) -> PterodactylServer:
        """Fetch a server's metadata, limits, and network allocations.

        Args:
            uuid: The server's Pterodactyl identifier (as stored in
                `servers.pterodactyl_uuid`).
        """
        raw = await _send_request(self._http, "GET", f"/api/client/servers/{uuid}")
        return _parse_server(raw)

    async def get_resources(self, uuid: str) -> PterodactylResources:
        """Fetch a server's live CPU/RAM/disk usage, uptime, and power state.

        Issues two requests concurrently: the resources endpoint (for
        current usage) and the server endpoint (for configured limits,
        which the resources endpoint doesn't include).

        Args:
            uuid: The server's Pterodactyl identifier.
        """
        resources_raw, server = await asyncio.gather(
            _send_request(self._http, "GET", f"/api/client/servers/{uuid}/resources"),
            self.get_server(uuid),
        )
        return _parse_resources(resources_raw, server.limits)

    async def send_power(self, uuid: str, signal: PowerSignal) -> None:
        """Send a power action (start/stop/restart/kill) to a server.

        Args:
            uuid: The server's Pterodactyl identifier.
            signal: The power signal to send.
        """
        await _send_request(self._http, "POST", f"/api/client/servers/{uuid}/power", json={"signal": signal})

    async def send_command(self, uuid: str, command: str) -> None:
        """Send a console command to a server (used by the admin cog).

        Args:
            uuid: The server's Pterodactyl identifier.
            command: The raw console command string.
        """
        await _send_request(
            self._http, "POST", f"/api/client/servers/{uuid}/command", json={"command": command}
        )

    async def list_servers(self) -> list[PterodactylServer]:
        """List every server visible to the configured API key.

        NOTE: Pterodactyl paginates this endpoint; for an MVP deployment
        (a handful of servers per panel) a single page is assumed to be
        sufficient. Pagination can be added in a later iteration if a
        deployment outgrows it.
        """
        raw = await _send_request(self._http, "GET", "/api/client")
        return [_parse_server(item) for item in raw.get("data", [])]


class PterodactylApplicationClient:
    """Async client for the Pterodactyl panel's `/api/application` endpoints.

    Only used for `/admin create-server`. Needs a separate, higher-
    privilege *application* API key — see the module docstring.
    """

    def __init__(self, base_url: str, application_api_key: str) -> None:
        """Create the client and its underlying persistent `httpx.AsyncClient`.

        Args:
            base_url: The panel's base URL (same panel as `PterodactylClient`).
            application_api_key: A Pterodactyl *application* API key (`ptla_...`).
        """
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {application_api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=_DEFAULT_TIMEOUT,
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool. Call during bot shutdown."""
        await self._http.aclose()

    async def create_server(self, name: str, template: ServerCreationTemplate) -> CreatedServer:
        """Provision a brand-new server on the panel from a fixed template.

        Uses Pterodactyl's `deploy` strategy (rather than a pre-selected
        allocation ID) so the panel picks an available node + network
        allocation within `template.deploy_location_ids` itself — a fixed
        single allocation ID would only work for the *first* server ever
        created, since allocations are one-to-one with servers.

        Args:
            name: The new server's display name on the panel.
            template: The fixed creation template (see `ServerCreationTemplate`).

        Returns:
            The newly created server's panel identifiers.

        Raises:
            PterodactylValidationError: if the panel rejects the request
                body (e.g. a misconfigured egg ID or docker image) — the
                most common failure mode the first time this template is used.
        """
        payload = {
            "name": name,
            "user": template.owner_user_id,
            "egg": template.egg_id,
            "docker_image": template.docker_image,
            "startup": template.startup_command,
            "environment": template.environment,
            "limits": {
                "memory": template.memory_mb,
                "swap": template.swap_mb,
                "disk": template.disk_mb,
                "io": template.io_weight,
                "cpu": template.cpu_percent,
            },
            "feature_limits": {
                "databases": template.databases_limit,
                "backups": template.backups_limit,
                "allocations": 1,
            },
            "deploy": {
                "locations": template.deploy_location_ids,
                "dedicated_ip": False,
                "port_range": [],
            },
        }
        raw = await _send_request(self._http, "POST", "/api/application/servers", json=payload)
        return _parse_created_server(raw)
