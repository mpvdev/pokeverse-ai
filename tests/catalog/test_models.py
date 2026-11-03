import pytest

from pokeverse.catalog import Pokemon


def test_pokemon_can_be_created() -> None:
    pokemon = Pokemon(25, "Pikachu", ("Electric",))

    assert pokemon.pokedex_id == 25
    assert pokemon.name == "Pikachu"
    assert pokemon.types == ("Electric",)


def test_pokemon_with_same_values_is_equal() -> None:
    first = Pokemon(6, "Charizard", ("Fire", "Flying"))
    second = Pokemon(6, "Charizard", ("Fire", "Flying"))

    assert first == second


@pytest.mark.parametrize(
    ("pokedex_id", "name", "types"),
    [
        (0, "MissingNo.", ("Bird",)),
        (1, "", ("Grass",)),
        (1, "Bulbasaur", ()),
    ],
)
def test_invalid_pokemon_values_are_rejected(
    pokedex_id: int,
    name: str,
    types: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError):
        Pokemon(pokedex_id, name, types)
