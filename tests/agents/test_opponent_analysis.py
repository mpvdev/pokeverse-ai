from typing import Any

import pytest

from pokeverse.agents import BattleStrategyAgent, OpponentAnalysis, OpponentAnalysisAgent
from pokeverse.agents.opponent_analysis import (
    OPPONENT_ANALYSIS_SYSTEM_PROMPT,
    matchup_table,
)
from pokeverse.battles import Battler, BattleState, legal_actions, start_battle
from pokeverse.catalog import BaseStats, DamageClass, Move, Pokemon, PokemonType
from pokeverse.llm import Completion, LlmRequestError

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
LEARNSET = frozenset({"earthquake", "thunderbolt", "flamethrower"})

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
    moves=(EARTHQUAKE,),
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
    moves=(THUNDERBOLT,),
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

OWN = [GARCHOMP, PIKACHU]
FOE = [PIKACHU, CHARIZARD]


class FixedChat:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.calls: list[dict[str, Any]] = []

    def complete(self, prompt: str, **kwargs: Any) -> Completion:
        self.calls.append({"prompt": prompt, **kwargs})
        return Completion("", "fake-model", "end_turn", 300, 100, 5, (), self.data)


def reply(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "threats": [
            {"foe": "foe-1:charizard", "danger": "high", "reason": "Beats Garchomp."},
            {"foe": "foe-0:pikachu", "danger": "low", "reason": "Walled by Garchomp."},
        ],
        "counters": [
            {"threat": "foe-0:pikachu", "answer": "own-0:garchomp", "reason": "Immune."},
            {"threat": "foe-1:charizard", "answer": "own-0:garchomp", "reason": "Wrong."},
            {"threat": "foe-1:charizard", "answer": "own-1:pikachu", "reason": "Super effective."},
        ],
        "plan": "Lead Garchomp; keep Pikachu for Charizard.",
    }
    return data | overrides


def test_the_prompt_is_the_code_computed_matchup_table() -> None:
    table = matchup_table(OWN, FOE)

    assert table.splitlines()[0] == "Matchup table (our Pokémon first in each line):"
    assert "- own-0:garchomp vs foe-1:charizard: Garchomp vs Charizard:" in table
    assert "one-on-one: Charizard wins." in table
    assert len(table.splitlines()) == 1 + len(OWN) * len(FOE)


def test_schema_restricts_names_to_team_slots() -> None:
    chat = FixedChat(reply())

    OpponentAnalysisAgent(chat).analyze(OWN, FOE)

    (call,) = chat.calls
    assert call["system"] == OPPONENT_ANALYSIS_SYSTEM_PROMPT
    properties = call["output_schema"].schema["properties"]
    assert properties["threats"]["items"]["properties"]["foe"]["enum"] == [
        "foe-0:pikachu",
        "foe-1:charizard",
    ]
    assert properties["counters"]["items"]["properties"]["answer"]["enum"] == [
        "own-0:garchomp",
        "own-1:pikachu",
    ]


def test_code_verifies_each_counter_against_the_matchups() -> None:
    analysis = OpponentAnalysisAgent(FixedChat(reply())).analyze(OWN, FOE)

    assert [counter.verified for counter in analysis.counters] == [True, False, False]


def test_a_super_effective_counter_can_still_lose_the_one_on_one() -> None:
    table = matchup_table([PIKACHU], [CHARIZARD])

    assert "Pikachu's Thunderbolt 44%-55%, KO in 3 hits" in table
    assert "Charizard's Flamethrower" in table and "KO in 2 hits" in table
    assert "one-on-one: Charizard wins." in table


def test_briefing_hands_over_ranking_and_verified_counters_only() -> None:
    briefing = OpponentAnalysisAgent(FixedChat(reply())).analyze(OWN, FOE).briefing()

    assert "- Threats: Charizard high; Pikachu low." in briefing
    assert "- Keep Garchomp for Pikachu: it wins that one-on-one." in briefing
    assert "for Charizard" not in briefing
    assert "Lead Garchomp" not in briefing


@pytest.mark.parametrize(
    "threats",
    [
        [{"foe": "foe-1:charizard", "danger": "high", "reason": "x"}],
        [
            {"foe": "foe-1:charizard", "danger": "high", "reason": "x"},
            {"foe": "foe-1:charizard", "danger": "low", "reason": "x"},
        ],
    ],
)
def test_every_foe_must_be_ranked_exactly_once(threats: list[dict[str, str]]) -> None:
    with pytest.raises(LlmRequestError, match="exactly once") as error:
        OpponentAnalysisAgent(FixedChat(reply(threats=threats))).analyze(OWN, FOE)
    assert error.value.completion is not None


def faint(state: BattleState, side: int, slot: int) -> BattleState:
    own = state.sides[side]
    team = list(own.team)
    team[slot] = team[slot].model_copy(update={"hp": 0})
    return state.with_side(side, own.model_copy(update={"team": tuple(team)}))


def analysis() -> OpponentAnalysis:
    data = reply(
        counters=[
            {"threat": "foe-0:pikachu", "answer": "own-0:garchomp", "reason": "Immune."},
            {"threat": "foe-0:pikachu", "answer": "own-0:garchomp", "reason": "Again."},
        ]
    )
    return OpponentAnalysisAgent(FixedChat(data)).analyze(OWN, FOE)


def test_briefing_drops_knocked_out_threats_and_counters() -> None:
    state = start_battle(OWN, FOE)

    assert "Charizard high" in analysis().briefing(state, 0)
    assert "Keep Garchomp for Pikachu" in analysis().briefing(state, 0)

    without_foe = analysis().briefing(faint(state, 1, 0), 0)
    assert "- Threats: Charizard high." in without_foe
    assert "Keep Garchomp for Pikachu" not in without_foe

    without_answer = analysis().briefing(faint(state, 0, 0), 0)
    assert "Pikachu low" in without_answer
    assert "Keep Garchomp" not in without_answer

    assert analysis().briefing(faint(faint(state, 1, 0), 1, 1), 0) == ""


def test_strategy_agent_appends_the_current_briefing_to_every_prompt() -> None:
    class Recorder:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def complete(self, prompt: str, **kwargs: Any) -> Completion:
            self.prompts.append(prompt)
            ids = kwargs["output_schema"].schema["properties"]["action"]["enum"]
            data = {"action": ids[0], "reason": "x"}
            return Completion("", "fake-model", "end_turn", 1, 1, 1, (), data)

    chat = Recorder()
    agent = BattleStrategyAgent(chat, analysis=analysis())
    state = start_battle(OWN, FOE)

    agent.choose(state, 0, legal_actions(state, 0))
    agent.choose(faint(state, 1, 1), 0, legal_actions(state, 0))

    assert chat.prompts[0].endswith(analysis().briefing(state, 0))
    assert "Charizard" not in chat.prompts[1].split("Pre-battle analysis")[1]
