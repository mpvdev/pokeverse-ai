"""Deterministic one-on-one matchups between battlers, for pre-battle analysis."""

import math
from typing import Any

from pokeverse.battles.battler import Battler
from pokeverse.battles.damage import damage_range, expected_damage
from pokeverse.battles.stats import battle_stats
from pokeverse.catalog import Move
from pokeverse.model import FrozenModel


def _best_move(attacker: Battler, defender: Battler) -> Move:
    return max(
        attacker.moves,
        key=lambda move: expected_damage(attacker.pokemon, defender.pokemon, move),
    )


def _hits_to_ko(low: int, hp: int) -> int | None:
    return math.ceil(hp / low) if low > 0 else None


class Matchup(FrozenModel):
    """A full-HP one-on-one; hit counts use minimum rolls and ignore misses and critical hits."""

    attacker: Battler
    defender: Battler
    move: Move
    damage: tuple[int, int]
    reply: Move
    reply_damage: tuple[int, int]
    moves_first: bool | None
    hits_to_ko: int | None
    hits_to_be_ko: int | None

    @property
    def wins(self) -> bool:
        if self.hits_to_ko is None:
            return False
        if self.hits_to_be_ko is None or self.hits_to_ko < self.hits_to_be_ko:
            return True
        return self.hits_to_ko == self.hits_to_be_ko and self.moves_first is True

    def describe(self) -> str:
        own = self.attacker.pokemon.display_name
        foe = self.defender.pokemon.display_name
        own_hp = battle_stats(self.attacker.pokemon.stats).hp
        foe_hp = battle_stats(self.defender.pokemon.stats).hp
        order = {True: f"{own} moves first", False: f"{foe} moves first", None: "speed tie"}
        return (
            f"{own} vs {foe}: {own}'s {self.move.display_name} "
            f"{_percent(self.damage, foe_hp)}, KO in {_hits(self.hits_to_ko)}; "
            f"{foe}'s {self.reply.display_name} {_percent(self.reply_damage, own_hp)}, "
            f"KO in {_hits(self.hits_to_be_ko)}; {order[self.moves_first]}; "
            f"one-on-one: {own if self.wins else foe} wins."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attacker": self.attacker.pokemon.name,
            "defender": self.defender.pokemon.name,
            "move": self.move.name,
            "damage": list(self.damage),
            "reply": self.reply.name,
            "reply_damage": list(self.reply_damage),
            "moves_first": self.moves_first,
            "hits_to_ko": self.hits_to_ko,
            "hits_to_be_ko": self.hits_to_be_ko,
            "wins": self.wins,
        }


def _percent(damage: tuple[int, int], hp: int) -> str:
    low, high = damage
    if high == 0:
        return "no effect"
    return f"{low / hp:.0%}-{high / hp:.0%}"


def _hits(count: int | None) -> str:
    if count is None:
        return "never"
    return "1 hit" if count == 1 else f"{count} hits"


def matchup(attacker: Battler, defender: Battler) -> Matchup:
    move = _best_move(attacker, defender)
    reply = _best_move(defender, attacker)
    damage = damage_range(attacker.pokemon, defender.pokemon, move)
    reply_damage = damage_range(defender.pokemon, attacker.pokemon, reply)
    own = (move.priority, battle_stats(attacker.pokemon.stats).speed)
    foe = (reply.priority, battle_stats(defender.pokemon.stats).speed)
    return Matchup(
        attacker=attacker,
        defender=defender,
        move=move,
        damage=damage,
        reply=reply,
        reply_damage=reply_damage,
        moves_first=None if own == foe else own > foe,
        hits_to_ko=_hits_to_ko(damage[0], battle_stats(defender.pokemon.stats).hp),
        hits_to_be_ko=_hits_to_ko(reply_damage[0], battle_stats(attacker.pokemon.stats).hp),
    )
