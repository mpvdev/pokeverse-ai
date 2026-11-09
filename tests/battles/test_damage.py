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

GARCHOMP = Pokemon(
    pokedex_id=445,
    name="garchomp",
    types=(T.DRAGON, T.GROUND),
    stats=BaseStats(
        hp=108, attack=130, defense=95, special_attack=80, special_defense=85, speed=102
    ),
)
PIKACHU = Pokemon(
    pokedex_id=25,
    name="pikachu",
    types=(T.ELECTRIC,),
    stats=BaseStats(hp=35, attack=55, defense=40, special_attack=50, special_defense=50, speed=90),
)
CHARIZARD = Pokemon(
    pokedex_id=6,
    name="charizard",
    types=(T.FIRE, T.FLYING),
    stats=BaseStats(
        hp=78, attack=84, defense=78, special_attack=109, special_defense=85, speed=100
    ),
)
GRASS_DRAGON = Pokemon(
    pokedex_id=1,
    name="grass-dragon",
    types=(T.GRASS, T.DRAGON),
    stats=BaseStats(hp=80, attack=80, defense=80, special_attack=80, special_defense=80, speed=80),
)
FEEBLE = Pokemon(
    pokedex_id=2,
    name="feeble",
    types=(T.NORMAL,),
    stats=BaseStats(hp=50, attack=1, defense=1, special_attack=1, special_defense=1, speed=1),
)
WALL = Pokemon(
    pokedex_id=3,
    name="wall",
    types=(T.STEEL, T.FIRE),
    stats=BaseStats(
        hp=50, attack=50, defense=255, special_attack=50, special_defense=255, speed=50
    ),
)

EARTHQUAKE = Move(
    move_id=89,
    name="earthquake",
    type=T.GROUND,
    damage_class=D.PHYSICAL,
    power=100,
    accuracy=100,
    priority=0,
    pp=10,
)
IRON_TAIL = Move(
    move_id=231,
    name="iron-tail",
    type=T.STEEL,
    damage_class=D.PHYSICAL,
    power=100,
    accuracy=75,
    priority=0,
    pp=15,
)
THUNDERBOLT = Move(
    move_id=85,
    name="thunderbolt",
    type=T.ELECTRIC,
    damage_class=D.SPECIAL,
    power=90,
    accuracy=100,
    priority=0,
    pp=15,
)
BUG_BITE = Move(
    move_id=450,
    name="bug-bite",
    type=T.BUG,
    damage_class=D.PHYSICAL,
    power=60,
    accuracy=100,
    priority=0,
    pp=20,
)
SWORDS_DANCE = Move(
    move_id=14,
    name="swords-dance",
    type=T.NORMAL,
    damage_class=D.STATUS,
    power=None,
    accuracy=None,
    priority=0,
    pp=20,
)
SEISMIC_TOSS = Move(
    move_id=69,
    name="seismic-toss",
    type=T.FIGHTING,
    damage_class=D.PHYSICAL,
    power=None,
    accuracy=100,
    priority=0,
    pp=20,
)


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
