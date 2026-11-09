"""The Team domain model."""

from typing import Any

from pydantic import field_validator

from pokeverse.catalog import Pokemon
from pokeverse.model import FrozenModel

MAX_TEAM_SIZE = 6


class Team(FrozenModel):
    """An immutable team of 1-6 Pokémon; the same species may appear more than once."""

    members: tuple[Pokemon, ...]

    @field_validator("members")
    @classmethod
    def _team_size(cls, members: tuple[Pokemon, ...]) -> tuple[Pokemon, ...]:
        if not 1 <= len(members) <= MAX_TEAM_SIZE:
            raise ValueError(f"a team must have between 1 and {MAX_TEAM_SIZE} Pokémon")
        return members

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(member.name for member in self.members)

    def to_dict(self) -> dict[str, Any]:
        return {"members": [member.to_dict(stats=False) for member in self.members]}
