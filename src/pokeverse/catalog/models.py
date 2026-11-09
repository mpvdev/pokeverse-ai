"""Core domain models for the Pokémon catalog."""

import re
from dataclasses import asdict, dataclass, fields
from enum import StrEnum
from typing import Any

# Matches PokéAPI resource slugs, e.g. "pikachu", "mr-mime", "porygon2".
NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

MAX_TYPES = 2

MIN_BASE_STAT = 1
MAX_BASE_STAT = 255

MAX_MOVE_POWER = 250
MIN_PRIORITY = -7
MAX_PRIORITY = 5
MAX_PP = 40


def _check_range(name: str, value: object, low: int, high: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")


class PokemonType(StrEnum):
    """The 18 elemental types. Values match PokéAPI type names."""

    NORMAL = "normal"
    FIRE = "fire"
    WATER = "water"
    ELECTRIC = "electric"
    GRASS = "grass"
    ICE = "ice"
    FIGHTING = "fighting"
    POISON = "poison"
    GROUND = "ground"
    FLYING = "flying"
    PSYCHIC = "psychic"
    BUG = "bug"
    ROCK = "rock"
    GHOST = "ghost"
    DRAGON = "dragon"
    DARK = "dark"
    STEEL = "steel"
    FAIRY = "fairy"


@dataclass(frozen=True, slots=True)
class BaseStats:
    """A species' six base stats. Field names match PokéAPI stat names with ``_`` for ``-``."""

    hp: int
    attack: int
    defense: int
    special_attack: int
    special_defense: int
    speed: int

    def __post_init__(self) -> None:
        for stat in fields(self):
            _check_range(stat.name, getattr(self, stat.name), MIN_BASE_STAT, MAX_BASE_STAT)

    @property
    def total(self) -> int:
        return sum(self.to_dict().values())

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Pokemon:
    """A validated, immutable Pokémon reference record.

    ``name`` must be a canonical PokéAPI slug (lowercase, hyphen-separated).
    Normalizing raw input into that form is the responsibility of callers,
    such as the ingestion pipeline or CLI, not of this model.
    """

    pokedex_id: int
    name: str
    types: tuple[PokemonType, ...]
    stats: BaseStats
    learnset: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if isinstance(self.pokedex_id, bool) or not isinstance(self.pokedex_id, int):
            raise ValueError("pokedex_id must be an integer")
        if self.pokedex_id <= 0:
            raise ValueError("pokedex_id must be positive")

        if not isinstance(self.name, str) or not NAME_PATTERN.fullmatch(self.name):
            raise ValueError("name must be a lowercase, hyphen-separated slug (e.g. 'mr-mime')")

        if not isinstance(self.types, tuple):
            raise ValueError("types must be a tuple")
        if not 1 <= len(self.types) <= MAX_TYPES:
            raise ValueError(f"types must contain between 1 and {MAX_TYPES} entries")
        if not all(isinstance(pokemon_type, PokemonType) for pokemon_type in self.types):
            raise ValueError("types must contain only PokemonType values")
        if len(set(self.types)) != len(self.types):
            raise ValueError("types must not contain duplicates")

        if not isinstance(self.stats, BaseStats):
            raise ValueError("stats must be BaseStats")

        if not isinstance(self.learnset, frozenset) or not all(
            isinstance(move, str) and NAME_PATTERN.fullmatch(move) for move in self.learnset
        ):
            raise ValueError("learnset must be a frozenset of move slugs")

    @property
    def display_name(self) -> str:
        """Human-friendly name derived from the slug (e.g. ``mr-mime`` -> ``Mr Mime``)."""
        return self.name.replace("-", " ").title()

    def to_dict(self, *, stats: bool = True) -> dict[str, Any]:
        """JSON-serializable representation, stable for CLI output and LLM tools.

        ``stats=False`` omits base stats where only identity and types matter (saves tokens).
        The learnset (often 100+ names) is never included.
        """
        data: dict[str, Any] = {
            "pokedex_id": self.pokedex_id,
            "name": self.name,
            "types": [pokemon_type.value for pokemon_type in self.types],
        }
        if stats:
            data["base_stats"] = self.stats.to_dict()
        return data


class DamageClass(StrEnum):
    """Which attack/defense stats a move uses; status moves deal no direct damage."""

    PHYSICAL = "physical"
    SPECIAL = "special"
    STATUS = "status"


@dataclass(frozen=True, slots=True)
class Move:
    """A validated, immutable move reference record (values as in PokéAPI).

    ``power`` is ``None`` for status moves and for damaging moves whose damage is not
    power-based (e.g. Seismic Toss). ``accuracy`` is ``None`` for moves that never miss.
    """

    move_id: int
    name: str
    type: PokemonType
    damage_class: DamageClass
    power: int | None
    accuracy: int | None
    priority: int
    pp: int

    def __post_init__(self) -> None:
        if isinstance(self.move_id, bool) or not isinstance(self.move_id, int):
            raise ValueError("move_id must be an integer")
        if self.move_id <= 0:
            raise ValueError("move_id must be positive")
        if not isinstance(self.name, str) or not NAME_PATTERN.fullmatch(self.name):
            raise ValueError("name must be a lowercase, hyphen-separated slug (e.g. 'u-turn')")
        if not isinstance(self.type, PokemonType):
            raise ValueError("type must be a PokemonType")
        if not isinstance(self.damage_class, DamageClass):
            raise ValueError("damage_class must be a DamageClass")
        if self.power is not None:
            if self.damage_class is DamageClass.STATUS:
                raise ValueError("status moves must not have power")
            _check_range("power", self.power, 1, MAX_MOVE_POWER)
        if self.accuracy is not None:
            _check_range("accuracy", self.accuracy, 1, 100)
        _check_range("priority", self.priority, MIN_PRIORITY, MAX_PRIORITY)
        _check_range("pp", self.pp, 1, MAX_PP)

    @property
    def display_name(self) -> str:
        return self.name.replace("-", " ").title()

    def to_dict(self) -> dict[str, Any]:
        return {
            "move_id": self.move_id,
            "name": self.name,
            "type": self.type.value,
            "damage_class": self.damage_class.value,
            "power": self.power,
            "accuracy": self.accuracy,
            "priority": self.priority,
            "pp": self.pp,
        }


def parse_identifier(name_or_id: str | int) -> str | int:
    """Lightly normalize a user-supplied Pokémon name or Pokédex id.

    Returns a positive ``int`` id, or a stripped, lowercased name. This is not
    full slug normalization (``"Mr. Mime"`` is not converted to ``mr-mime``).
    """
    if isinstance(name_or_id, bool):
        raise ValueError("Pokémon identifier must be a name or a positive integer id")
    if isinstance(name_or_id, int):
        if name_or_id <= 0:
            raise ValueError("Pokémon id must be positive")
        return name_or_id
    if not isinstance(name_or_id, str):
        raise ValueError("Pokémon identifier must be a name or a positive integer id")
    identifier = name_or_id.strip().lower()
    if not identifier:
        raise ValueError("Pokémon name must not be empty")
    return identifier
