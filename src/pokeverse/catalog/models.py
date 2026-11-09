"""Core domain models for the Pokémon catalog."""

import re
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import Field, StringConstraints, field_validator, model_validator

from pokeverse.model import FrozenModel

# Matches PokéAPI resource slugs, e.g. "pikachu", "mr-mime", "porygon2".
NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

MAX_TYPES = 2

MIN_BASE_STAT = 1
MAX_BASE_STAT = 255

MAX_MOVE_POWER = 250
MIN_PRIORITY = -7
MAX_PRIORITY = 5
MAX_PP = 40

Slug = Annotated[str, StringConstraints(pattern=f"^{NAME_PATTERN.pattern}$")]
BaseStat = Annotated[int, Field(ge=MIN_BASE_STAT, le=MAX_BASE_STAT)]


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


class BaseStats(FrozenModel):
    """A species' six base stats. Field names match PokéAPI stat names with ``_`` for ``-``."""

    hp: BaseStat
    attack: BaseStat
    defense: BaseStat
    special_attack: BaseStat
    special_defense: BaseStat
    speed: BaseStat

    @property
    def total(self) -> int:
        return sum(self.to_dict().values())

    def to_dict(self) -> dict[str, int]:
        return self.model_dump()


class Pokemon(FrozenModel):
    """A validated, immutable Pokémon reference record.

    ``name`` must be a canonical PokéAPI slug (lowercase, hyphen-separated).
    Normalizing raw input into that form is the responsibility of callers,
    such as the ingestion pipeline or CLI, not of this model.
    """

    pokedex_id: int = Field(gt=0)
    name: Slug
    types: tuple[PokemonType, ...] = Field(min_length=1, max_length=MAX_TYPES)
    stats: BaseStats = Field(serialization_alias="base_stats")
    learnset: frozenset[Slug] = Field(default=frozenset(), exclude=True)

    @field_validator("types")
    @classmethod
    def _distinct_types(cls, types: tuple[PokemonType, ...]) -> tuple[PokemonType, ...]:
        if len(set(types)) != len(types):
            raise ValueError("types must not contain duplicates")
        return types

    @property
    def display_name(self) -> str:
        """Human-friendly name derived from the slug (e.g. ``mr-mime`` -> ``Mr Mime``)."""
        return self.name.replace("-", " ").title()

    def to_dict(self, *, stats: bool = True) -> dict[str, Any]:
        """JSON-serializable representation, stable for CLI output and LLM tools.

        ``stats=False`` omits base stats where only identity and types matter (saves tokens).
        The learnset (often 100+ names) is never included.
        """
        return self.model_dump(mode="json", by_alias=True, exclude=None if stats else {"stats"})


class DamageClass(StrEnum):
    """Which attack/defense stats a move uses; status moves deal no direct damage."""

    PHYSICAL = "physical"
    SPECIAL = "special"
    STATUS = "status"


class Move(FrozenModel):
    """A validated, immutable move reference record (values as in PokéAPI).

    ``power`` is ``None`` for status moves and for damaging moves whose damage is not
    power-based (e.g. Seismic Toss). ``accuracy`` is ``None`` for moves that never miss.
    """

    move_id: int = Field(gt=0)
    name: Slug
    type: PokemonType
    damage_class: DamageClass
    power: Annotated[int, Field(ge=1, le=MAX_MOVE_POWER)] | None
    accuracy: Annotated[int, Field(ge=1, le=100)] | None
    priority: int = Field(ge=MIN_PRIORITY, le=MAX_PRIORITY)
    pp: int = Field(ge=1, le=MAX_PP)

    @model_validator(mode="after")
    def _status_moves_have_no_power(self) -> Self:
        if self.damage_class is DamageClass.STATUS and self.power is not None:
            raise ValueError("status moves must not have power")
        return self

    @property
    def display_name(self) -> str:
        return self.name.replace("-", " ").title()

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class PokemonEntry(FrozenModel):
    """One line of the upstream Pokémon index: an id and its slug, no details."""

    pokedex_id: int = Field(gt=0)
    name: Slug


class PokemonIndex(FrozenModel):
    """One page of the upstream Pokémon index; ``count`` is the total across pages."""

    count: int = Field(ge=0)
    results: tuple[PokemonEntry, ...]


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
