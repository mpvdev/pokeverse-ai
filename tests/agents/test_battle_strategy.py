import random
from collections.abc import Callable
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
DRAGON_CLAW = Move(
    move_id=337,
    name="dragon-claw",
    type=T.DRAGON,
    damage_class=D.PHYSICAL,
    power=80,
    accuracy=100,
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
QUICK_ATTACK = Move(
    move_id=98,
    name="quick-attack",
    type=T.NORMAL,
    damage_class=D.PHYSICAL,
    power=40,
    accuracy=100,
    priority=1,
    pp=30,
)
FLAMETHROWER = Move(
    move_id=53,
    name="flamethrower",
    type=T.FIRE,
    damage_class=D.SPECIAL,
    power=90,
    accuracy=100,
    priority=0,
    pp=15,
)

LEARNSET = frozenset(
    move.name for move in (EARTHQUAKE, DRAGON_CLAW, THUNDERBOLT, QUICK_ATTACK, FLAMETHROWER)
)
GARCHOMP = Battler(
    pokemon=Pokemon(
        pokedex_id=445,
        name="garchomp",
        types=(T.DRAGON, T.GROUND),
        stats=BaseStats(
            hp=108, attack=130, defense=95, special_attack=80, special_defense=85, speed=102
        ),
        learnset=LEARNSET,
    ),
    moves=(EARTHQUAKE, DRAGON_CLAW),
)
PIKACHU = Battler(
    pokemon=Pokemon(
        pokedex_id=25,
        name="pikachu",
        types=(T.ELECTRIC,),
        stats=BaseStats(
            hp=35, attack=55, defense=40, special_attack=50, special_defense=50, speed=90
        ),
        learnset=LEARNSET,
    ),
    moves=(THUNDERBOLT, QUICK_ATTACK),
)
CHARIZARD = Battler(
    pokemon=Pokemon(
        pokedex_id=6,
        name="charizard",
        types=(T.FIRE, T.FLYING),
        stats=BaseStats(
            hp=78, attack=84, defense=78, special_attack=109, special_defense=85, speed=100
        ),
        learnset=LEARNSET,
    ),
    moves=(FLAMETHROWER,),
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
    return state.with_side(side, own.with_current(own.current.model_copy(update={"hp": 0})))


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

    assert action == UseMove(index=1)
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

    assert agent.choose(state, 0, legal_actions(state, 0)) == UseMove(index=0)
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

    assert agent.choose(state, 1, legal_actions(state, 1)) == Switch(index=2)
    assert agent.decisions[0].turn == state.turn
