"""SQLite persistence for Pokémon reference data."""

import json
import sqlite3
from datetime import UTC, datetime
from os import PathLike
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from pokeverse.catalog.models import BaseStats, DamageClass, Move, Pokemon, PokemonType

SCHEMA_VERSION = 4
UPGRADABLE_VERSIONS = (0, 1, 2, 3)

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

CREATE TABLE IF NOT EXISTS pokemon_stats (
    pokedex_id       INTEGER PRIMARY KEY REFERENCES pokemon (pokedex_id) ON DELETE CASCADE,
    hp               INTEGER NOT NULL CHECK (hp BETWEEN 1 AND 255),
    attack           INTEGER NOT NULL CHECK (attack BETWEEN 1 AND 255),
    defense          INTEGER NOT NULL CHECK (defense BETWEEN 1 AND 255),
    special_attack   INTEGER NOT NULL CHECK (special_attack BETWEEN 1 AND 255),
    special_defense  INTEGER NOT NULL CHECK (special_defense BETWEEN 1 AND 255),
    speed            INTEGER NOT NULL CHECK (speed BETWEEN 1 AND 255)
);

CREATE TABLE IF NOT EXISTS pokemon_learnset (
    pokedex_id  INTEGER PRIMARY KEY REFERENCES pokemon (pokedex_id) ON DELETE CASCADE,
    moves       TEXT    NOT NULL CHECK (json_valid(moves))
);

CREATE TABLE IF NOT EXISTS move (
    move_id       INTEGER PRIMARY KEY CHECK (move_id > 0),
    name          TEXT    NOT NULL UNIQUE,
    type          TEXT    NOT NULL,
    damage_class  TEXT    NOT NULL CHECK (damage_class IN ('physical', 'special', 'status')),
    power         INTEGER CHECK (power BETWEEN 1 AND 250),
    accuracy      INTEGER CHECK (accuracy BETWEEN 1 AND 100),
    priority      INTEGER NOT NULL CHECK (priority BETWEEN -7 AND 5),
    pp            INTEGER NOT NULL CHECK (pp BETWEEN 1 AND 40),
    updated_at    TEXT    NOT NULL
);
"""

_SELECT = """
SELECT p.pokedex_id, p.name, l.moves, s.hp, s.attack, s.defense,
       s.special_attack, s.special_defense, s.speed
FROM pokemon p
JOIN pokemon_stats s USING (pokedex_id)
JOIN pokemon_learnset l USING (pokedex_id)
"""

_SELECT_MOVE = """
SELECT move_id, name, type, damage_class, power, accuracy, priority, pp FROM move
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
        if current not in UPGRADABLE_VERSIONS:
            raise CatalogSchemaError(
                f"Unsupported catalog schema version {current} (expected {SCHEMA_VERSION})"
            )
        with self._connection:
            self._connection.executescript(_SCHEMA)
            self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def save(self, pokemon: Pokemon) -> None:
        """Insert or replace a Pokémon, its types and its base stats atomically."""
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
            stats = pokemon.stats
            self._connection.execute(
                """
                INSERT OR REPLACE INTO pokemon_stats (pokedex_id, hp, attack, defense,
                    special_attack, special_defense, speed) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pokemon.pokedex_id,
                    stats.hp,
                    stats.attack,
                    stats.defense,
                    stats.special_attack,
                    stats.special_defense,
                    stats.speed,
                ),
            )
            self._connection.execute(
                "INSERT OR REPLACE INTO pokemon_learnset (pokedex_id, moves) VALUES (?, ?)",
                (pokemon.pokedex_id, json.dumps(sorted(pokemon.learnset))),
            )

    def get_by_id(self, pokedex_id: int) -> Pokemon | None:
        row = self._connection.execute(
            f"{_SELECT} WHERE p.pokedex_id = ?", (pokedex_id,)
        ).fetchone()
        return self._to_pokemon(row) if row else None

    def get_by_name(self, name: str) -> Pokemon | None:
        row = self._connection.execute(f"{_SELECT} WHERE p.name = ?", (name,)).fetchone()
        return self._to_pokemon(row) if row else None

    def list_all(self) -> list[Pokemon]:
        rows = self._connection.execute(f"{_SELECT} ORDER BY p.pokedex_id").fetchall()
        return [self._to_pokemon(row) for row in rows]

    def count(self) -> int:
        (total,) = self._connection.execute(
            "SELECT COUNT(*) FROM pokemon_stats JOIN pokemon_learnset USING (pokedex_id)"
        ).fetchone()
        return total

    def _to_pokemon(self, row: tuple[Any, ...]) -> Pokemon:
        pokedex_id, name, learnset, *stats = row
        type_rows = self._connection.execute(
            "SELECT type FROM pokemon_type WHERE pokedex_id = ? ORDER BY slot", (pokedex_id,)
        ).fetchall()
        return Pokemon(
            pokedex_id=pokedex_id,
            name=name,
            types=tuple(PokemonType(type_name) for (type_name,) in type_rows),
            stats=BaseStats(*stats),
            learnset=frozenset(json.loads(learnset)),
        )

    def save_move(self, move: Move) -> None:
        """Insert or replace a move."""
        with self._connection:
            self._connection.execute(
                """
                INSERT OR REPLACE INTO move (move_id, name, type, damage_class, power,
                    accuracy, priority, pp, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    move.move_id,
                    move.name,
                    move.type.value,
                    move.damage_class.value,
                    move.power,
                    move.accuracy,
                    move.priority,
                    move.pp,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def get_move_by_id(self, move_id: int) -> Move | None:
        row = self._connection.execute(f"{_SELECT_MOVE} WHERE move_id = ?", (move_id,)).fetchone()
        return self._to_move(row) if row else None

    def get_move_by_name(self, name: str) -> Move | None:
        row = self._connection.execute(f"{_SELECT_MOVE} WHERE name = ?", (name,)).fetchone()
        return self._to_move(row) if row else None

    @staticmethod
    def _to_move(row: tuple[Any, ...]) -> Move:
        move_id, name, move_type, damage_class, power, accuracy, priority, pp = row
        return Move(
            move_id=move_id,
            name=name,
            type=PokemonType(move_type),
            damage_class=DamageClass(damage_class),
            power=power,
            accuracy=accuracy,
            priority=priority,
            pp=pp,
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
