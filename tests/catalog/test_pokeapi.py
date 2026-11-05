import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from pokeverse.catalog import Pokemon, PokemonType
from pokeverse.catalog.pokeapi import (
    DEFAULT_BASE_URL,
    PokeApiClient,
    PokeApiError,
    PokeApiRateLimitedError,
    PokeApiResponseError,
    PokeApiUnavailableError,
    PokemonNotFoundError,
    parse_pokemon,
)

FIXTURES = Path(__file__).parent / "fixtures" / "pokeapi"

Handler = Callable[[httpx.Request], httpx.Response]


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def make_client(handler: Handler) -> PokeApiClient:
    return PokeApiClient(transport=httpx.MockTransport(handler))


def fixture_handler(request: httpx.Request) -> httpx.Response:
    name = request.url.path.rstrip("/").rsplit("/", 1)[-1]
    aliases = {"25": "pikachu", "6": "charizard"}
    fixture = FIXTURES / f"{aliases.get(name, name)}.json"
    if not fixture.exists():
        return httpx.Response(404, json={"status": 404, "message": "Not Found"})
    return httpx.Response(200, json=json.loads(fixture.read_text()))


# --- parse_pokemon ---------------------------------------------------------


def test_parse_single_type_pokemon() -> None:
    assert parse_pokemon(load_fixture("pikachu")) == Pokemon(25, "pikachu", (PokemonType.ELECTRIC,))


def test_parse_dual_type_pokemon() -> None:
    assert parse_pokemon(load_fixture("charizard")) == Pokemon(
        6, "charizard", (PokemonType.FIRE, PokemonType.FLYING)
    )


def test_parse_orders_types_by_slot() -> None:
    payload = load_fixture("charizard")
    payload["types"].reverse()

    assert parse_pokemon(payload).types == (PokemonType.FIRE, PokemonType.FLYING)


def test_parse_skips_non_elemental_types() -> None:
    payload = load_fixture("pikachu")
    payload["types"].append({"slot": 2, "type": {"name": "stellar", "url": ""}})

    assert parse_pokemon(payload).types == (PokemonType.ELECTRIC,)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.pop("id"),
        lambda p: p.pop("name"),
        lambda p: p.pop("types"),
        lambda p: p.update(types=[]),
        lambda p: p.update(types=[{"slot": 1}]),
        lambda p: p.update(types=[{"slot": 1, "type": {"name": "unknown"}}]),
        lambda p: p.update(types="electric"),
        lambda p: p.update(id="25"),
        lambda p: p.update(name="Pikachu"),
    ],
)
def test_parse_rejects_malformed_payload(mutate: Callable[[dict[str, Any]], Any]) -> None:
    payload = load_fixture("pikachu")
    mutate(payload)

    with pytest.raises(PokeApiResponseError):
        parse_pokemon(payload)


# --- PokeApiClient ---------------------------------------------------------


@pytest.mark.parametrize("identifier", ["pikachu", "Pikachu", "  PIKACHU ", 25])
def test_fetch_pokemon_by_name_or_id(identifier: str | int) -> None:
    with make_client(fixture_handler) as client:
        assert client.fetch_pokemon(identifier) == Pokemon(25, "pikachu", (PokemonType.ELECTRIC,))


def test_fetch_pokemon_sends_expected_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return fixture_handler(request)

    with make_client(handler) as client:
        client.fetch_pokemon("charizard")

    (request,) = seen
    assert str(request.url) == f"{DEFAULT_BASE_URL}/pokemon/charizard"
    assert request.headers["User-Agent"].startswith("pokeverse-ai/")
    assert request.headers["Accept"] == "application/json"


@pytest.mark.parametrize("identifier", ["", "   ", 0, -1, True])
def test_fetch_pokemon_rejects_invalid_identifier(identifier: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request should be made")

    with make_client(handler) as client, pytest.raises(ValueError):
        client.fetch_pokemon(identifier)


def test_unknown_pokemon_raises_not_found() -> None:
    with make_client(fixture_handler) as client, pytest.raises(PokemonNotFoundError):
        client.fetch_pokemon("missingno")


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(429), PokeApiRateLimitedError),
        (httpx.Response(500), PokeApiUnavailableError),
        (httpx.Response(503), PokeApiUnavailableError),
        (httpx.Response(301), PokeApiResponseError),
        (httpx.Response(400), PokeApiResponseError),
        (httpx.Response(200, content=b"not json"), PokeApiResponseError),
        (httpx.Response(200, json=["not", "an", "object"]), PokeApiResponseError),
    ],
)
def test_http_failures_map_to_client_errors(
    response: httpx.Response, error: type[PokeApiError]
) -> None:
    with make_client(lambda request: response) as client, pytest.raises(error):
        client.fetch_pokemon("pikachu")


@pytest.mark.parametrize(
    "exception",
    [
        httpx.ConnectTimeout("timed out"),
        httpx.ReadTimeout("timed out"),
        httpx.ConnectError("connection refused"),
    ],
)
def test_transport_failures_raise_unavailable(exception: httpx.TransportError) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception

    with make_client(handler) as client, pytest.raises(PokeApiUnavailableError):
        client.fetch_pokemon("pikachu")


def test_all_client_errors_share_a_base_class() -> None:
    for error in (
        PokemonNotFoundError,
        PokeApiUnavailableError,
        PokeApiRateLimitedError,
        PokeApiResponseError,
    ):
        assert issubclass(error, PokeApiError)


# --- Live (opt-in) ---------------------------------------------------------


@pytest.mark.network
def test_live_fetch_matches_fixture() -> None:
    with PokeApiClient() as client:
        assert client.fetch_pokemon("charizard") == parse_pokemon(load_fixture("charizard"))
