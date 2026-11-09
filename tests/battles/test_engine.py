import random

import pytest

from pokeverse.battles import (
    Action,
    BattleEvent,
    Battler,
    BattleState,
    IllegalActionError,
    Switch,
    UseMove,
    legal_actions,
    play_turn,
    replace_fainted,
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
STONE_EDGE = Move(
    move_id=444,
    name="stone-edge",
    type=T.ROCK,
    damage_class=D.PHYSICAL,
    power=100,
    accuracy=80,
    priority=0,
    pp=5,
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

LEARNSET = frozenset({m.name for m in (EARTHQUAKE, STONE_EDGE, THUNDERBOLT, QUICK_ATTACK)})


def pokemon(pokedex_id: int, name: str, types: tuple[T, ...], stats: BaseStats) -> Pokemon:
    return Pokemon(
        pokedex_id=pokedex_id,
        name=name,
        types=types,
        stats=stats,
        learnset=LEARNSET | {"flamethrower"},
    )


GARCHOMP_SPECIES = pokemon(
    445,
    "garchomp",
    (T.DRAGON, T.GROUND),
    BaseStats(hp=108, attack=130, defense=95, special_attack=80, special_defense=85, speed=102),
)
PIKACHU_SPECIES = pokemon(
    25,
    "pikachu",
    (T.ELECTRIC,),
    BaseStats(hp=35, attack=55, defense=40, special_attack=50, special_defense=50, speed=90),
)
CHARIZARD_SPECIES = pokemon(
    6,
    "charizard",
    (T.FIRE, T.FLYING),
    BaseStats(hp=78, attack=84, defense=78, special_attack=109, special_defense=85, speed=100),
)

GARCHOMP = Battler(pokemon=GARCHOMP_SPECIES, moves=(EARTHQUAKE, STONE_EDGE))
PIKACHU = Battler(pokemon=PIKACHU_SPECIES, moves=(THUNDERBOLT, QUICK_ATTACK))
CHARIZARD = Battler(pokemon=CHARIZARD_SPECIES, moves=(FLAMETHROWER,))
ELECTRIC_CHARIZARD = Battler(pokemon=CHARIZARD_SPECIES, moves=(THUNDERBOLT,))
EARTHQUAKE_ONLY = Battler(pokemon=GARCHOMP_SPECIES, moves=(EARTHQUAKE,))


class FixedRng(random.Random):
    """Every accuracy and damage roll at its maximum (high) or minimum; never a critical hit."""

    def __init__(self, high: bool) -> None:
        super().__init__(0)
        self.high = high

    def random(self) -> float:
        return 0.5

    def randint(self, a: int, b: int) -> int:
        return b if self.high else a

    def randrange(self, start: int, *args: int, **kwargs: int) -> int:
        return start - 1


class FirstOption:
    def choose(self, state: BattleState, side: int, options: tuple[Action, ...]) -> Action:
        return options[0]


def kinds(events: tuple[BattleEvent, ...]) -> list[tuple[str, str | None]]:
    return [(event.kind, event.pokemon) for event in events]


def test_start_battle_sends_out_the_first_battlers_at_full_hp() -> None:
    state = start_battle([GARCHOMP], [PIKACHU, CHARIZARD])

    assert state.turn == 0
    assert state.sides[0].current.hp == state.sides[0].current.max_hp == 183
    assert state.sides[1].current.name == "pikachu"
    assert state.sides[1].current.hp == 110


@pytest.mark.parametrize("size", [0, 7])
def test_team_size_is_checked(size: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 6"):
        start_battle([GARCHOMP] * size, [PIKACHU])


def test_legal_actions_are_moves_and_switches_to_healthy_bench() -> None:
    state = start_battle([GARCHOMP], [PIKACHU, CHARIZARD])

    assert legal_actions(state, 0) == (UseMove(index=0), UseMove(index=1))
    assert legal_actions(state, 1) == (UseMove(index=0), UseMove(index=1), Switch(index=1))


def test_faster_battler_moves_first_and_a_knocked_out_one_does_not_act() -> None:
    state = start_battle([GARCHOMP], [PIKACHU, CHARIZARD])

    state, events = play_turn(state, (UseMove(index=0), UseMove(index=0)), FixedRng(high=False))

    assert kinds(events) == [("move", "garchomp"), ("damage", "pikachu"), ("faint", "pikachu")]
    assert events[1].damage == 110
    assert events[1].effectiveness == 2.0
    assert state.turn == 1
    assert state.needs_replacement(1)
    assert legal_actions(state, 1) == (Switch(index=1),)


def test_priority_beats_speed() -> None:
    state = start_battle([GARCHOMP], [PIKACHU])

    _, events = play_turn(state, (UseMove(index=0), UseMove(index=1)), FixedRng(high=False))

    assert events[0].pokemon == "pikachu"
    assert events[0].move == "quick-attack"


def test_switches_happen_before_moves() -> None:
    state = start_battle([GARCHOMP], [PIKACHU, CHARIZARD])

    state, events = play_turn(state, (UseMove(index=0), Switch(index=1)), FixedRng(high=False))

    assert kinds(events) == [
        ("switch", "charizard"),
        ("move", "garchomp"),
        ("no_effect", "charizard"),
    ]
    assert state.sides[1].current.hp == state.sides[1].current.max_hp


def test_accuracy_roll_can_miss() -> None:
    state = start_battle([GARCHOMP], [CHARIZARD])

    state, events = play_turn(state, (UseMove(index=1), UseMove(index=0)), FixedRng(high=True))

    assert ("miss", "garchomp") in kinds(events)
    assert state.sides[1].current.hp == state.sides[1].current.max_hp


def test_speed_ties_are_broken_by_the_rng() -> None:
    first_movers = set()
    for seed in range(20):
        state = start_battle([PIKACHU], [PIKACHU])
        _, events = play_turn(state, (UseMove(index=0), UseMove(index=0)), random.Random(seed))
        first_movers.add(events[0].side)

    assert first_movers == {0, 1}


@pytest.mark.parametrize("action", [UseMove(index=2), Switch(index=0), Switch(index=1)])
def test_illegal_actions_are_rejected(action: Action) -> None:
    state = start_battle([GARCHOMP], [PIKACHU])

    with pytest.raises(IllegalActionError):
        play_turn(state, (action, UseMove(index=0)), FixedRng(high=False))


def test_turns_wait_for_a_replacement_and_replacements_need_a_faint() -> None:
    state = start_battle([GARCHOMP], [PIKACHU, CHARIZARD])
    with pytest.raises(IllegalActionError, match="no fainted battler"):
        replace_fainted(state, 1, Switch(index=1))

    state, _ = play_turn(state, (UseMove(index=0), UseMove(index=0)), FixedRng(high=False))
    with pytest.raises(IllegalActionError, match="replaced first"):
        play_turn(state, (UseMove(index=0), Switch(index=1)), FixedRng(high=False))

    state, events = replace_fainted(state, 1, Switch(index=1))
    assert kinds(events) == [("switch", "charizard")]
    assert state.sides[1].current.name == "charizard"


def test_run_battle_plays_to_a_win() -> None:
    result = run_battle(
        [GARCHOMP], [PIKACHU, CHARIZARD], (FirstOption(), FirstOption()), random.Random(1)
    )

    assert result.winner == 1
    assert result.events[-1].kind == "win"
    assert result.state.sides[0].defeated
    assert ("switch", "charizard") in kinds(result.events)


def test_mutual_immunity_ends_in_a_draw_at_the_turn_limit() -> None:
    result = run_battle(
        [EARTHQUAKE_ONLY],
        [ELECTRIC_CHARIZARD],
        (FirstOption(), FirstOption()),
        random.Random(1),
        max_turns=10,
    )

    assert result.winner is None
    assert result.turns == 10
    assert result.events[-1].kind == "draw"


def test_battles_are_reproducible_from_a_seed() -> None:
    def play(seed: int) -> tuple[BattleEvent, ...]:
        players = (FirstOption(), FirstOption())
        return run_battle([GARCHOMP], [PIKACHU, CHARIZARD], players, random.Random(seed)).events

    assert play(5) == play(5)


def test_illegal_choices_from_players_are_rejected() -> None:
    class Cheater:
        def choose(self, state: BattleState, side: int, options: tuple[Action, ...]) -> Action:
            return UseMove(index=3)

    with pytest.raises(IllegalActionError):
        run_battle([GARCHOMP], [PIKACHU], (Cheater(), FirstOption()), random.Random(1))


def test_events_describe_themselves() -> None:
    event = BattleEvent(
        turn=1,
        kind="damage",
        side=1,
        pokemon="pikachu",
        move="earthquake",
        damage=110,
        hp=0,
        critical=True,
        effectiveness=2.0,
    )

    assert event.describe() == (
        "Pikachu takes 110 damage (0 HP left). A critical hit! It's super effective!"
    )
    assert (
        BattleEvent(turn=0, kind="switch", side=0, pokemon="mr-mime").describe()
        == "Side 1 sends out Mr Mime."
    )
    assert (
        BattleEvent(turn=12, kind="draw").describe() == "The battle ends in a draw after 12 turns."
    )
    assert event.to_dict()["critical"] is True
    assert "critical" not in BattleEvent(turn=1, kind="faint", side=1, pokemon="pikachu").to_dict()
