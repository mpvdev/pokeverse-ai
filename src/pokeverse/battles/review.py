"""Deterministic review of battle choices: clear-cut mistakes judged from the engine's facts."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from pokeverse.battles.damage import damage_range
from pokeverse.battles.engine import Action, BattleState, Combatant, Player, Switch, UseMove
from pokeverse.catalog import Move

MistakeKind = Literal["missed_ko", "no_effect", "switched_into_ko"]


@dataclass(frozen=True, slots=True)
class Choice:
    state: BattleState
    side: int
    options: tuple[Action, ...]
    action: Action


class RecordingPlayer:
    """Wraps any player and records every choice with the state it was made in."""

    def __init__(self, inner: Player) -> None:
        self.inner = inner
        self.choices: list[Choice] = []

    def choose(self, state: BattleState, side: int, options: tuple[Action, ...]) -> Action:
        action = self.inner.choose(state, side, options)
        self.choices.append(Choice(state, side, options, action))
        return action


@dataclass(frozen=True, slots=True)
class Mistake:
    turn: int
    side: int
    kind: MistakeKind
    chosen: str
    better: str
    detail: str

    def describe(self) -> str:
        return f"Turn {self.turn}: chose {self.chosen} instead of {self.better}; {self.detail}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "side": self.side,
            "kind": self.kind,
            "chosen": self.chosen,
            "better": self.better,
            "detail": self.detail,
        }


def _label(state: BattleState, side: int, action: Action) -> str:
    own = state.sides[side]
    if isinstance(action, UseMove):
        return own.current.battler.moves[action.index].display_name
    return f"switching to {own.team[action.index].battler.pokemon.display_name}"


def _moves_first(attacker: Combatant, move: Move, foe: Combatant) -> bool:
    foe_priority = max(foe_move.priority for foe_move in foe.battler.moves)
    return (move.priority, attacker.speed) > (foe_priority, foe.speed)


def judge(choice: Choice) -> Mistake | None:
    """The clear-cut mistake in one voluntary choice, if any; forced replacements are not judged."""
    state, side, action = choice.state, choice.side, choice.action
    own = state.sides[side].current
    foe = state.sides[1 - side].current
    if own.fainted:
        return None
    turn = state.turn + 1
    moves = {
        option: own.battler.moves[option.index]
        for option in choice.options
        if isinstance(option, UseMove)
    }
    ranges = {
        option: damage_range(own.battler.pokemon, foe.battler.pokemon, move)
        for option, move in moves.items()
    }

    safe_kos = [
        option
        for option, move in moves.items()
        if ranges[option][0] >= foe.hp
        and move.accuracy in (None, 100)
        and _moves_first(own, move, foe)
    ]
    if safe_kos and action not in safe_kos:
        best = moves[safe_kos[0]]
        return Mistake(
            turn,
            side,
            "missed_ko",
            _label(state, side, action),
            best.display_name,
            f"{best.display_name} was a guaranteed KO on {foe.battler.pokemon.display_name} "
            "that could not miss and landed before it could move.",
        )

    if isinstance(action, UseMove) and ranges[action][1] == 0:
        damaging = [option for option in moves if ranges[option][1] > 0]
        if damaging:
            best_option = max(damaging, key=lambda option: ranges[option][1])
            return Mistake(
                turn,
                side,
                "no_effect",
                _label(state, side, action),
                moves[best_option].display_name,
                f"{moves[action].display_name} has no effect on "
                f"{foe.battler.pokemon.display_name}.",
            )

    if isinstance(action, Switch):
        incoming = state.sides[side].team[action.index]
        lethal = [
            move
            for move in foe.battler.moves
            if damage_range(foe.battler.pokemon, incoming.battler.pokemon, move)[0] >= incoming.hp
        ]
        if lethal:
            return Mistake(
                turn,
                side,
                "switched_into_ko",
                _label(state, side, action),
                "another option",
                f"{foe.battler.pokemon.display_name}'s {lethal[0].display_name} is a guaranteed "
                f"KO on the incoming {incoming.battler.pokemon.display_name}.",
            )
    return None


def find_mistakes(choices: Iterable[Choice]) -> tuple[Mistake, ...]:
    return tuple(mistake for choice in choices if (mistake := judge(choice)) is not None)
