"""Baseline players: code-only policies to compare agents against."""

import random

from pokeverse.battles.damage import damage_range
from pokeverse.battles.engine import Action, BattleState, Combatant, Switch, UseMove


class RandomPlayer:
    """Any legal action, uniformly at random."""

    name = "random"

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng

    def choose(self, state: BattleState, side: int, options: tuple[Action, ...]) -> Action:
        return self._rng.choice(options)


class GreedyPlayer:
    """The move with the highest expected damage this turn; switches only when no move can hurt."""

    name = "greedy"

    def choose(self, state: BattleState, side: int, options: tuple[Action, ...]) -> Action:
        own = state.sides[side]
        foe = state.sides[1 - side].current
        moves = [action for action in options if isinstance(action, UseMove)]
        switches = [action for action in options if isinstance(action, Switch)]

        if moves:
            best = max(moves, key=lambda action: self._move_key(own.current, foe, action.index))
            if self._move_key(own.current, foe, best.index)[0] > 0 or not switches:
                return best
        return max(switches, key=lambda action: self._best_value(own.team[action.index], foe))

    @staticmethod
    def _value(attacker: Combatant, foe: Combatant, index: int) -> float:
        move = attacker.battler.moves[index]
        low, high = damage_range(attacker.battler.pokemon, foe.battler.pokemon, move)
        return min((low + high) / 2, foe.hp) * (move.accuracy or 100) / 100

    def _move_key(self, attacker: Combatant, foe: Combatant, index: int) -> tuple[float, int]:
        return self._value(attacker, foe, index), attacker.battler.moves[index].priority

    def _best_value(self, combatant: Combatant, foe: Combatant) -> float:
        return max(self._value(combatant, foe, i) for i in range(len(combatant.battler.moves)))


PLAYER_NAMES = ("greedy", "random")


def make_player(name: str, rng: random.Random) -> RandomPlayer | GreedyPlayer:
    if name == "greedy":
        return GreedyPlayer()
    if name == "random":
        return RandomPlayer(rng)
    raise ValueError(f"unknown player {name!r}; choose from {', '.join(PLAYER_NAMES)}")
