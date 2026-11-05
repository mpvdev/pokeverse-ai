import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from pokeverse.catalog import Pokemon, PokemonType, SqlitePokemonRepository
from pokeverse.catalog.repository import SCHEMA_VERSION, CatalogSchemaError

PIKACHU = Pokemon(25, "pikachu", (PokemonType.ELECTRIC,))
CHARIZARD = Pokemon(6, "charizard", (PokemonType.FIRE, PokemonType.FLYING))


@pytest.fixture
def repository() -> Iterator[SqlitePokemonRepository]:
    with SqlitePokemonRepository(":memory:") as repo:
        yield repo


def test_empty_repository(repository: SqlitePokemonRepository) -> None:
    assert repository.count() == 0
    assert repository.list_all() == []
    assert repository.get_by_id(25) is None
    assert repository.get_by_name("pikachu") is None


def test_save_and_get_round_trip(repository: SqlitePokemonRepository) -> None:
    repository.save(CHARIZARD)

    assert repository.get_by_id(6) == CHARIZARD
    assert repository.get_by_name("charizard") == CHARIZARD


def test_type_order_is_preserved(repository: SqlitePokemonRepository) -> None:
    reversed_types = Pokemon(6, "charizard", (PokemonType.FLYING, PokemonType.FIRE))
    repository.save(reversed_types)

    assert repository.get_by_id(6) == reversed_types


def test_save_is_idempotent_and_updates(repository: SqlitePokemonRepository) -> None:
    repository.save(PIKACHU)
    repository.save(PIKACHU)
    updated = Pokemon(25, "pikachu", (PokemonType.ELECTRIC, PokemonType.FAIRY))
    repository.save(updated)

    assert repository.count() == 1
    assert repository.get_by_id(25) == updated


def test_list_all_is_ordered_by_pokedex_id(repository: SqlitePokemonRepository) -> None:
    repository.save(PIKACHU)
    repository.save(CHARIZARD)

    assert repository.list_all() == [CHARIZARD, PIKACHU]
    assert repository.count() == 2


def test_name_must_be_unique(repository: SqlitePokemonRepository) -> None:
    repository.save(PIKACHU)

    with pytest.raises(sqlite3.IntegrityError):
        repository.save(Pokemon(26, "pikachu", (PokemonType.ELECTRIC,)))
    assert repository.get_by_id(26) is None


def test_data_persists_across_connections(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "catalog.db"
    with SqlitePokemonRepository(db_path) as repo:
        repo.save(CHARIZARD)

    with SqlitePokemonRepository(db_path) as repo:
        assert repo.get_by_name("charizard") == CHARIZARD


def test_schema_version_is_recorded(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    SqlitePokemonRepository(db_path).close()

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)


def test_unknown_schema_version_is_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA user_version = 999")
    connection.close()

    with pytest.raises(CatalogSchemaError):
        SqlitePokemonRepository(db_path)
