import httpx
import pytest

from pokeverse.catalog import PokemonType
from pokeverse.catalog.type_chart import TYPE_CHART, defensive_profile, effectiveness

T = PokemonType


def test_chart_covers_every_attacking_type() -> None:
    assert set(TYPE_CHART) == set(PokemonType)
    assert all(
        multiplier in {0, 0.5, 2} for row in TYPE_CHART.values() for multiplier in row.values()
    )


@pytest.mark.parametrize(
    ("attacking", "defending", "expected"),
    [
        (T.PSYCHIC, (T.GHOST, T.POISON), 2.0),  # the Gengar mistake from the Phase 1 eval
        (T.ELECTRIC, (T.DRAGON, T.GROUND), 0.0),  # Garchomp
        (T.ROCK, (T.FIRE, T.FLYING), 4.0),  # Charizard
        (T.GRASS, (T.FIRE, T.FLYING), 0.25),
        (T.FIGHTING, (T.NORMAL,), 2.0),
        (T.NORMAL, (T.NORMAL,), 1.0),
        (T.DRAGON, (T.FAIRY,), 0.0),
    ],
)
def test_effectiveness(
    attacking: PokemonType, defending: tuple[PokemonType, ...], expected: float
) -> None:
    assert effectiveness(attacking, defending) == expected


def test_defensive_profile_of_gengar() -> None:
    profile = defensive_profile((T.GHOST, T.POISON))

    assert profile["weak_to"] == {"ground": 2, "psychic": 2, "ghost": 2, "dark": 2}
    assert profile["immune_to"] == {"normal": 0, "fighting": 0}
    assert profile["resists"] == {"grass": 0.5, "poison": 0.25, "bug": 0.25, "fairy": 0.5}


@pytest.mark.network
@pytest.mark.parametrize("attacking", list(PokemonType), ids=str)
def test_chart_matches_pokeapi(attacking: PokemonType) -> None:
    response = httpx.get(f"https://pokeapi.co/api/v2/type/{attacking.value}", timeout=10)
    response.raise_for_status()
    relations = response.json()["damage_relations"]
    known = {member.value for member in PokemonType}
    expected = {
        entry["name"]: multiplier
        for key, multiplier in (
            ("double_damage_to", 2),
            ("half_damage_to", 0.5),
            ("no_damage_to", 0),
        )
        for entry in relations[key]
        if entry["name"] in known
    }

    assert {k.value: v for k, v in TYPE_CHART[attacking].items()} == expected
