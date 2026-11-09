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
GARCHOMP_SPECIES = Pokemon(
    pokedex_id=445,
    name="garchomp",
    types=(T.DRAGON, T.GROUND),
    stats=BaseStats(
        hp=108, attack=130, defense=95, special_attack=80, special_defense=85, speed=102
    ),
    learnset=LEARNSET,
)
PIKACHU_SPECIES = Pokemon(
    pokedex_id=25,
    name="pikachu",
    types=(T.ELECTRIC,),
    stats=BaseStats(hp=35, attack=55, defense=40, special_attack=50, special_defense=50, speed=90),
    learnset=LEARNSET,
)
CHARIZARD_SPECIES = Pokemon(
    pokedex_id=6,
    name="charizard",
    types=(T.FIRE, T.FLYING),
    stats=BaseStats(
        hp=78, attack=84, defense=78, special_attack=109, special_defense=85, speed=100
    ),
    learnset=LEARNSET,
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
    shaky = EARTHQUAKE.model_copy(update={"accuracy": 70})
    species = GARCHOMP_SPECIES
    state = start_battle([Battler(species, (shaky, DRAGON_CLAW)), CHARIZARD], [SLOW_PIKACHU])

    assert judge(choice(state, Switch(1))) is not None
    assert judge(choice(state, Switch(1))).better == "Dragon Claw"

    claw_misses = DRAGON_CLAW.model_copy(update={"accuracy": 90})
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
