from typing import Any

import pytest

from pokeverse.battles import Battler
from pokeverse.catalog import BaseStats, DamageClass, Move, Pokemon, PokemonType
from pokeverse.evals.battles import feedback_experiment, run_system, wilson_interval
from pokeverse.llm import Completion

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
LEARNSET = frozenset({"earthquake", "dragon-claw", "flamethrower"})

GARCHOMP = Battler(
    Pokemon(
        pokedex_id=445,
        name="garchomp",
        types=(T.DRAGON, T.GROUND),
        stats=BaseStats(
            hp=108, attack=130, defense=95, special_attack=80, special_defense=85, speed=102
        ),
        learnset=LEARNSET,
    ),
    (EARTHQUAKE, DRAGON_CLAW),
)
CHARIZARD = Battler(
    Pokemon(
        pokedex_id=6,
        name="charizard",
        types=(T.FIRE, T.FLYING),
        stats=BaseStats(
            hp=78, attack=84, defense=78, special_attack=109, special_defense=85, speed=100
        ),
        learnset=LEARNSET,
    ),
    (FLAMETHROWER,),
)
TEAM = [GARCHOMP]
OPPONENT = [CHARIZARD]
CLAW_ONLY = Battler(GARCHOMP.pokemon, (DRAGON_CLAW,))


class ScriptedChat:
    """Always picks the first option (Earthquake into an immune Charizard)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def complete(self, prompt: str, **kwargs: Any) -> Completion:
        self.calls.append({"prompt": prompt, **kwargs})
        schema = kwargs["output_schema"]
        properties = schema.schema["properties"]
        if schema.name == "opponent_analysis":
            foes = properties["threats"]["items"]["properties"]["foe"]["enum"]
            data: dict[str, Any] = {
                "threats": [{"foe": foe, "danger": "high", "reason": "x"} for foe in foes],
                "counters": [],
                "plan": "x",
            }
        elif schema.name == "battle_review":
            ids = properties["lessons"]["items"]["properties"]["evidence"]["items"]["enum"]
            data = {"lessons": [{"text": "Check immunities first.", "evidence": ids[:2]}]}
        else:
            data = {"action": properties["action"]["enum"][0], "reason": "x"}
        return Completion("", "fake-model", "end_turn", 90, 10, 5, (), data)


def test_wilson_interval_is_wide_for_small_samples() -> None:
    low, high = wilson_interval(0, 5)
    assert low == 0.0
    assert high == pytest.approx(0.434, abs=0.001)
    low, high = wilson_interval(5, 10)
    assert (low, high) == (pytest.approx(0.237, abs=0.001), pytest.approx(0.763, abs=0.001))
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_greedy_system_needs_no_llm_and_is_reproducible() -> None:
    first = run_system("greedy", TEAM, OPPONENT, range(3))
    second = run_system("greedy", TEAM, OPPONENT, range(3))

    assert first == second
    assert first.battles == 3
    assert first.total_tokens == 0
    assert first.mistakes == ()


def test_unknown_systems_and_missing_llm_are_rejected() -> None:
    with pytest.raises(ValueError, match="unknown system"):
        run_system("genius", TEAM, OPPONENT, range(1))
    with pytest.raises(ValueError, match="needs an LLM"):
        run_system("agent", TEAM, OPPONENT, range(1))


def test_agent_system_counts_tokens_and_engine_detected_mistakes() -> None:
    progress: list[str] = []

    report = run_system("agent", TEAM, OPPONENT, range(2), ScriptedChat(), progress=progress.append)

    assert report.wins == 0
    assert report.mistakes and {m.kind for m in report.mistakes} == {"no_effect"}
    assert report.total_tokens == 100 * sum(len(r.mistakes) for r in report.records)
    assert report.to_dict()["win_rate_95"][0] == 0.0
    assert progress[0].startswith("agent seed 0: lost in ")


def test_agent_with_analysis_analyses_once_per_run() -> None:
    chat = ScriptedChat()

    report = run_system("agent+analysis", TEAM, OPPONENT, range(2), chat)

    analyses = [c for c in chat.calls if c["output_schema"].name == "opponent_analysis"]
    assert len(analyses) == 1
    assert report.setup_tokens == 100


def test_feedback_learns_on_training_seeds_and_tests_on_new_ones() -> None:
    chat = ScriptedChat()

    report = feedback_experiment(TEAM, OPPONENT, chat, range(0, 2), range(2, 4))

    assert [record.seed for record in report.training.records] == [0, 1]
    assert [record.seed for record in report.baseline.records] == [2, 3]
    assert report.review.lessons[0].text == "Check immunities first."
    assert report.with_lessons is not None
    lesson_prompts = [
        call["prompt"]
        for call in chat.calls
        if call["output_schema"].name == "battle_decision" and "Lessons from" in call["prompt"]
    ]
    assert len(lesson_prompts) == report.with_lessons.total_tokens // 100
    assert report.to_dict()["review_tokens"] == 100


def test_feedback_rejects_overlapping_seeds() -> None:
    with pytest.raises(ValueError, match="overlap"):
        feedback_experiment(TEAM, OPPONENT, ScriptedChat(), range(0, 3), range(2, 4))


def test_feedback_without_mistakes_skips_review_and_test_battles() -> None:
    chat = ScriptedChat()

    report = feedback_experiment([CLAW_ONLY], OPPONENT, chat, range(0, 1), range(1, 3))

    assert report.training.mistakes == ()
    assert (report.baseline, report.with_lessons) == (None, None)
    assert report.review_tokens == 0
    assert chat.calls == []
