import pytest
from conftest import FakePokeApi
from fastapi.testclient import TestClient


def analyze(client: TestClient, members: object):
    return client.post("/teams/analysis", json={"members": members})


def test_team_analysis(client: TestClient) -> None:
    response = analyze(client, ["Pikachu", 25, "#006"])

    assert response.status_code == 200
    body = response.json()
    assert [m["name"] for m in body["team"]["members"]] == ["pikachu", "pikachu", "charizard"]
    assert [v["attacking_type"] for v in body["vulnerabilities"]] == ["ground"]
    assert body["vulnerabilities"][0]["weak"] == ["pikachu", "pikachu"]
    assert "electric" in body["offensive_gaps"]
    assert len(body["exposures"]) == 18
    assert body["score"][:2] == [1, 2]


@pytest.mark.parametrize(
    "members",
    [[], ["pikachu"] * 7, ["  "], [0], [True], "pikachu", [["pikachu"]]],
)
def test_invalid_teams_are_422_before_any_lookup(
    client: TestClient, pokeapi: FakePokeApi, members: object
) -> None:
    response = analyze(client, members)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][:2] == ["body", "members"]
    assert pokeapi.requests == []


def test_unknown_fields_are_rejected(client: TestClient) -> None:
    response = client.post("/teams/analysis", json={"members": ["pikachu"], "size": 1})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "size"]


def test_unknown_member_is_404(client: TestClient) -> None:
    assert analyze(client, ["pikachu", "missingno"]).status_code == 404


def test_team_analysis_during_outage_is_503(client: TestClient, pokeapi: FakePokeApi) -> None:
    pokeapi.down = True

    assert analyze(client, ["pikachu"]).status_code == 503
