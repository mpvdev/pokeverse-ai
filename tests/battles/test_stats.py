from pokeverse.battles import BattleStats, battle_stats
from pokeverse.catalog import BaseStats


def test_garchomp_level_50_stats() -> None:
    assert battle_stats(
        BaseStats(hp=108, attack=130, defense=95, special_attack=80, special_defense=85, speed=102)
    ) == BattleStats(
        hp=183, attack=150, defense=115, special_attack=100, special_defense=105, speed=122
    )


def test_pikachu_level_50_stats() -> None:
    assert battle_stats(
        BaseStats(hp=35, attack=55, defense=40, special_attack=50, special_defense=50, speed=90)
    ) == BattleStats(
        hp=110, attack=75, defense=60, special_attack=70, special_defense=70, speed=110
    )


def test_highest_and_lowest_base_stats() -> None:
    assert (
        battle_stats(
            BaseStats(
                hp=255, attack=10, defense=10, special_attack=75, special_defense=135, speed=55
            )
        ).hp
        == 330
    )
    assert (
        battle_stats(
            BaseStats(hp=2, attack=1, defense=1, special_attack=1, special_defense=1, speed=1)
        ).attack
        == 21
    )


def test_base_hp_of_one_stays_one() -> None:
    assert (
        battle_stats(
            BaseStats(hp=1, attack=90, defense=45, special_attack=30, special_defense=30, speed=40)
        ).hp
        == 1
    )


def test_to_dict() -> None:
    assert battle_stats(
        BaseStats(hp=35, attack=55, defense=40, special_attack=50, special_defense=50, speed=90)
    ).to_dict() == {
        "hp": 110,
        "attack": 75,
        "defense": 60,
        "special_attack": 70,
        "special_defense": 70,
        "speed": 110,
    }
