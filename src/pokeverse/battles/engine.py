"""Turn-based singles battles between two teams of battlers, as pure state transitions."""

import random
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol

from pokeverse.battles.battler import Battler
from pokeverse.battles.damage import roll_damage
from pokeverse.battles.stats import battle_stats
from pokeverse.catalog.type_chart import effectiveness
from pokeverse.teams import MAX_TEAM_SIZE

MAX_TURNS = 100

EventKind = Literal["switch", "move", "no_effect", "miss", "damage", "faint", "win", "draw"]


class IllegalActionError(ValueError):
    """A player chose an action that is not legal in the current state."""


@dataclass(frozen=True, slots=True)
class UseMove:
    index: int


@dataclass(frozen=True, slots=True)
class Switch:
    index: int


type Action = UseMove | Switch


@dataclass(frozen=True, slots=True)
class Combatant:
    battler: Battler
    hp: int
    max_hp: int

    @classmethod
    def enter(cls, battler: Battler) -> Combatant:
        max_hp = battle_stats(battler.pokemon.stats).hp
        return cls(battler, max_hp, max_hp)

    @property
    def name(self) -> str:
        return self.battler.pokemon.name

    @property
    def speed(self) -> int:
        return battle_stats(self.battler.pokemon.stats).speed

    @property
    def fainted(self) -> bool:
        return self.hp == 0


@dataclass(frozen=True, slots=True)
class Side:
    team: tuple[Combatant, ...]
    active: int = 0

    @property
    def current(self) -> Combatant:
        return self.team[self.active]

    @property
    def defeated(self) -> bool:
        return all(member.fainted for member in self.team)

    def bench(self) -> tuple[int, ...]:
        return tuple(
            index
            for index, member in enumerate(self.team)
            if index != self.active and not member.fainted
        )

    def with_current(self, combatant: Combatant) -> Side:
        team = list(self.team)
        team[self.active] = combatant
        return replace(self, team=tuple(team))


@dataclass(frozen=True, slots=True)
class BattleState:
    sides: tuple[Side, Side]
    turn: int = 0

    @property
    def over(self) -> bool:
        return any(side.defeated for side in self.sides)

    @property
    def winner(self) -> int | None:
        if self.sides[1].defeated and not self.sides[0].defeated:
            return 0
        if self.sides[0].defeated and not self.sides[1].defeated:
            return 1
        return None

    def needs_replacement(self, side: int) -> bool:
        own = self.sides[side]
        return own.current.fainted and not own.defeated

    def with_side(self, index: int, side: Side) -> BattleState:
        sides = list(self.sides)
        sides[index] = side
        return replace(self, sides=(sides[0], sides[1]))


@dataclass(frozen=True, slots=True)
class BattleEvent:
    turn: int
    kind: EventKind
    side: int | None = None
    pokemon: str | None = None
    move: str | None = None
    damage: int | None = None
    hp: int | None = None
    critical: bool = False
    effectiveness: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "turn": self.turn,
            "kind": self.kind,
            "side": self.side,
            "pokemon": self.pokemon,
            "move": self.move,
            "damage": self.damage,
            "hp": self.hp,
            "critical": self.critical or None,
            "effectiveness": self.effectiveness,
        }
        return {key: value for key, value in data.items() if value is not None}

    def describe(self) -> str:
        pokemon = _display(self.pokemon)
        side = f"Side {self.side + 1}" if self.side is not None else ""
        match self.kind:
            case "switch":
                return f"{side} sends out {pokemon}."
            case "move":
                return f"{pokemon} uses {_display(self.move)}."
            case "no_effect":
                return f"It doesn't affect {pokemon}."
            case "miss":
                return f"{pokemon}'s attack missed."
            case "damage":
                text = f"{pokemon} takes {self.damage} damage ({self.hp} HP left)."
                if self.critical:
                    text += " A critical hit!"
                if self.effectiveness is not None and self.effectiveness > 1:
                    text += " It's super effective!"
                elif self.effectiveness is not None and self.effectiveness < 1:
                    text += " It's not very effective."
                return text
            case "faint":
                return f"{pokemon} fainted."
            case "win":
                return f"{side} wins."
            case "draw":
                return f"The battle ends in a draw after {self.turn} turns."


def _display(slug: str | None) -> str:
    return (slug or "").replace("-", " ").title()


class Player(Protocol):
    def choose(self, state: BattleState, side: int, options: tuple[Action, ...]) -> Action: ...


@dataclass(frozen=True, slots=True)
class BattleResult:
    state: BattleState
    events: tuple[BattleEvent, ...]

    @property
    def winner(self) -> int | None:
        return self.state.winner

    @property
    def turns(self) -> int:
        return self.state.turn


def start_battle(team_a: Sequence[Battler], team_b: Sequence[Battler]) -> BattleState:
    sides = []
    for team in (team_a, team_b):
        if not 1 <= len(team) <= MAX_TEAM_SIZE:
            raise ValueError(f"a battle team must have between 1 and {MAX_TEAM_SIZE} battlers")
        sides.append(Side(tuple(Combatant.enter(battler) for battler in team)))
    return BattleState((sides[0], sides[1]))


def legal_actions(state: BattleState, side: int) -> tuple[Action, ...]:
    """Moves plus switches to healthy bench members; only switches after a faint."""
    if state.over:
        return ()
    own = state.sides[side]
    switches = tuple(Switch(index) for index in own.bench())
    if own.current.fainted:
        return switches
    moves = tuple(UseMove(index) for index in range(len(own.current.battler.moves)))
    return moves + switches


def _check(state: BattleState, side: int, action: Action) -> None:
    if action not in legal_actions(state, side):
        raise IllegalActionError(f"side {side + 1} cannot choose {action}")


def _order(state: BattleState, actions: tuple[Action, Action], rng: random.Random) -> list[int]:
    keys = []
    for side, action in enumerate(actions):
        tiebreak = rng.random()
        if isinstance(action, Switch):
            keys.append((1, 0, 0, tiebreak, side))
        else:
            combatant = state.sides[side].current
            priority = combatant.battler.moves[action.index].priority
            keys.append((0, priority, combatant.speed, tiebreak, side))
    return [key[-1] for key in sorted(keys, reverse=True)]


def _switch(state: BattleState, side: int, index: int) -> tuple[BattleState, BattleEvent]:
    new_state = state.with_side(side, replace(state.sides[side], active=index))
    event = BattleEvent(new_state.turn, "switch", side, new_state.sides[side].current.name)
    return new_state, event


def _attack(
    state: BattleState, side: int, move_index: int, rng: random.Random
) -> tuple[BattleState, list[BattleEvent]]:
    attacker = state.sides[side].current
    target_side = 1 - side
    defender = state.sides[target_side].current
    move = attacker.battler.moves[move_index]
    events = [BattleEvent(state.turn, "move", side, attacker.name, move.name)]

    if effectiveness(move.type, defender.battler.pokemon.types) == 0:
        events.append(BattleEvent(state.turn, "no_effect", target_side, defender.name, move.name))
        return state, events
    if move.accuracy is not None and rng.randint(1, 100) > move.accuracy:
        events.append(BattleEvent(state.turn, "miss", side, attacker.name, move.name))
        return state, events

    hit = roll_damage(attacker.battler.pokemon, defender.battler.pokemon, move, rng)
    damage = min(hit.damage, defender.hp)
    hurt = replace(defender, hp=defender.hp - damage)
    state = state.with_side(target_side, state.sides[target_side].with_current(hurt))
    events.append(
        BattleEvent(
            state.turn,
            "damage",
            target_side,
            hurt.name,
            move.name,
            damage=damage,
            hp=hurt.hp,
            critical=hit.critical,
            effectiveness=hit.effectiveness,
        )
    )
    if hurt.fainted:
        events.append(BattleEvent(state.turn, "faint", target_side, hurt.name))
    return state, events


def _ending(state: BattleState) -> list[BattleEvent]:
    if state.winner is None:
        return []
    return [BattleEvent(state.turn, "win", state.winner)]


def play_turn(
    state: BattleState, actions: tuple[Action, Action], rng: random.Random
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    """Resolve one turn: switches first, then moves by priority, speed and a random tie-break."""
    if state.over:
        raise IllegalActionError("the battle is over")
    if state.needs_replacement(0) or state.needs_replacement(1):
        raise IllegalActionError("a fainted battler must be replaced first")
    for side, action in enumerate(actions):
        _check(state, side, action)

    state = replace(state, turn=state.turn + 1)
    events: list[BattleEvent] = []
    for side in _order(state, actions, rng):
        action = actions[side]
        if isinstance(action, Switch):
            state, event = _switch(state, side, action.index)
            events.append(event)
        elif not state.sides[side].current.fainted:
            state, new_events = _attack(state, side, action.index, rng)
            events.extend(new_events)
        if state.over:
            break
    events.extend(_ending(state))
    return state, tuple(events)


def replace_fainted(
    state: BattleState, side: int, action: Action
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    if not state.needs_replacement(side):
        raise IllegalActionError(f"side {side + 1} has no fainted battler to replace")
    _check(state, side, action)
    state, event = _switch(state, side, action.index)
    return state, (event,)


def run_battle(
    team_a: Sequence[Battler],
    team_b: Sequence[Battler],
    players: tuple[Player, Player],
    rng: random.Random,
    max_turns: int = MAX_TURNS,
) -> BattleResult:
    """Play until one side has no battlers left, or declare a draw after ``max_turns``."""
    state = start_battle(team_a, team_b)
    events = [BattleEvent(0, "switch", side, state.sides[side].current.name) for side in (0, 1)]
    while not state.over and state.turn < max_turns:
        actions = (
            players[0].choose(state, 0, legal_actions(state, 0)),
            players[1].choose(state, 1, legal_actions(state, 1)),
        )
        state, new_events = play_turn(state, actions, rng)
        events.extend(new_events)
        for side in (0, 1):
            if state.needs_replacement(side):
                choice = players[side].choose(state, side, legal_actions(state, side))
                state, new_events = replace_fainted(state, side, choice)
                events.extend(new_events)
    if not state.over:
        events.append(BattleEvent(state.turn, "draw"))
    return BattleResult(state, tuple(events))
