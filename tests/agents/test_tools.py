from collections.abc import Iterator
from typing import Any

import pytest

from pokeverse.agents import make_catalog_tools, make_team_tools, normalize_pokemon_identifier
from pokeverse.agents.tools import make_score_tool
from pokeverse.catalog import (
    Pokemon,
    PokemonCatalog,
    PokemonType,
    SqlitePokemonRepository,
)
from pokeverse.catalog.pokeapi import PokeApiUnavailableError

MR_MIME = Pokemon(122, "mr-mime", (PokemonType.PSYCHIC, PokemonType.FAIRY))


class DownSource:
    def fetch_pokemon(self, name_or_id: str | int) -> Pokemon:
        raise PokeApiUnavailableError("timeout")


@pytest.fixture
def repository() -> Iterator[SqlitePokemonRepository]:
    with SqlitePokemonRepository(":memory:") as repo:
        repo.save(MR_MIME)
        yield repo


def call_tool(catalog: PokemonCatalog, name: str, name_or_id: str) -> dict[str, object]:
    tools = {tool.name: tool for tool in make_catalog_tools(catalog)}
    return tools[name].handler(name_or_id=name_or_id)


def get_pokemon(catalog: PokemonCatalog, name_or_id: str) -> dict[str, object]:
    return call_tool(catalog, "get_pokemon", name_or_id)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Pikachu", "pikachu"),
        ("  Mr. Mime ", "mr-mime"),
        ("Farfetch'd", "farfetchd"),
        ("Ho-Oh", "ho-oh"),
        ("25", 25),
        ("#025", 25),
    ],
)
def test_normalize_pokemon_identifier(raw: str, expected: str | int) -> None:
    assert normalize_pokemon_identifier(raw) == expected


def test_get_pokemon_returns_canonical_json(repository: SqlitePokemonRepository) -> None:
    catalog = PokemonCatalog(repository)

    assert get_pokemon(catalog, "Mr. Mime") == MR_MIME.to_dict()
    assert get_pokemon(catalog, "122") == MR_MIME.to_dict()


@pytest.mark.parametrize("tool_name", ["get_pokemon", "get_type_matchups"])
@pytest.mark.parametrize(
    ("name_or_id", "source", "error"),
    [
        ("pikachu", None, "not_found"),
        ("pikachu", DownSource(), "unavailable"),
        ("   ", None, "invalid_identifier"),
        ("0", None, "invalid_identifier"),
    ],
)
def test_tools_return_errors_as_data(
    repository: SqlitePokemonRepository,
    tool_name: str,
    name_or_id: str,
    source: object,
    error: str,
) -> None:
    catalog = PokemonCatalog(repository, source)  # type: ignore[arg-type]

    result = call_tool(catalog, tool_name, name_or_id)

    assert result["error"] == error
    assert result["message"]


def test_get_type_matchups_computes_defensive_profile(
    repository: SqlitePokemonRepository,
) -> None:
    result = call_tool(PokemonCatalog(repository), "get_type_matchups", "Mr. Mime")

    assert result["pokemon"] == MR_MIME.to_dict()
    assert result["weak_to"] == {"poison": 2, "ghost": 2, "steel": 2}
    assert result["immune_to"] == {"dragon": 0}
    assert result["resists"] == {"fighting": 0.25, "psychic": 0.5}


def test_schemas_are_strict_mode_compatible(repository: SqlitePokemonRepository) -> None:
    catalog = PokemonCatalog(repository)
    for tool in make_catalog_tools(catalog) + make_team_tools(catalog):
        assert tool.parameters["additionalProperties"] is False
        assert set(tool.parameters["required"]) == set(tool.parameters["properties"])


def analyze(catalog: PokemonCatalog, names: list[str]) -> dict[str, Any]:
    (tool,) = make_team_tools(catalog)
    return tool.handler(names=names)


def test_analyze_team_returns_compact_analysis(repository: SqlitePokemonRepository) -> None:
    result = analyze(PokemonCatalog(repository), ["Mr. Mime", "mr-mime"])

    assert [m["name"] for m in result["team"]["members"]] == ["mr-mime", "mr-mime"]
    assert {v["attacking_type"] for v in result["vulnerabilities"]} == {
        "poison",
        "ghost",
        "steel",
    }
    assert "exposures" not in result


def test_analyze_team_reports_which_member_failed(repository: SqlitePokemonRepository) -> None:
    result = analyze(PokemonCatalog(repository), ["mr-mime", "missingno"])

    assert result["error"] == "not_found"
    assert result["name"] == "missingno"


def test_analyze_team_rejects_oversized_team(repository: SqlitePokemonRepository) -> None:
    result = analyze(PokemonCatalog(repository), ["mr-mime"] * 7)

    assert result["error"] == "invalid_team"


def test_score_team_is_compact(repository: SqlitePokemonRepository) -> None:
    tool = make_score_tool(PokemonCatalog(repository))

    result = tool.handler(names=["Mr. Mime", "mr-mime"])

    assert result == {
        "members": ["mr-mime (psychic/fairy)", "mr-mime (psychic/fairy)"],
        "score": [3, 6, 15, 14],
        "vulnerable_to": ["poison", "ghost", "steel"],
    }
    assert tool.handler(names=["missingno"])["error"] == "not_found"
