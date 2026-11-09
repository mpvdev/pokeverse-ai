from collections.abc import Iterator
from dataclasses import replace

import pytest

from pokeverse.battles import choose_moveset, default_battler, move_score
from pokeverse.catalog import (
    BaseStats,
    DamageClass,
    Move,
    MoveNotInCatalogError,
    Pokemon,
    PokemonCatalog,
    PokemonType,
    SqlitePokemonRepository,
)
from pokeverse.catalog.pokeapi import PokemonNotFoundError

T = PokemonType
D = DamageClass

OUTRAGE = Move(200, "outrage", T.DRAGON, D.PHYSICAL, 120, 100, 0, 10)
EARTHQUAKE = Move(89, "earthquake", T.GROUND, D.PHYSICAL, 100, 100, 0, 10)
DRAGON_CLAW = Move(337, "dragon-claw", T.DRAGON, D.PHYSICAL, 80, 100, 0, 15)
STONE_EDGE = Move(444, "stone-edge", T.ROCK, D.PHYSICAL, 100, 80, 0, 5)
FIRE_FANG = Move(424, "fire-fang", T.FIRE, D.PHYSICAL, 65, 95, 0, 15)
SWORDS_DANCE = Move(14, "swords-dance", T.NORMAL, D.STATUS, None, None, 0, 20)
HYPER_BEAM = Move(63, "hyper-beam", T.NORMAL, D.SPECIAL, 150, 90, 0, 5)
THUNDERBOLT = Move(85, "thunderbolt", T.ELECTRIC, D.SPECIAL, 90, 100, 0, 15)

ALL_MOVES = (
    OUTRAGE,
    EARTHQUAKE,
    DRAGON_CLAW,
    STONE_EDGE,
    FIRE_FANG,
    SWORDS_DANCE,
    HYPER_BEAM,
    THUNDERBOLT,
)

GARCHOMP = Pokemon(
    445,
    "garchomp",
    (T.DRAGON, T.GROUND),
    BaseStats(108, 130, 95, 80, 85, 102),
    frozenset(move.name for move in ALL_MOVES if move is not THUNDERBOLT),
)


def test_move_score_uses_power_accuracy_stab_and_the_matching_stat() -> None:
    assert move_score(GARCHOMP, EARTHQUAKE) == 100 * 1.5 * 150
    assert move_score(GARCHOMP, STONE_EDGE) == 100 * 0.8 * 150
    assert move_score(GARCHOMP, THUNDERBOLT) == 90 * 100


def test_default_moveset_is_strongest_move_then_coverage() -> None:
    chosen = choose_moveset(GARCHOMP, ALL_MOVES)

    assert [move.name for move in chosen] == ["outrage", "earthquake", "stone-edge", "fire-fang"]


def test_default_moveset_skips_status_unmodelled_and_unlearnable_moves() -> None:
    chosen = {move.name for move in choose_moveset(GARCHOMP, ALL_MOVES)}

    assert not chosen & {"swords-dance", "hyper-beam", "thunderbolt"}


def test_default_moveset_can_be_shorter_than_four() -> None:
    assert choose_moveset(GARCHOMP, (EARTHQUAKE, SWORDS_DANCE)) == (EARTHQUAKE,)
    assert choose_moveset(GARCHOMP, (SWORDS_DANCE,)) == ()


def test_first_pick_is_the_strongest_move_even_without_coverage() -> None:
    body_slam = Move(34, "body-slam", T.NORMAL, D.PHYSICAL, 85, 100, 0, 15)
    snorlax = Pokemon(
        143,
        "snorlax",
        (T.NORMAL,),
        BaseStats(160, 110, 65, 65, 110, 30),
        frozenset({"body-slam", "earthquake"}),
    )

    assert choose_moveset(snorlax, (EARTHQUAKE, body_slam))[0] == body_slam


class FakeSource:
    def __init__(self, pokemon: Pokemon, moves: tuple[Move, ...]) -> None:
        self.pokemon = pokemon
        self.moves = {move.name: move for move in moves}
        self.move_calls: list[str | int] = []

    def fetch_pokemon(self, name_or_id: str | int) -> Pokemon:
        return self.pokemon

    def fetch_move(self, name_or_id: str | int) -> Move:
        self.move_calls.append(name_or_id)
        if name_or_id not in self.moves:
            raise PokemonNotFoundError(str(name_or_id))
        return self.moves[str(name_or_id)]


@pytest.fixture
def repository() -> Iterator[SqlitePokemonRepository]:
    with SqlitePokemonRepository(":memory:") as repo:
        yield repo


def test_default_battler_resolves_every_learnable_move(
    repository: SqlitePokemonRepository,
) -> None:
    source = FakeSource(GARCHOMP, ALL_MOVES)
    catalog = PokemonCatalog(repository, source)

    battler = default_battler(catalog, "garchomp")

    assert [move.name for move in battler.moves] == [
        "outrage",
        "earthquake",
        "stone-edge",
        "fire-fang",
    ]
    assert sorted(source.move_calls) == sorted(GARCHOMP.learnset)


def test_default_battler_fails_when_a_learnable_move_is_unavailable(
    repository: SqlitePokemonRepository,
) -> None:
    catalog = PokemonCatalog(repository, FakeSource(GARCHOMP, (EARTHQUAKE,)))

    with pytest.raises(MoveNotInCatalogError):
        default_battler(catalog, "garchomp")


def test_default_battler_needs_at_least_one_battle_move(
    repository: SqlitePokemonRepository,
) -> None:
    species = replace(GARCHOMP, learnset=frozenset({"swords-dance"}))
    catalog = PokemonCatalog(repository, FakeSource(species, (SWORDS_DANCE,)))

    with pytest.raises(ValueError, match="no moves usable in battle"):
        default_battler(catalog, "garchomp")
