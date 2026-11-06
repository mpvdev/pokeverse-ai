import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from pokeverse.catalog import BaseStats, Pokemon, PokemonType, SqlitePokemonRepository
from pokeverse.catalog.repository import SCHEMA_VERSION, CatalogSchemaError

PIKACHU_STATS = BaseStats(35, 55, 40, 50, 50, 90)
CHARIZARD_STATS = BaseStats(78, 84, 78, 109, 85, 100)
PIKACHU = Pokemon(25, "pikachu", (PokemonType.ELECTRIC,), PIKACHU_STATS)
CHARIZARD = Pokemon(6, "charizard", (PokemonType.FIRE, PokemonType.FLYING), CHARIZARD_STATS)

V1_SCHEMA = """
CREATE TABLE pokemon (
    pokedex_id  INTEGER PRIMARY KEY CHECK (pokedex_id > 0),
    name        TEXT    NOT NULL UNIQUE,
    updated_at  TEXT    NOT NULL
);
CREATE TABLE pokemon_type (
    pokedex_id  INTEGER NOT NULL REFERENCES pokemon (pokedex_id) ON DELETE CASCADE,
    slot        INTEGER NOT NULL CHECK (slot IN (1, 2)),
    type        TEXT    NOT NULL,
    PRIMARY KEY (pokedex_id, slot),
    UNIQUE (pokedex_id, type)
);
INSERT INTO pokemon VALUES (25, 'pikachu', '2026-01-01T00:00:00+00:00');
INSERT INTO pokemon_type VALUES (25, 1, 'electric');
PRAGMA user_version = 1;
"""


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
    reversed_types = Pokemon(
        6, "charizard", (PokemonType.FLYING, PokemonType.FIRE), CHARIZARD_STATS
    )
    repository.save(reversed_types)

    assert repository.get_by_id(6) == reversed_types


def test_save_is_idempotent_and_updates(repository: SqlitePokemonRepository) -> None:
    repository.save(PIKACHU)
    repository.save(PIKACHU)
    updated = Pokemon(
        25, "pikachu", (PokemonType.ELECTRIC, PokemonType.FAIRY), BaseStats(35, 55, 40, 50, 50, 95)
    )
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
        repository.save(Pokemon(26, "pikachu", (PokemonType.ELECTRIC,), PIKACHU_STATS))
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


def make_v1_database(db_path: Path) -> None:
    connection = sqlite3.connect(db_path)
    connection.executescript(V1_SCHEMA)
    connection.close()


def test_v1_database_is_upgraded(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    make_v1_database(db_path)

    SqlitePokemonRepository(db_path).close()

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)


def test_v1_rows_without_stats_are_misses_until_re_saved(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    make_v1_database(db_path)

    with SqlitePokemonRepository(db_path) as repo:
        assert repo.get_by_name("pikachu") is None
        assert repo.list_all() == []
        assert repo.count() == 0

        repo.save(PIKACHU)

        assert repo.get_by_name("pikachu") == PIKACHU
        assert repo.count() == 1
