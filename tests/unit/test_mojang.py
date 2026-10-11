"""Unit tests for `craftcord.core.mojang.MojangClient`.

All HTTP is mocked with `respx` — no real network access.
"""

from __future__ import annotations

import httpx
import pytest

from craftcord.core.exceptions import MojangLookupError
from craftcord.core.mojang import MojangClient

_BASE_URL = "https://api.mojang.com"


@pytest.fixture
async def client():
    instance = MojangClient()
    yield instance
    await instance.aclose()


async def test_get_uuid_success_inserts_dashes(respx_mock, client):
    respx_mock.get(f"{_BASE_URL}/users/profiles/minecraft/Notch").mock(
        return_value=httpx.Response(200, json={"name": "Notch", "id": "069a79f444e94726a5befca90e38aaf6"})
    )

    uuid = await client.get_uuid("Notch")

    assert uuid == "069a79f4-44e9-4726-a5be-fca90e38aaf6"


async def test_get_uuid_404_returns_none(respx_mock, client):
    respx_mock.get(f"{_BASE_URL}/users/profiles/minecraft/doesnotexist").mock(
        return_value=httpx.Response(404)
    )

    assert await client.get_uuid("doesnotexist") is None


async def test_get_uuid_5xx_raises_mojang_lookup_error(respx_mock, client):
    respx_mock.get(f"{_BASE_URL}/users/profiles/minecraft/Notch").mock(return_value=httpx.Response(503))

    with pytest.raises(MojangLookupError):
        await client.get_uuid("Notch")


async def test_get_uuid_caches_successful_result(respx_mock, client):
    route = respx_mock.get(f"{_BASE_URL}/users/profiles/minecraft/Notch").mock(
        return_value=httpx.Response(200, json={"name": "Notch", "id": "069a79f444e94726a5befca90e38aaf6"})
    )

    first = await client.get_uuid("Notch")
    second = await client.get_uuid("Notch")

    assert first == second
    assert route.call_count == 1  # second call should be served from the cache


async def test_get_uuid_caches_not_found_result(respx_mock, client):
    route = respx_mock.get(f"{_BASE_URL}/users/profiles/minecraft/doesnotexist").mock(
        return_value=httpx.Response(404)
    )

    await client.get_uuid("doesnotexist")
    await client.get_uuid("doesnotexist")

    assert route.call_count == 1


async def test_get_uuid_cache_key_is_case_insensitive(respx_mock, client):
    route = respx_mock.get(f"{_BASE_URL}/users/profiles/minecraft/Notch").mock(
        return_value=httpx.Response(200, json={"name": "Notch", "id": "069a79f444e94726a5befca90e38aaf6"})
    )

    await client.get_uuid("Notch")
    await client.get_uuid("NOTCH")  # different case, same underlying player

    assert route.call_count == 1
