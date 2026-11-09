from typing import Any

from pokeverse.agents import BattleReviewAgent, BattleStrategyAgent
from pokeverse.agents.battle_review import BATTLE_REVIEW_SYSTEM_PROMPT, review_prompt
from pokeverse.battles import Battler, Mistake, legal_actions, start_battle
from pokeverse.catalog import BaseStats, DamageClass, Move, Pokemon, PokemonType
from pokeverse.llm import Completion

MISTAKES = (
    Mistake(3, 0, "no_effect", "Earthquake", "Dragon Claw", "Earthquake has no effect."),
    Mistake(5, 0, "missed_ko", "Outrage", "Volt Tackle", "Volt Tackle was a guaranteed KO."),
)


class FixedChat:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.calls: list[dict[str, Any]] = []

    def complete(self, prompt: str, **kwargs: Any) -> Completion:
        self.calls.append({"prompt": prompt, **kwargs})
        return Completion("", "fake-model", "end_turn", 200, 50, 5, (), self.data)


def lesson(text: str, *evidence: str) -> dict[str, Any]:
    return {"text": text, "evidence": list(evidence)}


def test_no_mistakes_means_no_lessons_and_no_model_call() -> None:
    chat = FixedChat({"lessons": []})

    review = BattleReviewAgent(chat).review(())

    assert review.lessons == ()
    assert review.guidance() == ""
    assert chat.calls == []


def test_prompt_lists_mistakes_with_ids_and_the_schema_restricts_evidence() -> None:
    chat = FixedChat({"lessons": [lesson("Check immunities.", "m-0")]})

    BattleReviewAgent(chat).review(MISTAKES)

    (call,) = chat.calls
    assert call["system"] == BATTLE_REVIEW_SYSTEM_PROMPT
    assert call["prompt"] == review_prompt(MISTAKES)
    assert "- m-1 [missed_ko]: Turn 5: chose Outrage instead of Volt Tackle;" in call["prompt"]
    items = call["output_schema"].schema["properties"]["lessons"]["items"]
    assert items["properties"]["evidence"]["items"]["enum"] == ["m-0", "m-1"]


def test_only_cited_lessons_are_kept_and_at_most_three() -> None:
    data = {
        "lessons": [
            lesson("Never use a move the foe is immune to.", "m-0", "m-0"),
            lesson("Uncited advice."),
            lesson("Take guaranteed knockouts.", "m-1"),
            lesson("", "m-0"),
            lesson("Third.", "m-0"),
            lesson("Fourth.", "m-1"),
        ]
    }

    review = BattleReviewAgent(FixedChat(data)).review(MISTAKES)

    assert [item.text for item in review.lessons] == [
        "Never use a move the foe is immune to.",
        "Take guaranteed knockouts.",
        "Third.",
    ]
    assert review.lessons[0].evidence == ("m-0",)
    assert review.guidance().splitlines() == [
        "Lessons from earlier battles (each based on mistakes the engine detected):",
        "- Never use a move the foe is immune to.",
        "- Take guaranteed knockouts.",
        "- Third.",
    ]


def test_strategy_agent_appends_lessons_to_every_prompt() -> None:
    T, D = PokemonType, DamageClass
    earthquake = Move(
        move_id=89,
        name="earthquake",
        type=T.GROUND,
        damage_class=D.PHYSICAL,
        power=100,
        accuracy=100,
        priority=0,
        pp=10,
    )
    claw = Move(
        move_id=337,
        name="dragon-claw",
        type=T.DRAGON,
        damage_class=D.PHYSICAL,
        power=80,
        accuracy=100,
        priority=0,
        pp=15,
    )
    species = Pokemon(
        pokedex_id=445,
        name="garchomp",
        types=(T.DRAGON, T.GROUND),
        stats=BaseStats(
            hp=108, attack=130, defense=95, special_attack=80, special_defense=85, speed=102
        ),
        learnset=frozenset({"earthquake", "dragon-claw"}),
    )
    garchomp = Battler(species, (earthquake, claw))

    class Recorder:
        prompts: list[str] = []

        def complete(self, prompt: str, **kwargs: Any) -> Completion:
            self.prompts.append(prompt)
            ids = kwargs["output_schema"].schema["properties"]["action"]["enum"]
            return Completion("", "m", "end_turn", 1, 1, 1, (), {"action": ids[0], "reason": "x"})

    chat = Recorder()
    agent = BattleStrategyAgent(chat, lessons="Lessons from earlier battles:\n- Check immunity.")
    state = start_battle([garchomp], [garchomp])

    agent.choose(state, 0, legal_actions(state, 0))

    assert chat.prompts[0].endswith("\n\nLessons from earlier battles:\n- Check immunity.")
