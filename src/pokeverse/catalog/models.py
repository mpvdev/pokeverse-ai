"""Core domain models for the Pokémon catalog."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Pokemon:
    """A validated, immutable Pokémon reference record."""

    pokedex_id: int
    name: str
    types: tuple[str, ...]

    def __post_init__(self) -> None:
        if isinstance(self.pokedex_id, bool) or not isinstance(self.pokedex_id, int):
            raise ValueError("pokedex_id must be an integer")
        if self.pokedex_id <= 0:
            raise ValueError("pokedex_id must be positive")

        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must be a non-empty string")

        if not isinstance(self.types, tuple) or not self.types:
            raise ValueError("types must be a non-empty tuple")
        if any(
            not isinstance(pokemon_type, str) or not pokemon_type.strip()
            for pokemon_type in self.types
        ):
            raise ValueError("types must contain non-empty strings")
