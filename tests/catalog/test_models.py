from typing import Any

import pytest

from pokeverse.catalog import Pokemon, PokemonType, parse_identifier


def test_pokemon_can_be_created() -> None:
    pokemon = Pokemon(25, "pikachu", (PokemonType.ELECTRIC,))

    assert pokemon.pokedex_id == 25
    assert pokemon.name == "pikachu"
    assert pokemon.types == (PokemonType.ELECTRIC,)


def test_pokemon_with_same_values_is_equal() -> None:
    first = Pokemon(6, "charizard", (PokemonType.FIRE, PokemonType.FLYING))
    second = Pokemon(6, "charizard", (PokemonType.FIRE, PokemonType.FLYING))

    assert first == second
    assert hash(first) == hash(second)


def test_pokemon_is_immutable() -> None:
    pokemon = Pokemon(25, "pikachu", (PokemonType.ELECTRIC,))

    with pytest.raises(AttributeError):
        pokemon.name = "raichu"  # type: ignore[misc]


@pytest.mark.parametrize("name", ["mr-mime", "porygon2", "nidoran-f", "ho-oh"])
def test_pokemon_accepts_canonical_slug_names(name: str) -> None:
    assert Pokemon(1, name, (PokemonType.NORMAL,)).name == name


def test_pokemon_type_values_match_pokeapi_names() -> None:
    assert len(PokemonType) == 18
    assert PokemonType("electric") is PokemonType.ELECTRIC
    assert all(member.value == member.name.lower() for member in PokemonType)


@pytest.mark.parametrize(
    ("pokedex_id", "message"),
    [
        (0, "positive"),
        (-1, "positive"),
        (True, "integer"),
        (False, "integer"),
        (25.0, "integer"),
        ("25", "integer"),
        (None, "integer"),
    ],
)
def test_invalid_pokedex_id_is_rejected(pokedex_id: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Pokemon(pokedex_id, "pikachu", (PokemonType.ELECTRIC,))


@pytest.mark.parametrize(
    "name",
    [
        "",
        "   ",
        "Pikachu",
        " pikachu",
        "pikachu ",
        "pikachu\n",
        "mr mime",
        "mr.-mime",
        "farfetch'd",
        "-pikachu",
        "pikachu-",
        "mr--mime",
        None,
        25,
    ],
)
def test_non_canonical_name_is_rejected(name: Any) -> None:
    with pytest.raises(ValueError, match="slug"):
        Pokemon(25, name, (PokemonType.ELECTRIC,))


@pytest.mark.parametrize(
    ("types", "message"),
    [
        ([PokemonType.ELECTRIC], "tuple"),
        ({PokemonType.ELECTRIC}, "tuple"),
        (PokemonType.ELECTRIC, "tuple"),
        ((), "between 1 and 2"),
        ((PokemonType.FIRE, PokemonType.FLYING, PokemonType.DRAGON), "between 1 and 2"),
        (("electric",), "PokemonType"),
        ((PokemonType.FIRE, "flying"), "PokemonType"),
        ((None,), "PokemonType"),
        ((PokemonType.FIRE, PokemonType.FIRE), "duplicates"),
    ],
)
def test_invalid_types_are_rejected(types: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Pokemon(6, "charizard", types)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("pikachu", "pikachu"), ("  Pikachu ", "pikachu"), ("MR-MIME", "mr-mime"), (25, 25)],
)
def test_parse_identifier_normalizes(raw: str | int, expected: str | int) -> None:
    assert parse_identifier(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", 0, -1, True, False, None, 2.5])
def test_parse_identifier_rejects_invalid(raw: Any) -> None:
    with pytest.raises(ValueError):
        parse_identifier(raw)


def test_display_name_is_derived_from_slug() -> None:
    assert Pokemon(122, "mr-mime", (PokemonType.PSYCHIC, PokemonType.FAIRY)).display_name == (
        "Mr Mime"
    )


def test_to_dict_is_json_friendly() -> None:
    pokemon = Pokemon(6, "charizard", (PokemonType.FIRE, PokemonType.FLYING))

    assert pokemon.to_dict() == {
        "pokedex_id": 6,
        "name": "charizard",
        "types": ["fire", "flying"],
    }
