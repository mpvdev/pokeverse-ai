"""The Team domain model."""

from dataclasses import dataclass
from typing import Any

from pokeverse.catalog import Pokemon

MAX_TEAM_SIZE = 6


@dataclass(frozen=True, slots=True)
class Team:
    """An immutable team of 1-6 Pokémon; the same species may appear more than once."""

    members: tuple[Pokemon, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.members, tuple):
            raise ValueError("members must be a tuple")
        if not 1 <= len(self.members) <= MAX_TEAM_SIZE:
            raise ValueError(f"a team must have between 1 and {MAX_TEAM_SIZE} Pokémon")
        if not all(isinstance(member, Pokemon) for member in self.members):
            raise ValueError("members must be Pokemon")

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(member.name for member in self.members)

    def to_dict(self) -> dict[str, Any]:
        # Team analysis is type-based, so base stats would only cost tokens in agent tools.
        return {"members": [member.to_dict(stats=False) for member in self.members]}
