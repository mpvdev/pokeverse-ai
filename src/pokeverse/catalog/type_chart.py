"""Deterministic type effectiveness (Generation 6+ chart)."""

from collections.abc import Iterable, Mapping
from math import prod

from pokeverse.catalog.models import PokemonType

T = PokemonType

# Attacking type -> defending types it does not hit for 1x. Omitted pairs are 1x.
TYPE_CHART: Mapping[PokemonType, Mapping[PokemonType, float]] = {
    T.NORMAL: {T.ROCK: 0.5, T.GHOST: 0, T.STEEL: 0.5},
    T.FIRE: {
        T.FIRE: 0.5, T.WATER: 0.5, T.GRASS: 2, T.ICE: 2, T.BUG: 2, T.ROCK: 0.5,
        T.DRAGON: 0.5, T.STEEL: 2,
    },
    T.WATER: {T.FIRE: 2, T.WATER: 0.5, T.GRASS: 0.5, T.GROUND: 2, T.ROCK: 2, T.DRAGON: 0.5},
    T.ELECTRIC: {
        T.WATER: 2, T.ELECTRIC: 0.5, T.GRASS: 0.5, T.GROUND: 0, T.FLYING: 2, T.DRAGON: 0.5,
    },
    T.GRASS: {
        T.FIRE: 0.5, T.WATER: 2, T.GRASS: 0.5, T.POISON: 0.5, T.GROUND: 2, T.FLYING: 0.5,
        T.BUG: 0.5, T.ROCK: 2, T.DRAGON: 0.5, T.STEEL: 0.5,
    },
    T.ICE: {
        T.FIRE: 0.5, T.WATER: 0.5, T.GRASS: 2, T.ICE: 0.5, T.GROUND: 2, T.FLYING: 2,
        T.DRAGON: 2, T.STEEL: 0.5,
    },
    T.FIGHTING: {
        T.NORMAL: 2, T.ICE: 2, T.POISON: 0.5, T.FLYING: 0.5, T.PSYCHIC: 0.5, T.BUG: 0.5,
        T.ROCK: 2, T.GHOST: 0, T.DARK: 2, T.STEEL: 2, T.FAIRY: 0.5,
    },
    T.POISON: {
        T.GRASS: 2, T.POISON: 0.5, T.GROUND: 0.5, T.ROCK: 0.5, T.GHOST: 0.5, T.STEEL: 0,
        T.FAIRY: 2,
    },
    T.GROUND: {
        T.FIRE: 2, T.ELECTRIC: 2, T.GRASS: 0.5, T.POISON: 2, T.FLYING: 0, T.BUG: 0.5,
        T.ROCK: 2, T.STEEL: 2,
    },
    T.FLYING: {
        T.ELECTRIC: 0.5, T.GRASS: 2, T.FIGHTING: 2, T.BUG: 2, T.ROCK: 0.5, T.STEEL: 0.5,
    },
    T.PSYCHIC: {T.FIGHTING: 2, T.POISON: 2, T.PSYCHIC: 0.5, T.DARK: 0, T.STEEL: 0.5},
    T.BUG: {
        T.FIRE: 0.5, T.GRASS: 2, T.FIGHTING: 0.5, T.POISON: 0.5, T.FLYING: 0.5, T.PSYCHIC: 2,
        T.GHOST: 0.5, T.DARK: 2, T.STEEL: 0.5, T.FAIRY: 0.5,
    },
    T.ROCK: {
        T.FIRE: 2, T.ICE: 2, T.FIGHTING: 0.5, T.GROUND: 0.5, T.FLYING: 2, T.BUG: 2,
        T.STEEL: 0.5,
    },
    T.GHOST: {T.NORMAL: 0, T.PSYCHIC: 2, T.GHOST: 2, T.DARK: 0.5},
    T.DRAGON: {T.DRAGON: 2, T.STEEL: 0.5, T.FAIRY: 0},
    T.DARK: {T.FIGHTING: 0.5, T.PSYCHIC: 2, T.GHOST: 2, T.DARK: 0.5, T.FAIRY: 0.5},
    T.STEEL: {
        T.FIRE: 0.5, T.WATER: 0.5, T.ELECTRIC: 0.5, T.ICE: 2, T.ROCK: 2, T.STEEL: 0.5,
        T.FAIRY: 2,
    },
    T.FAIRY: {
        T.FIRE: 0.5, T.FIGHTING: 2, T.POISON: 0.5, T.DRAGON: 2, T.DARK: 2, T.STEEL: 0.5,
    },
}  # fmt: skip


def effectiveness(attacking: PokemonType, defending: Iterable[PokemonType]) -> float:
    """Damage multiplier of an ``attacking``-type move against the ``defending`` types."""
    return float(prod(TYPE_CHART[attacking].get(defender, 1.0) for defender in defending))


def defensive_profile(defending: Iterable[PokemonType]) -> dict[str, dict[str, float]]:
    """Group every attacking type by its non-neutral multiplier against ``defending``."""
    types = tuple(defending)
    profile: dict[str, dict[str, float]] = {"weak_to": {}, "resists": {}, "immune_to": {}}
    for attacking in PokemonType:
        multiplier = effectiveness(attacking, types)
        if multiplier == 0:
            profile["immune_to"][attacking.value] = 0.0
        elif multiplier > 1:
            profile["weak_to"][attacking.value] = multiplier
        elif multiplier < 1:
            profile["resists"][attacking.value] = multiplier
    return profile
