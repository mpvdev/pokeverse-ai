"""Deterministic, type-based team analysis (no moves, abilities or stats yet)."""

from dataclasses import dataclass
from typing import Any

from pokeverse.catalog import PokemonType
from pokeverse.catalog.type_chart import effectiveness
from pokeverse.teams.models import Team

# A type is a vulnerability when at least this many members are weak to it
# and weak members outnumber those that resist or are immune.
MIN_WEAK_MEMBERS = 2


@dataclass(frozen=True, slots=True)
class TypeExposure:
    """How one attacking type affects each team member."""

    attacking_type: PokemonType
    weak: tuple[str, ...]
    resists: tuple[str, ...]
    immune: tuple[str, ...]

    @property
    def is_vulnerability(self) -> bool:
        return len(self.weak) >= MIN_WEAK_MEMBERS and len(self.weak) > len(self.resists) + len(
            self.immune
        )

    @property
    def is_unresisted(self) -> bool:
        return not self.resists and not self.immune

    def to_dict(self) -> dict[str, Any]:
        return {
            "attacking_type": self.attacking_type.value,
            "weak": list(self.weak),
            "resists": list(self.resists),
            "immune": list(self.immune),
        }


@dataclass(frozen=True, slots=True)
class TeamAnalysis:
    team: Team
    exposures: tuple[TypeExposure, ...]
    # Defending types none of the team's own types hit super-effectively (STAB only).
    offensive_gaps: tuple[PokemonType, ...]

    @property
    def vulnerabilities(self) -> tuple[TypeExposure, ...]:
        return tuple(exposure for exposure in self.exposures if exposure.is_vulnerability)

    @property
    def unresisted(self) -> tuple[PokemonType, ...]:
        return tuple(e.attacking_type for e in self.exposures if e.is_unresisted)

    def to_dict(self) -> dict[str, Any]:
        return {
            "team": self.team.to_dict(),
            "vulnerabilities": [exposure.to_dict() for exposure in self.vulnerabilities],
            "unresisted": [pokemon_type.value for pokemon_type in self.unresisted],
            "offensive_gaps": [pokemon_type.value for pokemon_type in self.offensive_gaps],
            "exposures": [exposure.to_dict() for exposure in self.exposures],
        }


def _exposure(team: Team, attacking: PokemonType) -> TypeExposure:
    weak, resists, immune = [], [], []
    for member in team.members:
        multiplier = effectiveness(attacking, member.types)
        if multiplier == 0:
            immune.append(member.name)
        elif multiplier > 1:
            weak.append(member.name)
        elif multiplier < 1:
            resists.append(member.name)
    return TypeExposure(attacking, tuple(weak), tuple(resists), tuple(immune))


def analyze_team(team: Team) -> TeamAnalysis:
    attacking_types = {pokemon_type for member in team.members for pokemon_type in member.types}
    offensive_gaps = tuple(
        defending
        for defending in PokemonType
        if all(effectiveness(attacking, (defending,)) <= 1 for attacking in attacking_types)
    )
    return TeamAnalysis(
        team=team,
        exposures=tuple(_exposure(team, attacking) for attacking in PokemonType),
        offensive_gaps=offensive_gaps,
    )
