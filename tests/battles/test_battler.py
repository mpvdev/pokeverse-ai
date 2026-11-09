from collections.abc import Iterator
from typing import Any, cast

import pytest

from pokeverse.battles import Battler, load_battler
from pokeverse.catalog import (
    BaseStats,
    DamageClass,
    Move,
    Pokemon,
    PokemonCatalog,
    PokemonType,
    SqlitePokemonRepository,
)
from pokeverse.catalog.pokeapi import PokemonNotFoundError

T = PokemonType
D = DamageClass

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
IRON_TAIL = Move(
    move_id=231,
    name="iron-tail",
    type=T.STEEL,
    damage_class=D.PHYSICAL,
    power=100,
    accuracy=75,
    priority=0,
    pp=15,
)
SURF = Move(
    move_id=57,
    name="surf",
    type=T.WATER,
    damage_class=D.SPECIAL,
    power=90,
    accuracy=100,
    priority=0,
    pp=15,
)
VOLT_TACKLE = Move(
    move_id=344,
    name="volt-tackle",
    type=T.ELECTRIC,
    damage_class=D.PHYSICAL,
    power=120,
    accuracy=100,
    priority=0,
    pp=15,
)
THUNDER_WAVE = Move(
    move_id=86,
    name="thunder-wave",
    type=T.ELECTRIC,
    damage_class=D.STATUS,
    power=None,
    accuracy=90,
    priority=0,
    pp=20,
)
SEISMIC_TOSS = Move(
    move_id=69,
    name="seismic-toss",
    type=T.FIGHTING,
    damage_class=D.PHYSICAL,
    power=None,
    accuracy=100,
    priority=0,
    pp=20,
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

PIKACHU = Pokemon(
    pokedex_id=25,
    name="pikachu",
    types=(T.ELECTRIC,),
    stats=BaseStats(hp=35, attack=55, defense=40, special_attack=50, special_defense=50, speed=90),
    learnset=frozenset(
        {
            "thunderbolt",
            "quick-attack",
            "iron-tail",
            "surf",
            "volt-tackle",
            "thunder-wave",
            "seismic-toss",
            "hyper-beam",
        }
    ),
)


def test_battler_with_four_moves() -> None:
    battler = Battler(PIKACHU, (THUNDERBOLT, QUICK_ATTACK, IRON_TAIL, SURF))

    assert [move.name for move in battler.moves] == [
        "thunderbolt",
        "quick-attack",
        "iron-tail",
        "surf",
    ]
    assert battler.to_dict()["pokemon"]["name"] == "pikachu"
    assert [move["name"] for move in battler.to_dict()["moves"]][0] == "thunderbolt"


@pytest.mark.parametrize(
    ("moves", "message"),
    [
        ((), "between 1 and 4"),
        ((THUNDERBOLT, QUICK_ATTACK, IRON_TAIL, SURF, VOLT_TACKLE), "between 1 and 4"),
        ([THUNDERBOLT], "tuple of Move"),
        (("thunderbolt",), "tuple of Move"),
        ((THUNDERBOLT, THUNDERBOLT), "duplicates"),
        ((THUNDERBOLT, FLAMETHROWER), "pikachu cannot learn: flamethrower"),
        ((THUNDER_WAVE,), "not supported in battle: thunder-wave"),
        ((SEISMIC_TOSS,), "not supported in battle: seismic-toss"),
        ((HYPER_BEAM,), "not supported in battle: hyper-beam"),
    ],
)
def test_invalid_battler_is_rejected(moves: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Battler(PIKACHU, moves)


def test_pokemon_must_be_a_pokemon() -> None:
    with pytest.raises(ValueError, match="Pokemon"):
        Battler(cast(Any, "pikachu"), (THUNDERBOLT,))


class FakeSource:
    def __init__(self) -> None:
        self.move_calls: list[str | int] = []

    def fetch_pokemon(self, name_or_id: str | int) -> Pokemon:
        return PIKACHU

    def fetch_move(self, name_or_id: str | int) -> Move:
        self.move_calls.append(name_or_id)
        moves = {move.name: move for move in (THUNDERBOLT, QUICK_ATTACK, THUNDER_WAVE)}
        if name_or_id not in moves:
            raise PokemonNotFoundError(str(name_or_id))
        return moves[str(name_or_id)]


@pytest.fixture
def source() -> FakeSource:
    return FakeSource()


@pytest.fixture
def catalog(source: FakeSource) -> Iterator[PokemonCatalog]:
    with SqlitePokemonRepository(":memory:") as repository:
        yield PokemonCatalog(repository, source)


def test_load_battler_resolves_moves_through_the_catalog(
    catalog: PokemonCatalog, source: FakeSource
) -> None:
    battler = load_battler(catalog, "pikachu", ["thunderbolt", "quick-attack"])

    assert battler.moves == (THUNDERBOLT, QUICK_ATTACK)
    assert source.move_calls == ["thunderbolt", "quick-attack"]


def test_load_battler_checks_the_learnset_before_fetching_moves(
    catalog: PokemonCatalog, source: FakeSource
) -> None:
    with pytest.raises(ValueError, match="cannot learn: flamethrower"):
        load_battler(catalog, "pikachu", ["thunderbolt", "flamethrower"])
    assert source.move_calls == []


@pytest.mark.parametrize("count", [0, 5])
def test_load_battler_checks_the_move_count_first(
    catalog: PokemonCatalog, source: FakeSource, count: int
) -> None:
    with pytest.raises(ValueError, match="between 1 and 4"):
        load_battler(catalog, "pikachu", ["thunderbolt"] * count)
    assert source.move_calls == []


def test_load_battler_rejects_status_moves(catalog: PokemonCatalog) -> None:
    with pytest.raises(ValueError, match="thunder-wave"):
        load_battler(catalog, "pikachu", ["thunder-wave"])
