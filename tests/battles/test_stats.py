from pokeverse.battles import BattleStats, battle_stats
from pokeverse.catalog import BaseStats


def test_garchomp_level_50_stats() -> None:
    assert battle_stats(BaseStats(108, 130, 95, 80, 85, 102)) == BattleStats(
        183, 150, 115, 100, 105, 122
    )


def test_pikachu_level_50_stats() -> None:
    assert battle_stats(BaseStats(35, 55, 40, 50, 50, 90)) == BattleStats(110, 75, 60, 70, 70, 110)


def test_highest_and_lowest_base_stats() -> None:
    assert battle_stats(BaseStats(255, 10, 10, 75, 135, 55)).hp == 330
    assert battle_stats(BaseStats(2, 1, 1, 1, 1, 1)).attack == 21


def test_base_hp_of_one_stays_one() -> None:
    assert battle_stats(BaseStats(1, 90, 45, 30, 30, 40)).hp == 1


def test_to_dict() -> None:
    assert battle_stats(BaseStats(35, 55, 40, 50, 50, 90)).to_dict() == {
        "hp": 110,
        "attack": 75,
        "defense": 60,
        "special_attack": 70,
        "special_defense": 70,
        "speed": 110,
    }
