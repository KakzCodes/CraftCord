"""Unit tests for `craftcord.core.rcon.RconClient`.

`mcrcon.MCRcon` is monkeypatched with an in-memory fake — no real sockets.
"""

from __future__ import annotations

import pytest

from craftcord.core.exceptions import RconConnectionError
from craftcord.core.rcon import RconClient, RconConfig

_CFG = RconConfig(host="localhost", port=25575, password="secret")


@pytest.fixture
def fake_rcon(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Patch `MCRcon` with a fake that returns canned responses by exact command string."""
    responses: dict[str, str] = {}

    class _FakeMCRcon:
        def __init__(self, host: str, password: str, port: int = 25575, timeout: int = 5) -> None:
            self.host = host
            self.password = password
            self.port = port
            self.timeout = timeout

        def __enter__(self) -> "_FakeMCRcon":
            return self

        def __exit__(self, *exc_info: object) -> bool:
            return False

        def command(self, cmd: str) -> str:
            return responses[cmd]

    monkeypatch.setattr("craftcord.core.rcon.MCRcon", _FakeMCRcon)
    return responses


async def test_command_returns_raw_response(fake_rcon: dict[str, str]) -> None:
    fake_rcon["say hello"] = "OK"
    client = RconClient()

    result = await client.command(_CFG, "say hello")

    assert result == "OK"


async def test_list_players_parses_comma_separated_names(fake_rcon: dict[str, str]) -> None:
    fake_rcon["list"] = "There are 2 of a max of 20 players online: Alice, Bob"
    client = RconClient()

    players = await client.list_players(_CFG)

    assert players == ["Alice", "Bob"]


async def test_list_players_returns_empty_list_when_nobody_online(fake_rcon: dict[str, str]) -> None:
    fake_rcon["list"] = "There are 0 of a max of 20 players online:"
    client = RconClient()

    players = await client.list_players(_CFG)

    assert players == []


async def test_get_player_pos_parses_pos_and_dimension_nbt(fake_rcon: dict[str, str]) -> None:
    fake_rcon["data get entity Steve Pos"] = "Steve has the following entity data: [123.5d, 64.0d, -78.3d]"
    fake_rcon["data get entity Steve Dimension"] = (
        'Steve has the following entity data: "minecraft:overworld"'
    )
    client = RconClient()

    result = await client.get_player_pos(_CFG, "Steve")

    assert result == (124, 64, -78, "minecraft:overworld")


async def test_get_player_pos_returns_none_when_player_offline(fake_rcon: dict[str, str]) -> None:
    fake_rcon["data get entity Ghost Pos"] = "No entity was found"
    client = RconClient()

    result = await client.get_player_pos(_CFG, "Ghost")

    assert result is None


async def test_connection_failure_raises_rcon_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FailingMCRcon:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "_FailingMCRcon":
            raise ConnectionRefusedError("connection refused")

        def __exit__(self, *exc_info: object) -> bool:
            return False

    monkeypatch.setattr("craftcord.core.rcon.MCRcon", _FailingMCRcon)
    client = RconClient()

    with pytest.raises(RconConnectionError):
        await client.command(_CFG, "list")
