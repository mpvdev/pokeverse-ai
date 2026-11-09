"""Deterministic battle mechanics."""

from pokeverse.battles.battler import MAX_MOVES, Battler, load_battler
from pokeverse.battles.damage import (
    CRITICAL_HIT_ODDS,
    MAX_ROLL,
    MIN_ROLL,
    DamageRoll,
    calculate_damage,
    damage_range,
    roll_damage,
)
from pokeverse.battles.stats import LEVEL, BattleStats, battle_stats

__all__ = [
    "CRITICAL_HIT_ODDS",
    "LEVEL",
    "MAX_MOVES",
    "MAX_ROLL",
    "MIN_ROLL",
    "BattleStats",
    "Battler",
    "DamageRoll",
    "battle_stats",
    "calculate_damage",
    "damage_range",
    "load_battler",
    "roll_damage",
]
