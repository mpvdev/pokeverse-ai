from importlib.metadata import version

import pytest
from conftest import FakePokeApi
from fastapi.testclient import TestClient

PIKACHU = {
    "pokedex_id": 25,
    "name": "pikachu",
    "types": ["electric"],
    "base_stats": {
        "hp": 35,
        "attack": 55,
        "defense": 40,
        "special_attack": 50,
        "special_defense": 50,
        "speed": 90,
    },
}


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": version("pokeverse-ai")}


def test_get_pokemon_returns_the_canonical_json(client: TestClient, pokeapi: FakePokeApi) -> None:
    response = client.get("/pokemon/pikachu")

    assert response.status_code == 200
    assert response.json() == PIKACHU
    assert pokeapi.requests == ["/api/v2/pokemon/pikachu"]


@pytest.mark.parametrize("identifier", ["Pikachu", "25", "%23025", "  PIKACHU "])
def test_names_and_ids_are_normalized(client: TestClient, identifier: str) -> None:
    assert client.get(f"/pokemon/{identifier}").json()["name"] == "pikachu"


def test_every_request_fetches_from_pokeapi(client: TestClient, pokeapi: FakePokeApi) -> None:
    client.get("/pokemon/pikachu")
    client.get("/pokemon/pikachu")

    assert pokeapi.requests == ["/api/v2/pokemon/pikachu"] * 2


def test_synced_pokemon_are_not_served_during_an_outage(
    client: TestClient, pokeapi: FakePokeApi
) -> None:
    client.get("/pokemon/pikachu")
    pokeapi.down = True

    assert client.get("/pokemon/pikachu").status_code == 503


def test_unknown_pokemon_is_404(client: TestClient) -> None:
    response = client.get("/pokemon/missingno")

    assert response.status_code == 404
    assert "does not exist" in response.json()["detail"]


def test_upstream_outage_is_503(client: TestClient, pokeapi: FakePokeApi) -> None:
    pokeapi.down = True

    response = client.get("/pokemon/pikachu")

    assert response.status_code == 503
    assert "PokéAPI could not provide" in response.json()["detail"]


@pytest.mark.parametrize("identifier", ["0", "%20%20", "-"])
def test_invalid_identifiers_are_422_before_any_lookup(
    client: TestClient, pokeapi: FakePokeApi, identifier: str
) -> None:
    response = client.get(f"/pokemon/{identifier}")

    assert response.status_code == 422
    assert pokeapi.requests == []


def test_list_pages_through_the_pokeapi_index(client: TestClient) -> None:
    first = client.get("/pokemon", params={"limit": 1}).json()
    second = client.get("/pokemon", params={"limit": 1, "offset": 1}).json()

    assert first == {"count": 2, "results": [{"pokedex_id": 6, "name": "charizard"}]}
    assert second["results"] == [{"pokedex_id": 25, "name": "pikachu"}]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_list_paging_is_validated(
    client: TestClient, pokeapi: FakePokeApi, params: dict[str, int]
) -> None:
    assert client.get("/pokemon", params=params).status_code == 422
    assert pokeapi.requests == []


def test_list_during_outage_is_503(client: TestClient, pokeapi: FakePokeApi) -> None:
    pokeapi.down = True

    assert client.get("/pokemon").status_code == 503


def test_learnset(client: TestClient, pokeapi: FakePokeApi) -> None:
    response = client.get("/pokemon/pikachu/learnset")

    assert response.json() == {
        "pokemon": "pikachu",
        "learnset": [
            "iron-tail",
            "quick-attack",
            "surf",
            "thunder-wave",
            "thunderbolt",
            "volt-tackle",
        ],
    }
    assert pokeapi.requests == ["/api/v2/pokemon/pikachu"]


def test_get_move(client: TestClient) -> None:
    response = client.get("/moves/Swords Dance")

    assert response.status_code == 200
    assert response.json() == {
        "move_id": 14,
        "name": "swords-dance",
        "type": "normal",
        "damage_class": "status",
        "power": None,
        "accuracy": None,
        "priority": 0,
        "pp": 20,
    }


def test_unknown_move_is_404(client: TestClient) -> None:
    assert client.get("/moves/splashier").status_code == 404


def test_openapi_documents_the_catalog(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert {"/pokemon", "/pokemon/{name_or_id}", "/moves/{name_or_id}"} <= set(schema["paths"])
    pokemon = schema["components"]["schemas"]["Pokemon"]
    assert list(pokemon["properties"]) == ["pokedex_id", "name", "types", "base_stats"]
