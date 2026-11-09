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
    shaky = replace(EARTHQUAKE, name="shaky-quake", power=150, accuracy=90)
    species = replace(GARCHOMP_SPECIES, learnset=LEARNSET | {"shaky-quake"})
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
