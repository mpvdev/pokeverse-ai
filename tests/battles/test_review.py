from dataclasses import replace

from pokeverse.battles import (
    Action,
    Battler,
    BattleState,
    Choice,
    GreedyPlayer,
    RecordingPlayer,
    Switch,
    UseMove,
    find_mistakes,
    judge,
    legal_actions,
    start_battle,
)
from pokeverse.catalog import BaseStats, DamageClass, Move, Pokemon, PokemonType

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
GARCHOMP_SPECIES = Pokemon(
    445, "garchomp", (T.DRAGON, T.GROUND), BaseStats(108, 130, 95, 80, 85, 102), LEARNSET
)
PIKACHU_SPECIES = Pokemon(25, "pikachu", (T.ELECTRIC,), BaseStats(35, 55, 40, 50, 50, 90), LEARNSET)
CHARIZARD_SPECIES = Pokemon(
    6, "charizard", (T.FIRE, T.FLYING), BaseStats(78, 84, 78, 109, 85, 100), LEARNSET
)

GARCHOMP = Battler(GARCHOMP_SPECIES, (EARTHQUAKE, DRAGON_CLAW))
EARTHQUAKE_ONLY = Battler(GARCHOMP_SPECIES, (EARTHQUAKE,))
SLOW_PIKACHU = Battler(PIKACHU_SPECIES, (THUNDERBOLT,))
QUICK_PIKACHU = Battler(PIKACHU_SPECIES, (THUNDERBOLT, QUICK_ATTACK))
CHARIZARD = Battler(CHARIZARD_SPECIES, (FLAMETHROWER,))


def choice(state: BattleState, action: Action, side: int = 0) -> Choice:
    return Choice(state, side, legal_actions(state, side), action)


def test_missing_a_safe_knockout_is_a_mistake() -> None:
    state = start_battle([GARCHOMP, CHARIZARD], [SLOW_PIKACHU])

    mistake = judge(choice(state, Switch(1)))

    assert mistake is not None
    assert (mistake.kind, mistake.turn, mistake.chosen, mistake.better) == (
        "missed_ko",
        1,
        "switching to Charizard",
        "Earthquake",
    )
    assert judge(choice(state, UseMove(0))) is None


def test_a_knockout_the_foe_can_outprioritize_is_not_safe() -> None:
    state = start_battle([GARCHOMP, CHARIZARD], [QUICK_PIKACHU])

    assert judge(choice(state, Switch(1))) is None


def test_a_knockout_that_can_miss_is_not_safe() -> None:
    shaky = replace(EARTHQUAKE, accuracy=70)
    species = replace(GARCHOMP_SPECIES)
    state = start_battle([Battler(species, (shaky, DRAGON_CLAW)), CHARIZARD], [SLOW_PIKACHU])

    assert judge(choice(state, Switch(1))) is not None
    assert judge(choice(state, Switch(1))).better == "Dragon Claw"

    claw_misses = replace(DRAGON_CLAW, accuracy=90)
    state = start_battle([Battler(species, (shaky, claw_misses)), CHARIZARD], [SLOW_PIKACHU])
    assert judge(choice(state, Switch(1))) is None


def test_using_a_move_with_no_effect_is_a_mistake() -> None:
    state = start_battle([GARCHOMP], [CHARIZARD])

    mistake = judge(choice(state, UseMove(0)))

    assert mistake is not None
    assert (mistake.kind, mistake.better) == ("no_effect", "Dragon Claw")
    assert "Earthquake has no effect on Charizard." in mistake.describe()


def test_no_effect_is_not_a_mistake_without_a_damaging_alternative() -> None:
    state = start_battle([EARTHQUAKE_ONLY], [CHARIZARD])

    assert judge(choice(state, UseMove(0))) is None


def test_switching_into_a_guaranteed_knockout_is_a_mistake() -> None:
    state = start_battle([GARCHOMP, SLOW_PIKACHU], [EARTHQUAKE_ONLY])

    mistake = judge(choice(state, Switch(1)))

    assert mistake is not None
    assert mistake.kind == "switched_into_ko"
    assert "Garchomp's Earthquake is a guaranteed KO on the incoming Pikachu." in mistake.detail


def test_forced_replacements_are_not_judged() -> None:
    state = start_battle([SLOW_PIKACHU, GARCHOMP], [EARTHQUAKE_ONLY])
    fainted = state.sides[0].with_current(replace(state.sides[0].current, hp=0))
    state = state.with_side(0, fainted)

    assert judge(choice(state, Switch(1))) is None


def test_recording_player_keeps_every_choice_for_review() -> None:
    state = start_battle([GARCHOMP], [CHARIZARD])
    recorder = RecordingPlayer(GreedyPlayer())

    action = recorder.choose(state, 0, legal_actions(state, 0))

    assert action == UseMove(1)
    assert recorder.choices == [Choice(state, 0, legal_actions(state, 0), UseMove(1))]
    assert find_mistakes(recorder.choices) == ()
    assert len(find_mistakes([choice(state, UseMove(0))])) == 1
