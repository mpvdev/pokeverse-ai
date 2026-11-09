import random
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest

from pokeverse.agents import BattleStrategyAgent
from pokeverse.agents.battle_strategy import (
    BATTLE_STRATEGY_SYSTEM_PROMPT,
    describe_situation,
    option_id,
)
from pokeverse.battles import (
    Battler,
    BattleState,
    GreedyPlayer,
    Switch,
    UseMove,
    legal_actions,
    run_battle,
    start_battle,
)
from pokeverse.catalog import BaseStats, DamageClass, Move, Pokemon, PokemonType
from pokeverse.llm import Completion, LlmRequestError, LlmUnavailableError

T = PokemonType
D = DamageClass

EARTHQUAKE = Move(89, "earthquake", T.GROUND, D.PHYSICAL, 100, 100, 0, 10)
DRAGON_CLAW = Move(337, "dragon-claw", T.DRAGON, D.PHYSICAL, 80, 100, 0, 15)
THUNDERBOLT = Move(85, "thunderbolt", T.ELECTRIC, D.SPECIAL, 90, 100, 0, 15)
QUICK_ATTACK = Move(98, "quick-attack", T.NORMAL, D.PHYSICAL, 40, 100, 1, 30)
FLAMETHROWER = Move(53, "flamethrower", T.FIRE, D.SPECIAL, 90, 100, 0, 15)

LEARNSET = frozenset(
    move.name for move in (EARTHQUAKE, DRAGON_CLAW, THUNDERBOLT, QUICK_ATTACK, FLAMETHROWER)
)
GARCHOMP = Battler(
    Pokemon(445, "garchomp", (T.DRAGON, T.GROUND), BaseStats(108, 130, 95, 80, 85, 102), LEARNSET),
    (EARTHQUAKE, DRAGON_CLAW),
)
PIKACHU = Battler(
    Pokemon(25, "pikachu", (T.ELECTRIC,), BaseStats(35, 55, 40, 50, 50, 90), LEARNSET),
    (THUNDERBOLT, QUICK_ATTACK),
)
CHARIZARD = Battler(
    Pokemon(6, "charizard", (T.FIRE, T.FLYING), BaseStats(78, 84, 78, 109, 85, 100), LEARNSET),
    (FLAMETHROWER,),
)


class ScriptedChat:
    """Answers each decision with ``pick(option_ids)``, or raises ``error``."""

    def __init__(
        self,
        pick: Callable[[list[str]], Any] = lambda ids: ids[0],
        error: Exception | None = None,
    ) -> None:
        self.pick = pick
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def complete(self, prompt: str, **kwargs: Any) -> Completion:
        self.calls.append({"prompt": prompt, **kwargs})
        if self.error is not None:
            raise self.error
        ids = kwargs["output_schema"].schema["properties"]["action"]["enum"]
        data = {"action": self.pick(ids), "reason": "Scripted."}
        return Completion("", "fake-model", "end_turn", 100, 20, 5, (), data)


def test_option_ids_name_the_move_or_the_incoming_pokemon() -> None:
    state = start_battle([GARCHOMP, PIKACHU], [CHARIZARD])

    ids = [option_id(state, 0, action) for action in legal_actions(state, 0)]

    assert ids == ["move-0:earthquake", "move-1:dragon-claw", "switch-1:pikachu"]


def test_situation_lists_code_computed_facts_for_every_option() -> None:
    state = start_battle([GARCHOMP, PIKACHU], [CHARIZARD])

    prompt = describe_situation(state, 0, legal_actions(state, 0))

    assert "Your active: Garchomp (Dragon/Ground) 183/183 HP, speed 122." in prompt
    assert "Foe active: Charizard (Fire/Flying) 153/153 HP, speed 120." in prompt
    assert "You are faster" in prompt
    assert "- move-0:earthquake: Earthquake (Ground, physical, power 100" in prompt
    assert "no effect (immune)" in prompt
    assert "- switch-1:pikachu: switch to Pikachu" in prompt
    assert "It takes the foe's attack this turn." in prompt
    assert "Foe bench: none." in prompt


def test_situation_flags_knockouts() -> None:
    state = start_battle([GARCHOMP], [PIKACHU])

    prompt = describe_situation(state, 0, legal_actions(state, 0))

    assert "move-0:earthquake" in prompt
    assert "guaranteed KO" in prompt


def faint_active(state: BattleState, side: int) -> BattleState:
    own = state.sides[side]
    return state.with_side(side, own.with_current(replace(own.current, hp=0)))


def test_replacement_situation_says_the_newcomer_is_not_attacked() -> None:
    state = faint_active(start_battle([PIKACHU, GARCHOMP, CHARIZARD], [GARCHOMP]), 0)

    prompt = describe_situation(state, 0, legal_actions(state, 0))

    assert "Your Pikachu fainted. Choose a replacement" in prompt
    assert "It takes the foe's attack this turn." not in prompt
    assert "switch-1:garchomp" in prompt and "switch-2:charizard" in prompt


def test_agent_uses_the_models_choice_with_a_per_turn_enum_schema() -> None:
    chat = ScriptedChat(pick=lambda ids: "move-1:dragon-claw")
    agent = BattleStrategyAgent(chat)
    state = start_battle([GARCHOMP, PIKACHU], [CHARIZARD])

    action = agent.choose(state, 0, legal_actions(state, 0))

    assert action == UseMove(1)
    (call,) = chat.calls
    assert call["system"] == BATTLE_STRATEGY_SYSTEM_PROMPT
    schema = call["output_schema"].schema
    assert schema["properties"]["action"]["enum"] == [
        "move-0:earthquake",
        "move-1:dragon-claw",
        "switch-1:pikachu",
    ]
    assert schema["additionalProperties"] is False
    (decision,) = agent.decisions
    assert (decision.turn, decision.action, decision.fallback, decision.tokens) == (
        1,
        "move-1:dragon-claw",
        False,
        120,
    )


def test_a_single_legal_option_needs_no_model_call() -> None:
    chat = ScriptedChat()
    agent = BattleStrategyAgent(chat)
    state = start_battle([CHARIZARD], [GARCHOMP])

    assert agent.choose(state, 0, legal_actions(state, 0)) == UseMove(0)
    assert chat.calls == []
    assert agent.decisions[0].reason == "Only legal option."


@pytest.mark.parametrize(
    "chat",
    [
        ScriptedChat(pick=lambda ids: "move-9:hyper-beam"),
        ScriptedChat(error=LlmRequestError("refused")),
    ],
)
def test_bad_replies_fall_back_to_greedy_and_are_recorded(chat: ScriptedChat) -> None:
    agent = BattleStrategyAgent(chat)
    state = start_battle([GARCHOMP, PIKACHU], [CHARIZARD])
    options = legal_actions(state, 0)

    action = agent.choose(state, 0, options)

    assert action == GreedyPlayer().choose(state, 0, options)
    assert agent.fallbacks == 1
    assert agent.decisions[0].fallback


def test_outages_abort_instead_of_falling_back() -> None:
    agent = BattleStrategyAgent(ScriptedChat(error=LlmUnavailableError("down")))
    state = start_battle([GARCHOMP, PIKACHU], [CHARIZARD])

    with pytest.raises(LlmUnavailableError):
        agent.choose(state, 0, legal_actions(state, 0))


def test_agent_plays_a_whole_battle_and_records_replacements() -> None:
    chat = ScriptedChat(pick=lambda ids: ids[-1])
    agent = BattleStrategyAgent(chat)

    result = run_battle(
        [PIKACHU, GARCHOMP], [GARCHOMP, CHARIZARD], (agent, GreedyPlayer()), random.Random(2)
    )

    assert result.winner is not None
    assert agent.total_tokens == 120 * len(chat.calls)
    assert all(decision.side == 0 for decision in agent.decisions)


def test_forced_replacement_decision_is_recorded_on_the_current_turn() -> None:
    agent = BattleStrategyAgent(ScriptedChat(pick=lambda ids: ids[-1]))
    state = faint_active(start_battle([GARCHOMP], [PIKACHU, CHARIZARD, GARCHOMP]), 1)

    assert agent.choose(state, 1, legal_actions(state, 1)) == Switch(2)
    assert agent.decisions[0].turn == state.turn
