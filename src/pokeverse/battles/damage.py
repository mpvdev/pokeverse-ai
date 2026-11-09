"""The Gen 6+ damage formula, following Pokémon Showdown's integer rounding."""

import math
import random
from dataclasses import dataclass

from pokeverse.battles.stats import LEVEL, battle_stats
from pokeverse.catalog import DamageClass, Move, Pokemon
from pokeverse.catalog.type_chart import effectiveness

MIN_ROLL = 85
MAX_ROLL = 100
CRITICAL_HIT_ODDS = 24
CRITICAL_MULTIPLIER = 1.5
STAB_MODIFIER = 6144


@dataclass(frozen=True, slots=True)
class DamageRoll:
    damage: int
    roll: int
    critical: bool
    effectiveness: float


def _modify(value: int, modifier: int) -> int:
    return (value * modifier + 2047) // 4096


def _attack_and_defense(attacker: Pokemon, defender: Pokemon, move: Move) -> tuple[int, int]:
    offense, defense = battle_stats(attacker.stats), battle_stats(defender.stats)
    if move.damage_class is DamageClass.PHYSICAL:
        return offense.attack, defense.defense
    return offense.special_attack, defense.special_defense


def calculate_damage(
    attacker: Pokemon,
    defender: Pokemon,
    move: Move,
    *,
    roll: int = MAX_ROLL,
    critical: bool = False,
) -> int:
    """Damage of one hit for a given random roll (85-100) and critical-hit outcome."""
    if move.damage_class is DamageClass.STATUS or move.power is None:
        raise ValueError(f"{move.name} does not deal power-based damage")
    if not MIN_ROLL <= roll <= MAX_ROLL:
        raise ValueError(f"roll must be between {MIN_ROLL} and {MAX_ROLL}")

    multiplier = effectiveness(move.type, defender.types)
    if multiplier == 0:
        return 0

    attack, defense = _attack_and_defense(attacker, defender, move)
    damage = (2 * LEVEL // 5 + 2) * move.power * attack // defense // 50 + 2
    if critical:
        damage = math.floor(damage * CRITICAL_MULTIPLIER)
    damage = damage * roll // 100
    if move.type in attacker.types:
        damage = _modify(damage, STAB_MODIFIER)
    steps = round(math.log2(multiplier))
    for _ in range(steps):
        damage *= 2
    for _ in range(-steps):
        damage //= 2
    return max(damage, 1)


def damage_range(attacker: Pokemon, defender: Pokemon, move: Move) -> tuple[int, int]:
    """Minimum and maximum damage without a critical hit."""
    return (
        calculate_damage(attacker, defender, move, roll=MIN_ROLL),
        calculate_damage(attacker, defender, move, roll=MAX_ROLL),
    )


def expected_damage(attacker: Pokemon, defender: Pokemon, move: Move) -> float:
    """Average non-critical damage weighted by the chance to hit."""
    low, high = damage_range(attacker, defender, move)
    return (low + high) / 2 * (move.accuracy or 100) / 100


def roll_damage(attacker: Pokemon, defender: Pokemon, move: Move, rng: random.Random) -> DamageRoll:
    """One hit with a random critical hit (1 in 24) and random roll, drawn from ``rng``."""
    critical = rng.randrange(CRITICAL_HIT_ODDS) == 0
    roll = rng.randint(MIN_ROLL, MAX_ROLL)
    return DamageRoll(
        damage=calculate_damage(attacker, defender, move, roll=roll, critical=critical),
        roll=roll,
        critical=critical,
        effectiveness=effectiveness(move.type, defender.types),
    )
