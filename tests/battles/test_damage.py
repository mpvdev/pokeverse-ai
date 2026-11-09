import random

import pytest

from pokeverse.battles import (
    CRITICAL_HIT_ODDS,
    MAX_ROLL,
    MIN_ROLL,
    DamageRoll,
    calculate_damage,
    damage_range,
    roll_damage,
)
from pokeverse.catalog import BaseStats, DamageClass, Move, Pokemon, PokemonType

T = PokemonType
D = DamageClass

GARCHOMP = Pokemon(445, "garchomp", (T.DRAGON, T.GROUND), BaseStats(108, 130, 95, 80, 85, 102))
PIKACHU = Pokemon(25, "pikachu", (T.ELECTRIC,), BaseStats(35, 55, 40, 50, 50, 90))
CHARIZARD = Pokemon(6, "charizard", (T.FIRE, T.FLYING), BaseStats(78, 84, 78, 109, 85, 100))
GRASS_DRAGON = Pokemon(1, "grass-dragon", (T.GRASS, T.DRAGON), BaseStats(80, 80, 80, 80, 80, 80))
FEEBLE = Pokemon(2, "feeble", (T.NORMAL,), BaseStats(50, 1, 1, 1, 1, 1))
WALL = Pokemon(3, "wall", (T.STEEL, T.FIRE), BaseStats(50, 50, 255, 50, 255, 50))

EARTHQUAKE = Move(89, "earthquake", T.GROUND, D.PHYSICAL, 100, 100, 0, 10)
IRON_TAIL = Move(231, "iron-tail", T.STEEL, D.PHYSICAL, 100, 75, 0, 15)
THUNDERBOLT = Move(85, "thunderbolt", T.ELECTRIC, D.SPECIAL, 90, 100, 0, 15)
BUG_BITE = Move(450, "bug-bite", T.BUG, D.PHYSICAL, 60, 100, 0, 20)
SWORDS_DANCE = Move(14, "swords-dance", T.NORMAL, D.STATUS, None, None, 0, 20)
SEISMIC_TOSS = Move(69, "seismic-toss", T.FIGHTING, D.PHYSICAL, None, 100, 0, 20)


def test_super_effective_stab_range_rounds_half_down() -> None:
    assert damage_range(GARCHOMP, PIKACHU, EARTHQUAKE) == (284, 336)


def test_neutral_non_stab_range() -> None:
    assert damage_range(PIKACHU, GARCHOMP, IRON_TAIL) == (25, 30)


def test_double_resisted_special_stab_range() -> None:
    assert damage_range(PIKACHU, GRASS_DRAGON, THUNDERBOLT) == (9, 10)


def test_immunity_deals_no_damage() -> None:
    assert damage_range(GARCHOMP, CHARIZARD, EARTHQUAKE) == (0, 0)
    assert calculate_damage(PIKACHU, GARCHOMP, THUNDERBOLT, critical=True) == 0


def test_critical_hit_multiplies_before_the_roll() -> None:
    assert calculate_damage(GARCHOMP, PIKACHU, EARTHQUAKE, critical=True) == 504


def test_damage_is_at_least_one_unless_immune() -> None:
    assert calculate_damage(FEEBLE, WALL, BUG_BITE, roll=MIN_ROLL) == 1


@pytest.mark.parametrize("move", [SWORDS_DANCE, SEISMIC_TOSS])
def test_moves_without_power_are_rejected(move: Move) -> None:
    with pytest.raises(ValueError, match="power-based"):
        calculate_damage(GARCHOMP, PIKACHU, move)


@pytest.mark.parametrize("roll", [MIN_ROLL - 1, MAX_ROLL + 1])
def test_roll_must_be_in_range(roll: int) -> None:
    with pytest.raises(ValueError, match="roll"):
        calculate_damage(GARCHOMP, PIKACHU, EARTHQUAKE, roll=roll)


class ScriptedRng:
    def __init__(self, critical_draw: int, roll: int) -> None:
        self.critical_draw = critical_draw
        self.roll = roll

    def randrange(self, stop: int) -> int:
        assert stop == CRITICAL_HIT_ODDS
        return self.critical_draw

    def randint(self, low: int, high: int) -> int:
        assert (low, high) == (MIN_ROLL, MAX_ROLL)
        return self.roll


def test_roll_damage_uses_the_rng_for_critical_hits_and_rolls() -> None:
    critical = roll_damage(GARCHOMP, PIKACHU, EARTHQUAKE, ScriptedRng(0, MAX_ROLL))
    normal = roll_damage(GARCHOMP, PIKACHU, EARTHQUAKE, ScriptedRng(1, MIN_ROLL))

    assert (critical.damage, critical.critical, critical.roll) == (504, True, MAX_ROLL)
    assert (normal.damage, normal.critical, normal.roll) == (284, False, MIN_ROLL)
    assert normal.effectiveness == 2.0


def rolls(seed: int) -> list[DamageRoll]:
    rng = random.Random(seed)
    return [roll_damage(GARCHOMP, PIKACHU, EARTHQUAKE, rng) for _ in range(50)]


def test_seeded_rolls_are_reproducible_and_in_range() -> None:
    first = rolls(7)

    assert first == rolls(7)
    assert all(284 <= hit.damage <= 336 or hit.critical for hit in first)
