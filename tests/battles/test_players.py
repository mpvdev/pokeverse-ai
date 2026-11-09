import random
from dataclasses import replace

import pytest

from pokeverse.battles import (
    Battler,
    BattleState,
    GreedyPlayer,
    RandomPlayer,
    Switch,
    UseMove,
    legal_actions,
    make_player,
    run_battle,
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
PIKACHU = Battler(PIKACHU_SPECIES, (THUNDERBOLT, QUICK_ATTACK))
CHARIZARD = Battler(CHARIZARD_SPECIES, (FLAMETHROWER,))


def greedy(state: BattleState, side: int = 0) -> Switch | UseMove:
    return GreedyPlayer().choose(state, side, legal_actions(state, side))


def test_greedy_picks_the_most_damaging_move_for_the_current_foe() -> None:
    assert greedy(start_battle([GARCHOMP], [PIKACHU])) == UseMove(0)
    assert greedy(start_battle([GARCHOMP], [CHARIZARD])) == UseMove(1)


def test_greedy_prefers_priority_when_both_moves_finish_the_foe() -> None:
    state = start_battle([PIKACHU], [CHARIZARD])
    weakened = replace(state.sides[1].current, hp=1)
    state = state.with_side(1, state.sides[1].with_current(weakened))

    assert greedy(state) == UseMove(1)


def test_greedy_switches_when_no_move_can_hurt() -> None:
    assert greedy(start_battle([EARTHQUAKE_ONLY, PIKACHU], [CHARIZARD])) == Switch(1)


def test_greedy_prefers_the_sure_knockout_over_a_stronger_move_that_can_miss() -> None:
    shaky = EARTHQUAKE.model_copy(update={"name": "shaky-quake", "power": 150, "accuracy": 90})
    species = GARCHOMP_SPECIES.model_copy(update={"learnset": LEARNSET | {"shaky-quake"}})
    state = start_battle([Battler(species, (shaky, EARTHQUAKE))], [PIKACHU])

    assert greedy(state) == UseMove(1)


def test_greedy_replaces_a_fainted_battler_with_the_best_attacker() -> None:
    state = start_battle([EARTHQUAKE_ONLY, CHARIZARD, PIKACHU], [CHARIZARD])
    fainted = replace(state.sides[0].current, hp=0)
    state = state.with_side(0, state.sides[0].with_current(fainted))

    assert greedy(state) == Switch(2)


def test_random_player_picks_legal_actions_reproducibly() -> None:
    state = start_battle([GARCHOMP, PIKACHU], [CHARIZARD])
    options = legal_actions(state, 0)

    first = [RandomPlayer(random.Random(3)).choose(state, 0, options) for _ in range(5)]
    picks = [RandomPlayer(random.Random(3)).choose(state, 0, options) for _ in range(5)]
    player = RandomPlayer(random.Random(3))
    many = {player.choose(state, 0, options) for _ in range(50)}

    assert first == picks
    assert many == set(options)


def test_make_player() -> None:
    assert isinstance(make_player("greedy", random.Random(0)), GreedyPlayer)
    assert isinstance(make_player("random", random.Random(0)), RandomPlayer)
    with pytest.raises(ValueError, match="unknown player"):
        make_player("genius", random.Random(0))


def test_greedy_beats_random_in_a_mirror_match() -> None:
    team = [EARTHQUAKE_ONLY, PIKACHU, CHARIZARD]
    greedy_wins = 0
    for seed in range(20):
        players = (GreedyPlayer(), RandomPlayer(random.Random(seed)))
        result = run_battle(team, team, players, random.Random(seed))
        greedy_wins += result.winner == 0

    assert greedy_wins >= 15
