import random

import httpx
import pytest
from conftest import FakePokeApi
from fastapi.testclient import TestClient

from pokeverse.battles import GreedyPlayer, load_battler, run_battle
from pokeverse.catalog import PokemonCatalog, SqlitePokemonRepository
from pokeverse.catalog.pokeapi import PokeApiClient

DEFAULT_PIKACHU = ["volt-tackle", "surf", "iron-tail", "quick-attack"]


def test_battler_with_explicit_moves(client: TestClient) -> None:
    response = client.post(
        "/battlers", json={"pokemon": "Pikachu", "moves": ["Thunderbolt", "quick attack"]}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["pokemon"]["name"] == "pikachu"
    assert body["pokemon"]["base_stats"]["speed"] == 90
    assert [move["name"] for move in body["moves"]] == ["thunderbolt", "quick-attack"]


def test_battler_without_moves_gets_the_default_moveset(client: TestClient) -> None:
    response = client.post("/battlers", json={"pokemon": 25})

    assert [move["name"] for move in response.json()["moves"]] == DEFAULT_PIKACHU


def test_unlearnable_move_is_422_before_fetching_moves(
    client: TestClient, pokeapi: FakePokeApi
) -> None:
    response = client.post("/battlers", json={"pokemon": "pikachu", "moves": ["flamethrower"]})

    assert response.status_code == 422
    assert response.json()["detail"] == "pikachu cannot learn: flamethrower"
    assert pokeapi.requests == ["/api/v2/pokemon/pikachu"]


def test_unsupported_move_is_422(client: TestClient) -> None:
    response = client.post("/battlers", json={"pokemon": "pikachu", "moves": ["Thunder Wave"]})

    assert response.status_code == 422
    assert response.json()["detail"].startswith("moves not supported in battle: thunder-wave")


@pytest.mark.parametrize(
    ("body", "loc"),
    [
        ({"pokemon": "pikachu", "moves": ["surf"] * 5}, ["body", "moves"]),
        ({"pokemon": "pikachu", "moves": [85]}, ["body", "moves", 0]),
        ({"pokemon": "", "moves": []}, ["body", "pokemon"]),
        ({"moves": ["surf"]}, ["body", "pokemon"]),
    ],
)
def test_invalid_battler_requests_are_422_before_any_lookup(
    client: TestClient, pokeapi: FakePokeApi, body: dict[str, object], loc: list[object]
) -> None:
    response = client.post("/battlers", json=body)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == loc
    assert pokeapi.requests == []


def test_default_moveset_with_a_missing_move_is_404(client: TestClient) -> None:
    assert client.post("/battlers", json={"pokemon": "charizard"}).status_code == 404


def test_damage(client: TestClient) -> None:
    response = client.post(
        "/damage", json={"attacker": "pikachu", "move": "Thunderbolt", "defender": "#006"}
    )

    assert response.json() == {
        "attacker": "pikachu",
        "move": "thunderbolt",
        "defender": "charizard",
        "min": 68,
        "max": 84,
        "critical_max": 126,
        "defender_hp": 153,
        "effectiveness": 2.0,
        "stab": True,
    }


def test_damage_with_a_status_move_is_422(client: TestClient) -> None:
    response = client.post(
        "/damage", json={"attacker": "pikachu", "move": "thunder-wave", "defender": "pikachu"}
    )

    assert response.status_code == 422
    assert "does not deal power-based damage" in response.json()["detail"]


BATTLE = {
    "side1": [{"pokemon": "pikachu"}],
    "side2": [{"pokemon": "pikachu", "moves": ["quick-attack"]}],
    "seed": 3,
}


def test_battle_report(client: TestClient) -> None:
    body = client.post("/battles", json=BATTLE).json()

    assert body["seed"] == 3
    assert body["players"] == ["greedy", "greedy"]
    assert body["teams"] == [
        [{"pokemon": "pikachu", "moves": DEFAULT_PIKACHU}],
        [{"pokemon": "pikachu", "moves": ["quick-attack"]}],
    ]
    assert [event["kind"] for event in body["events"][:2]] == ["switch", "switch"]
    assert body["events"][-1] == {
        "turn": body["turns"],
        "kind": "win",
        "side": body["winner"],
        "pokemon": None,
        "move": None,
        "damage": None,
        "hp": None,
        "critical": False,
        "effectiveness": None,
    }


def test_battle_is_reproducible_and_matches_the_engine(
    client: TestClient, pokeapi: FakePokeApi
) -> None:
    first = client.post("/battles", json=BATTLE).json()
    second = client.post("/battles", json=BATTLE).json()

    transport = httpx.MockTransport(pokeapi.handler)
    with (
        SqlitePokemonRepository(":memory:") as repository,
        PokeApiClient(transport=transport) as upstream,
    ):
        catalog = PokemonCatalog(repository, upstream)
        teams = [
            [load_battler(catalog, "pikachu", DEFAULT_PIKACHU)],
            [load_battler(catalog, "pikachu", ["quick-attack"])],
        ]
    direct = run_battle(teams[0], teams[1], (GreedyPlayer(), GreedyPlayer()), random.Random(3))

    assert first == second
    assert first["winner"] == direct.winner
    assert first["events"] == [event.model_dump(mode="json") for event in direct.events]


def test_random_players_are_seeded(client: TestClient) -> None:
    request = {**BATTLE, "player1": "random", "player2": "random"}
    first = client.post("/battles", json=request).json()

    assert client.post("/battles", json=request).json() == first
    assert first["players"] == ["random", "random"]


@pytest.mark.parametrize(
    ("change", "loc"),
    [
        ({"player1": "agent"}, ["body", "player1"]),
        ({"side1": []}, ["body", "side1"]),
        ({"side2": [{"pokemon": "pikachu"}] * 7}, ["body", "side2"]),
        ({"seed": "3"}, ["body", "seed"]),
    ],
)
def test_invalid_battle_requests_are_422_before_any_lookup(
    client: TestClient, pokeapi: FakePokeApi, change: dict[str, object], loc: list[object]
) -> None:
    response = client.post("/battles", json={**BATTLE, **change})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == loc
    assert pokeapi.requests == []


def test_battle_during_outage_is_503(client: TestClient, pokeapi: FakePokeApi) -> None:
    pokeapi.down = True

    assert client.post("/battles", json=BATTLE).status_code == 503


def test_openapi_documents_the_deterministic_endpoints(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert {"/teams/analysis", "/battlers", "/damage", "/battles"} <= set(schema["paths"])
    analysis = schema["components"]["schemas"]["TeamAnalysis"]["properties"]
    assert {"vulnerabilities", "unresisted", "score"} <= set(analysis)
