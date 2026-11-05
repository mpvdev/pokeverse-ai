from collections.abc import Iterator

import pytest

from pokeverse.agents import make_catalog_tools, normalize_pokemon_identifier
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


def get_pokemon(catalog: PokemonCatalog, name_or_id: str) -> dict[str, object]:
    (tool,) = make_catalog_tools(catalog)
    return tool.handler(name_or_id=name_or_id)


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


@pytest.mark.parametrize(
    ("name_or_id", "source", "error"),
    [
        ("pikachu", None, "not_found"),
        ("pikachu", DownSource(), "unavailable"),
        ("   ", None, "invalid_identifier"),
        ("0", None, "invalid_identifier"),
    ],
)
def test_get_pokemon_returns_errors_as_data(
    repository: SqlitePokemonRepository, name_or_id: str, source: object, error: str
) -> None:
    catalog = PokemonCatalog(repository, source)  # type: ignore[arg-type]

    result = get_pokemon(catalog, name_or_id)

    assert result["error"] == error
    assert result["message"]


def test_schema_is_strict_mode_compatible(repository: SqlitePokemonRepository) -> None:
    (tool,) = make_catalog_tools(PokemonCatalog(repository))

    assert tool.parameters["additionalProperties"] is False
    assert set(tool.parameters["required"]) == set(tool.parameters["properties"])
