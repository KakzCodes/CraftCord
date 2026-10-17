"""Unit tests for `craftcord.core.pterodactyl.PterodactylClient`.

All HTTP is mocked with `respx` — no real network access. These assert:
request shape (URL, headers, JSON body), status-code -> domain-exception
mapping, and the retry-on-5xx/429 policy.
"""

from __future__ import annotations

import json

import httpx
import pytest

from craftcord.core.exceptions import (
    PterodactylAuthError,
    PterodactylError,
    PterodactylNotFound,
    PterodactylRateLimited,
    PterodactylValidationError,
)
from craftcord.core.pterodactyl import PterodactylApplicationClient, PterodactylClient, ServerCreationTemplate

_BASE_URL = "https://panel.test"
_API_KEY = "ptlc_test_key"

_SERVER_PAYLOAD = {
    "object": "server",
    "attributes": {
        "identifier": "abc123",
        "uuid": "abc12345-0000-0000-0000-000000000000",
        "name": "Survival",
        "node": "node-1",
        "limits": {"memory": 2048, "disk": 10240},
        "relationships": {
            "allocations": {
                "object": "list",
                "data": [
                    {
                        "object": "allocation",
                        "attributes": {"id": 1, "ip": "203.0.113.5", "port": 25565, "is_default": True},
                    }
                ],
            }
        },
    },
}


@pytest.fixture(autouse=True)
def _no_retry_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip real backoff sleeps so retry tests run instantly."""

    async def _instant_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("craftcord.core.pterodactyl.asyncio.sleep", _instant_sleep)


@pytest.fixture
async def client():
    instance = PterodactylClient(_BASE_URL, _API_KEY)
    yield instance
    await instance.aclose()


async def test_get_server_sends_authorized_request_and_parses_response(respx_mock, client):
    route = respx_mock.get(f"{_BASE_URL}/api/client/servers/abc123").mock(
        return_value=httpx.Response(200, json=_SERVER_PAYLOAD)
    )

    server = await client.get_server("abc123")

    assert route.called
    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {_API_KEY}"
    assert request.headers["Accept"] == "application/json"

    assert server.identifier == "abc123"
    assert server.name == "Survival"
    assert server.limits.memory_mb == 2048
    assert server.default_allocation is not None
    assert server.default_allocation.port == 25565


async def test_send_power_posts_signal_body(respx_mock, client):
    route = respx_mock.post(f"{_BASE_URL}/api/client/servers/abc123/power").mock(
        return_value=httpx.Response(204)
    )

    await client.send_power("abc123", "start")

    assert route.called
    assert json.loads(route.calls.last.request.content) == {"signal": "start"}


async def test_send_command_posts_command_body(respx_mock, client):
    route = respx_mock.post(f"{_BASE_URL}/api/client/servers/abc123/command").mock(
        return_value=httpx.Response(204)
    )

    await client.send_command("abc123", "say hello")

    assert json.loads(route.calls.last.request.content) == {"command": "say hello"}


async def test_404_maps_to_not_found(respx_mock, client):
    respx_mock.get(f"{_BASE_URL}/api/client/servers/missing").mock(return_value=httpx.Response(404))

    with pytest.raises(PterodactylNotFound):
        await client.get_server("missing")


@pytest.mark.parametrize("status", [401, 403])
async def test_401_403_maps_to_auth_error(respx_mock, client, status):
    respx_mock.get(f"{_BASE_URL}/api/client/servers/abc123").mock(return_value=httpx.Response(status))

    with pytest.raises(PterodactylAuthError):
        await client.get_server("abc123")


async def test_429_retries_then_raises_rate_limited(respx_mock, client):
    route = respx_mock.post(f"{_BASE_URL}/api/client/servers/abc123/power").mock(
        return_value=httpx.Response(429)
    )

    with pytest.raises(PterodactylRateLimited):
        await client.send_power("abc123", "start")

    assert route.call_count == 3


async def test_5xx_retries_up_to_max_attempts(respx_mock, client):
    route = respx_mock.post(f"{_BASE_URL}/api/client/servers/abc123/power").mock(
        return_value=httpx.Response(503)
    )

    with pytest.raises(PterodactylError):
        await client.send_power("abc123", "start")

    assert route.call_count == 3


async def test_5xx_then_success_recovers_without_raising(respx_mock, client):
    responses = iter([httpx.Response(500), httpx.Response(204)])

    def _responder(request: httpx.Request) -> httpx.Response:
        return next(responses)

    respx_mock.post(f"{_BASE_URL}/api/client/servers/abc123/power").mock(side_effect=_responder)

    await client.send_power("abc123", "start")  # should not raise


async def test_list_servers_parses_data_array(respx_mock, client):
    respx_mock.get(f"{_BASE_URL}/api/client").mock(
        return_value=httpx.Response(200, json={"object": "list", "data": [_SERVER_PAYLOAD]})
    )

    servers = await client.list_servers()

    assert len(servers) == 1
    assert servers[0].identifier == "abc123"


# --- PterodactylApplicationClient --------------------------------------------

_CREATE_TEMPLATE = ServerCreationTemplate(
    owner_user_id=1,
    egg_id=2,
    docker_image="ghcr.io/pterodactyl/yolks:java_21",
    startup_command="java -jar server.jar",
    environment={"SERVER_JARFILE": "server.jar", "MINECRAFT_VERSION": "1.20.4"},
    memory_mb=2048,
    swap_mb=0,
    disk_mb=10240,
    cpu_percent=0,
    io_weight=500,
    databases_limit=0,
    backups_limit=0,
    deploy_location_ids=[1],
)

_CREATED_SERVER_PAYLOAD = {
    "object": "server",
    "attributes": {"id": 7, "uuid": "new-uuid-0000", "identifier": "new1234"},
}


@pytest.fixture
async def app_client():
    instance = PterodactylApplicationClient(_BASE_URL, "ptla_test_key")
    yield instance
    await instance.aclose()


async def test_create_server_posts_template_as_deploy_payload(respx_mock, app_client):
    route = respx_mock.post(f"{_BASE_URL}/api/application/servers").mock(
        return_value=httpx.Response(201, json=_CREATED_SERVER_PAYLOAD)
    )

    created = await app_client.create_server("Survival", _CREATE_TEMPLATE)

    assert route.called
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer ptla_test_key"

    body = json.loads(request.content)
    assert body["name"] == "Survival"
    assert body["user"] == 1
    assert body["egg"] == 2
    assert body["limits"] == {"memory": 2048, "swap": 0, "disk": 10240, "io": 500, "cpu": 0}
    assert body["feature_limits"] == {"databases": 0, "backups": 0, "allocations": 1}
    assert body["deploy"] == {"locations": [1], "dedicated_ip": False, "port_range": []}

    assert created.id == 7
    assert created.uuid == "new-uuid-0000"
    assert created.identifier == "new1234"


async def test_create_server_422_raises_validation_error_with_detail(respx_mock, app_client):
    respx_mock.post(f"{_BASE_URL}/api/application/servers").mock(
        return_value=httpx.Response(
            422,
            json={
                "errors": [
                    {"code": "ValidationException", "status": "422", "detail": "The egg id is invalid."}
                ]
            },
        )
    )

    with pytest.raises(PterodactylValidationError) as exc_info:
        await app_client.create_server("Survival", _CREATE_TEMPLATE)

    assert "egg id is invalid" in exc_info.value.user_message
