import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from pokeverse.catalog import BaseStats, DamageClass, Move, Pokemon, PokemonType
from pokeverse.catalog.pokeapi import (
    DEFAULT_BASE_URL,
    PokeApiClient,
    PokeApiError,
    PokeApiRateLimitedError,
    PokeApiResponseError,
    PokeApiUnavailableError,
    PokemonNotFoundError,
    parse_move,
    parse_pokemon,
)

FIXTURES = Path(__file__).parent / "fixtures" / "pokeapi"

PIKACHU = Pokemon(
    pokedex_id=25,
    name="pikachu",
    types=(PokemonType.ELECTRIC,),
    stats=BaseStats(hp=35, attack=55, defense=40, special_attack=50, special_defense=50, speed=90),
    learnset=frozenset(
        {"thunderbolt", "quick-attack", "iron-tail", "thunder-wave", "surf", "volt-tackle"}
    ),
)
CHARIZARD = Pokemon(
    pokedex_id=6,
    name="charizard",
    types=(PokemonType.FIRE, PokemonType.FLYING),
    stats=BaseStats(
        hp=78, attack=84, defense=78, special_attack=109, special_defense=85, speed=100
    ),
    learnset=frozenset(
        {"flamethrower", "air-slash", "dragon-claw", "earthquake", "swords-dance", "fire-fang"}
    ),
)
THUNDERBOLT = Move(
    move_id=85,
    name="thunderbolt",
    type=PokemonType.ELECTRIC,
    damage_class=DamageClass.SPECIAL,
    power=90,
    accuracy=100,
    priority=0,
    pp=15,
)
SWORDS_DANCE = Move(
    move_id=14,
    name="swords-dance",
    type=PokemonType.NORMAL,
    damage_class=DamageClass.STATUS,
    power=None,
    accuracy=None,
    priority=0,
    pp=20,
)

Handler = Callable[[httpx.Request], httpx.Response]


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def load_move_fixture(name: str) -> dict[str, Any]:
    return load_fixture(f"move/{name}")


def make_client(handler: Handler) -> PokeApiClient:
    return PokeApiClient(transport=httpx.MockTransport(handler))


def fixture_handler(request: httpx.Request) -> httpx.Response:
    resource, name = request.url.path.rstrip("/").split("/")[-2:]
    aliases = {"25": "pikachu", "6": "charizard", "85": "thunderbolt"}
    folder = FIXTURES if resource == "pokemon" else FIXTURES / resource
    fixture = folder / f"{aliases.get(name, name)}.json"
    if not fixture.exists():
        return httpx.Response(404, json={"status": 404, "message": "Not Found"})
    return httpx.Response(200, json=json.loads(fixture.read_text()))


# --- parse_pokemon ---------------------------------------------------------


def test_parse_single_type_pokemon() -> None:
    assert parse_pokemon(load_fixture("pikachu")) == PIKACHU


def test_parse_dual_type_pokemon() -> None:
    assert parse_pokemon(load_fixture("charizard")) == CHARIZARD


def test_parse_ignores_stat_order() -> None:
    payload = load_fixture("charizard")
    payload["stats"].reverse()

    assert parse_pokemon(payload).stats == CHARIZARD.stats


def test_parse_skips_move_names_that_are_not_slugs() -> None:
    payload = load_fixture("pikachu")
    payload["moves"].append({"move": {"name": "breakneck-blitz--physical", "url": ""}})

    assert parse_pokemon(payload).learnset == PIKACHU.learnset


def test_parse_accepts_an_empty_learnset() -> None:
    payload = load_fixture("pikachu")
    payload["moves"] = []

    assert parse_pokemon(payload).learnset == frozenset()


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
        lambda p: p.pop("stats"),
        lambda p: p.update(stats=[]),
        lambda p: p["stats"].pop(),
        lambda p: p["stats"][0].update(base_stat=0),
        lambda p: p["stats"][0].update(base_stat="35"),
        lambda p: p["stats"][0].pop("stat"),
        lambda p: p.pop("moves"),
        lambda p: p["moves"][0].pop("move"),
        lambda p: p["moves"][0]["move"].update(name=None),
    ],
)
def test_parse_rejects_malformed_payload(mutate: Callable[[dict[str, Any]], Any]) -> None:
    payload = load_fixture("pikachu")
    mutate(payload)

    with pytest.raises(PokeApiResponseError):
        parse_pokemon(payload)


# --- parse_move ------------------------------------------------------------


def test_parse_damaging_move() -> None:
    assert parse_move(load_move_fixture("thunderbolt")) == THUNDERBOLT


def test_parse_status_move_with_null_power_and_accuracy() -> None:
    assert parse_move(load_move_fixture("swords-dance")) == SWORDS_DANCE


def test_parse_normalizes_pokeapi_quirks() -> None:
    status = load_move_fixture("swords-dance")
    status.update(power=60, accuracy=0)
    damaging = load_move_fixture("thunderbolt")
    damaging.update(power=0, accuracy=0)

    assert (parse_move(status).power, parse_move(status).accuracy) == (None, None)
    assert (parse_move(damaging).power, parse_move(damaging).accuracy) == (None, None)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.pop("power"),
        lambda p: p.pop("damage_class"),
        lambda p: p.update(type={"name": "shadow"}),
        lambda p: p.update(pp=None),
        lambda p: p.update(name="breakneck-blitz--physical"),
        lambda p: p.update(damage_class=None),
    ],
)
def test_parse_move_rejects_unsupported_or_malformed(
    mutate: Callable[[dict[str, Any]], Any],
) -> None:
    payload = load_move_fixture("thunderbolt")
    mutate(payload)

    with pytest.raises(PokeApiResponseError):
        parse_move(payload)


# --- PokeApiClient ---------------------------------------------------------


@pytest.mark.parametrize("identifier", ["pikachu", "Pikachu", "  PIKACHU ", 25])
def test_fetch_pokemon_by_name_or_id(identifier: str | int) -> None:
    with make_client(fixture_handler) as client:
        assert client.fetch_pokemon(identifier) == PIKACHU


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


@pytest.mark.parametrize("identifier", ["thunderbolt", " Thunderbolt ", 85])
def test_fetch_move_by_name_or_id(identifier: str | int) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return fixture_handler(request)

    with make_client(handler) as client:
        assert client.fetch_move(identifier) == THUNDERBOLT
    assert seen[0].startswith("/api/v2/move/")


def test_unknown_move_raises_not_found() -> None:
    with make_client(fixture_handler) as client, pytest.raises(PokemonNotFoundError):
        client.fetch_move("splashier")


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
        live = client.fetch_pokemon("charizard")
    fixture = parse_pokemon(load_fixture("charizard"))

    assert (live.pokedex_id, live.name, live.types, live.stats) == (
        fixture.pokedex_id,
        fixture.name,
        fixture.types,
        fixture.stats,
    )
    assert fixture.learnset <= live.learnset


@pytest.mark.network
def test_live_fetch_move_matches_fixture() -> None:
    with PokeApiClient() as client:
        assert client.fetch_move("thunderbolt") == THUNDERBOLT
        assert client.fetch_move("swords-dance") == SWORDS_DANCE
