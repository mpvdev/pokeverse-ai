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

THUNDERBOLT = Move(85, "thunderbolt", T.ELECTRIC, D.SPECIAL, 90, 100, 0, 15)
QUICK_ATTACK = Move(98, "quick-attack", T.NORMAL, D.PHYSICAL, 40, 100, 1, 30)
IRON_TAIL = Move(231, "iron-tail", T.STEEL, D.PHYSICAL, 100, 75, 0, 15)
SURF = Move(57, "surf", T.WATER, D.SPECIAL, 90, 100, 0, 15)
VOLT_TACKLE = Move(344, "volt-tackle", T.ELECTRIC, D.PHYSICAL, 120, 100, 0, 15)
THUNDER_WAVE = Move(86, "thunder-wave", T.ELECTRIC, D.STATUS, None, 90, 0, 20)
SEISMIC_TOSS = Move(69, "seismic-toss", T.FIGHTING, D.PHYSICAL, None, 100, 0, 20)
FLAMETHROWER = Move(53, "flamethrower", T.FIRE, D.SPECIAL, 90, 100, 0, 15)

PIKACHU = Pokemon(
    25,
    "pikachu",
    (T.ELECTRIC,),
    BaseStats(35, 55, 40, 50, 50, 90),
    frozenset(
        {
            "thunderbolt",
            "quick-attack",
            "iron-tail",
            "surf",
            "volt-tackle",
            "thunder-wave",
            "seismic-toss",
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
        ((THUNDER_WAVE,), "fixed power are supported in battle: thunder-wave"),
        ((SEISMIC_TOSS,), "fixed power are supported in battle: seismic-toss"),
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
