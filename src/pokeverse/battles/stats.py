"""Battle stats derived from base stats under the fixed Phase 3 rules."""

from dataclasses import asdict, dataclass

from pokeverse.catalog import BaseStats

LEVEL = 50
IV = 31
EV = 0


@dataclass(frozen=True, slots=True)
class BattleStats:
    hp: int
    attack: int
    defense: int
    special_attack: int
    special_defense: int
    speed: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def _scaled(base: int) -> int:
    return (2 * base + IV + EV // 4) * LEVEL // 100


def battle_stats(base: BaseStats) -> BattleStats:
    """Stats at level 50 with 31 IVs, 0 EVs and a neutral nature; base HP 1 (Shedinja) stays 1."""
    return BattleStats(
        hp=1 if base.hp == 1 else _scaled(base.hp) + LEVEL + 10,
        attack=_scaled(base.attack) + 5,
        defense=_scaled(base.defense) + 5,
        special_attack=_scaled(base.special_attack) + 5,
        special_defense=_scaled(base.special_defense) + 5,
        speed=_scaled(base.speed) + 5,
    )
