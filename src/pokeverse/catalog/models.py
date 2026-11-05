"""Core domain models for the Pokémon catalog."""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# Matches PokéAPI resource slugs, e.g. "pikachu", "mr-mime", "porygon2".
NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

MAX_TYPES = 2


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
class Pokemon:
    """A validated, immutable Pokémon reference record.

    ``name`` must be a canonical PokéAPI slug (lowercase, hyphen-separated).
    Normalizing raw input into that form is the responsibility of callers,
    such as the ingestion pipeline or CLI, not of this model.
    """

    pokedex_id: int
    name: str
    types: tuple[PokemonType, ...]

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

    @property
    def display_name(self) -> str:
        """Human-friendly name derived from the slug (e.g. ``mr-mime`` -> ``Mr Mime``)."""
        return self.name.replace("-", " ").title()

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable representation, stable for CLI output and LLM tools."""
        return {
            "pokedex_id": self.pokedex_id,
            "name": self.name,
            "types": [pokemon_type.value for pokemon_type in self.types],
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
