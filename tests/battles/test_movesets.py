from collections.abc import Iterator

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

OUTRAGE = Move(
    move_id=200,
    name="outrage",
    type=T.DRAGON,
    damage_class=D.PHYSICAL,
    power=120,
    accuracy=100,
    priority=0,
    pp=10,
)
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
FIRE_FANG = Move(
    move_id=424,
    name="fire-fang",
    type=T.FIRE,
    damage_class=D.PHYSICAL,
    power=65,
    accuracy=95,
    priority=0,
    pp=15,
)
SWORDS_DANCE = Move(
    move_id=14,
    name="swords-dance",
    type=T.NORMAL,
    damage_class=D.STATUS,
    power=None,
    accuracy=None,
    priority=0,
    pp=20,
)
HYPER_BEAM = Move(
    move_id=63,
    name="hyper-beam",
    type=T.NORMAL,
    damage_class=D.SPECIAL,
    power=150,
    accuracy=90,
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
    pokedex_id=445,
    name="garchomp",
    types=(T.DRAGON, T.GROUND),
    stats=BaseStats(
        hp=108, attack=130, defense=95, special_attack=80, special_defense=85, speed=102
    ),
    learnset=frozenset(move.name for move in ALL_MOVES if move is not THUNDERBOLT),
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
    body_slam = Move(
        move_id=34,
        name="body-slam",
        type=T.NORMAL,
        damage_class=D.PHYSICAL,
        power=85,
        accuracy=100,
        priority=0,
        pp=15,
    )
    snorlax = Pokemon(
        pokedex_id=143,
        name="snorlax",
        types=(T.NORMAL,),
        stats=BaseStats(
            hp=160, attack=110, defense=65, special_attack=65, special_defense=110, speed=30
        ),
        learnset=frozenset({"body-slam", "earthquake"}),
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
    species = GARCHOMP.model_copy(update={"learnset": frozenset({"swords-dance"})})
    catalog = PokemonCatalog(repository, FakeSource(species, (SWORDS_DANCE,)))

    with pytest.raises(ValueError, match="no moves usable in battle"):
        default_battler(catalog, "garchomp")
