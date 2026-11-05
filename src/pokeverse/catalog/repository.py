"""SQLite persistence for Pokémon reference data."""

import sqlite3
from datetime import UTC, datetime
from os import PathLike
from pathlib import Path
from types import TracebackType
from typing import Self

from pokeverse.catalog.models import Pokemon, PokemonType

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pokemon (
    pokedex_id  INTEGER PRIMARY KEY CHECK (pokedex_id > 0),
    name        TEXT    NOT NULL UNIQUE,
    updated_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS pokemon_type (
    pokedex_id  INTEGER NOT NULL REFERENCES pokemon (pokedex_id) ON DELETE CASCADE,
    slot        INTEGER NOT NULL CHECK (slot IN (1, 2)),
    type        TEXT    NOT NULL,
    PRIMARY KEY (pokedex_id, slot),
    UNIQUE (pokedex_id, type)
);

CREATE INDEX IF NOT EXISTS idx_pokemon_type_type ON pokemon_type (type);
"""


class CatalogSchemaError(Exception):
    """The database was created by an incompatible schema version."""


class SqlitePokemonRepository:
    """Stores and retrieves validated ``Pokemon`` records in SQLite.

    ``path`` may be a file path or ``":memory:"``. Parent directories are created
    as needed. Use as a context manager, or call ``close()`` when finished.
    """

    def __init__(self, path: str | PathLike[str]) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def _migrate(self) -> None:
        (current,) = self._connection.execute("PRAGMA user_version").fetchone()
        if current == SCHEMA_VERSION:
            return
        if current != 0:
            raise CatalogSchemaError(
                f"Unsupported catalog schema version {current} (expected {SCHEMA_VERSION})"
            )
        with self._connection:
            self._connection.executescript(_SCHEMA)
            self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def save(self, pokemon: Pokemon) -> None:
        """Insert or replace a Pokémon and its types atomically."""
        now = datetime.now(UTC).isoformat()
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO pokemon (pokedex_id, name, updated_at) VALUES (?, ?, ?)
                ON CONFLICT (pokedex_id) DO UPDATE
                    SET name = excluded.name, updated_at = excluded.updated_at
                """,
                (pokemon.pokedex_id, pokemon.name, now),
            )
            self._connection.execute(
                "DELETE FROM pokemon_type WHERE pokedex_id = ?", (pokemon.pokedex_id,)
            )
            self._connection.executemany(
                "INSERT INTO pokemon_type (pokedex_id, slot, type) VALUES (?, ?, ?)",
                [
                    (pokemon.pokedex_id, slot, pokemon_type.value)
                    for slot, pokemon_type in enumerate(pokemon.types, start=1)
                ],
            )

    def get_by_id(self, pokedex_id: int) -> Pokemon | None:
        row = self._connection.execute(
            "SELECT pokedex_id, name FROM pokemon WHERE pokedex_id = ?", (pokedex_id,)
        ).fetchone()
        return self._to_pokemon(row) if row else None

    def get_by_name(self, name: str) -> Pokemon | None:
        row = self._connection.execute(
            "SELECT pokedex_id, name FROM pokemon WHERE name = ?", (name,)
        ).fetchone()
        return self._to_pokemon(row) if row else None

    def list_all(self) -> list[Pokemon]:
        rows = self._connection.execute(
            "SELECT pokedex_id, name FROM pokemon ORDER BY pokedex_id"
        ).fetchall()
        return [self._to_pokemon(row) for row in rows]

    def count(self) -> int:
        (total,) = self._connection.execute("SELECT COUNT(*) FROM pokemon").fetchone()
        return total

    def _to_pokemon(self, row: tuple[int, str]) -> Pokemon:
        pokedex_id, name = row
        type_rows = self._connection.execute(
            "SELECT type FROM pokemon_type WHERE pokedex_id = ? ORDER BY slot", (pokedex_id,)
        ).fetchall()
        return Pokemon(
            pokedex_id=pokedex_id,
            name=name,
            types=tuple(PokemonType(type_name) for (type_name,) in type_rows),
        )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
