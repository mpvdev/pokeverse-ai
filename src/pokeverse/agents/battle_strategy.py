"""The Battle Strategy Agent: an LLM chooses battle actions from code-computed facts."""

from dataclasses import dataclass
from typing import Any

from pokeverse.agents.opponent_analysis import OpponentAnalysis
from pokeverse.agents.research import ChatModel
from pokeverse.battles import (
    Action,
    BattleState,
    Combatant,
    GreedyPlayer,
    UseMove,
    damage_range,
    expected_damage,
)
from pokeverse.catalog import Move
from pokeverse.llm import Completion, LlmRequestError, OutputSchema

STRATEGY_MAX_TOKENS = 1500

BATTLE_STRATEGY_SYSTEM_PROMPT = (
    "You are the PokéVerse Battle Strategy Agent, playing a simplified singles Pokémon battle. "
    "Each turn you get the situation and a list of options with exact facts computed by the "
    "game engine: damage ranges, knock-out chances and threats. Rely on these facts; never "
    "work out damage or type effectiveness yourself. Rules: switches happen before moves, so "
    "a Pokémon you switch in takes the foe's attack this turn; otherwise higher priority, "
    "then higher speed, moves first; there are no abilities, items, status conditions, "
    "weather or stat changes, and moves never run out. Damage ranges exclude critical hits "
    "(1 in 24). Think beyond this turn: knock out a foe before it can hit back, avoid "
    "leaving a Pokémon in to be knocked out for nothing, switch to a Pokémon that takes "
    "little damage when that wins the exchange, and keep healthy Pokémon for later threats. "
    "Choose exactly one option id and give a one-sentence reason."
)


@dataclass(frozen=True, slots=True)
class BattleDecision:
    turn: int
    side: int
    action: str
    reason: str
    fallback: bool
    tokens: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "side": self.side,
            "action": self.action,
            "reason": self.reason,
            "fallback": self.fallback,
            "tokens": self.tokens,
        }


def option_id(state: BattleState, side: int, action: Action) -> str:
    own = state.sides[side]
    if isinstance(action, UseMove):
        return f"move-{action.index}:{own.current.battler.moves[action.index].name}"
    return f"switch-{action.index}:{own.team[action.index].name}"


def _profile(combatant: Combatant) -> str:
    pokemon = combatant.battler.pokemon
    types = "/".join(t.value.title() for t in pokemon.types)
    return (
        f"{pokemon.display_name} ({types}) {combatant.hp}/{combatant.max_hp} HP, "
        f"speed {combatant.speed}"
    )


def _move_facts(move: Move) -> str:
    accuracy = f"{move.accuracy}%" if move.accuracy is not None else "never misses"
    return (
        f"{move.display_name} ({move.type.value.title()}, {move.damage_class.value}, "
        f"power {move.power}, accuracy {accuracy}, priority {move.priority:+d})"
    )


def _hit(attacker: Combatant, defender: Combatant, move: Move) -> str:
    low, high = damage_range(attacker.battler.pokemon, defender.battler.pokemon, move)
    if high == 0:
        return "no effect (immune)"
    text = (
        f"{low}-{high} damage ({low / defender.hp:.0%}-{high / defender.hp:.0%} of its "
        f"remaining {defender.hp} HP)"
    )
    if low >= defender.hp:
        text += ", guaranteed KO"
    elif high >= defender.hp:
        text += ", possible KO"
    return text


def _best_move(attacker: Combatant, defender: Combatant) -> Move:
    return max(
        attacker.battler.moves,
        key=lambda move: expected_damage(attacker.battler.pokemon, defender.battler.pokemon, move),
    )


def _order(own: Combatant, foe: Combatant) -> str:
    if own.speed > foe.speed:
        return "You are faster: at equal priority you move first."
    if own.speed < foe.speed:
        return "The foe is faster: at equal priority it moves first."
    return "Speed tie: at equal priority the order is random."


def describe_situation(state: BattleState, side: int, options: tuple[Action, ...]) -> str:
    """The prompt for one decision: situation, threats and every legal option with facts."""
    own_side = state.sides[side]
    foe_side = state.sides[1 - side]
    own = own_side.current
    foe = foe_side.current
    replacing = own.fainted

    lines = [f"Turn {state.turn + 1}. You control side {side + 1}."]
    if replacing:
        lines.append(
            f"Your {own.battler.pokemon.display_name} fainted. Choose a replacement; it comes "
            "in now without being attacked."
        )
    else:
        lines.append(f"Your active: {_profile(own)}.")
    lines.append(f"Foe active: {_profile(foe)}.")
    if not replacing:
        lines.append(_order(own, foe))
        lines.append(f"Foe's moves against your {own.battler.pokemon.display_name}:")
        lines.extend(f"- {_move_facts(move)}: {_hit(foe, own, move)}" for move in foe.battler.moves)

    bench = [_profile(own_side.team[i]) for i in own_side.bench()]
    lines.append(f"Your bench: {'; '.join(bench) if bench else 'none'}.")
    foe_bench = [_profile(foe_side.team[i]) for i in foe_side.bench()]
    lines.append(f"Foe bench: {'; '.join(foe_bench) if foe_bench else 'none'}.")

    lines.append("Options:")
    for action in options:
        identifier = option_id(state, side, action)
        if isinstance(action, UseMove):
            move = own.battler.moves[action.index]
            lines.append(f"- {identifier}: {_move_facts(move)}: {_hit(own, foe, move)}")
            continue
        incoming = own_side.team[action.index]
        threat = _best_move(foe, incoming)
        answer = _best_move(incoming, foe)
        when = "" if replacing else "It takes the foe's attack this turn. "
        lines.append(
            f"- {identifier}: switch to {_profile(incoming)}. {when}"
            f"Foe's best move against it: {threat.display_name}, {_hit(foe, incoming, threat)}. "
            f"Its best move against the foe: {answer.display_name}, "
            f"{_hit(incoming, foe, answer)}."
        )
    return "\n".join(lines)


def decision_schema(option_ids: list[str]) -> OutputSchema:
    return OutputSchema(
        name="battle_decision",
        schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": option_ids},
                "reason": {
                    "type": "string",
                    "description": "One sentence explaining the choice.",
                },
            },
            "required": ["action", "reason"],
            "additionalProperties": False,
        },
    )


class BattleStrategyAgent:
    """A battle ``Player`` backed by an LLM; falls back to greedy play on a bad reply."""

    name = "agent"

    def __init__(
        self,
        chat: ChatModel,
        *,
        analysis: OpponentAnalysis | None = None,
        lessons: str = "",
        temperature: float | None = None,
        max_tokens: int = STRATEGY_MAX_TOKENS,
    ) -> None:
        self._chat = chat
        self._analysis = analysis
        self._lessons = lessons
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._fallback = GreedyPlayer()
        self.decisions: list[BattleDecision] = []
        self.completions: list[Completion] = []

    @property
    def total_tokens(self) -> int:
        return sum(decision.tokens for decision in self.decisions)

    @property
    def fallbacks(self) -> int:
        return sum(decision.fallback for decision in self.decisions)

    def choose(self, state: BattleState, side: int, options: tuple[Action, ...]) -> Action:
        turn = state.turn if state.sides[side].current.fainted else state.turn + 1
        by_id = {option_id(state, side, action): action for action in options}
        if len(options) == 1:
            self._record(turn, side, next(iter(by_id)), "Only legal option.", False, 0)
            return options[0]

        try:
            prompt = describe_situation(state, side, options)
            briefing = self._analysis.briefing(state, side) if self._analysis else ""
            for extra in (briefing, self._lessons):
                if extra:
                    prompt = f"{prompt}\n\n{extra}"
            completion = self._chat.complete(
                prompt,
                system=BATTLE_STRATEGY_SYSTEM_PROMPT,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                output_schema=decision_schema(list(by_id)),
            )
            data = completion.data or {}
            chosen, reason = data.get("action"), data.get("reason")
            if chosen not in by_id or not isinstance(reason, str):
                raise LlmRequestError(f"Invalid battle decision: {data}", completion=completion)
        except LlmRequestError as error:
            action = self._fallback.choose(state, side, options)
            tokens = error.completion.total_tokens if error.completion else 0
            if error.completion:
                self.completions.append(error.completion)
            self._record(turn, side, option_id(state, side, action), str(error), True, tokens)
            return action

        self.completions.append(completion)
        self._record(turn, side, chosen, reason, False, completion.total_tokens)
        return by_id[chosen]

    def _record(
        self, turn: int, side: int, action: str, reason: str, fallback: bool, tokens: int
    ) -> None:
        self.decisions.append(BattleDecision(turn, side, action, reason, fallback, tokens))
