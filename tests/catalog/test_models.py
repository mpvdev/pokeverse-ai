from typing import Any

import pytest

from pokeverse.catalog import BaseStats, DamageClass, Move, Pokemon, PokemonType, parse_identifier

PIKACHU_STATS = BaseStats(35, 55, 40, 50, 50, 90)
CHARIZARD_STATS = BaseStats(78, 84, 78, 109, 85, 100)


def test_pokemon_can_be_created() -> None:
    pokemon = Pokemon(25, "pikachu", (PokemonType.ELECTRIC,), PIKACHU_STATS)

    assert pokemon.pokedex_id == 25
    assert pokemon.name == "pikachu"
    assert pokemon.types == (PokemonType.ELECTRIC,)
    assert pokemon.stats.speed == 90


def test_pokemon_with_same_values_is_equal() -> None:
    first = Pokemon(6, "charizard", (PokemonType.FIRE, PokemonType.FLYING), CHARIZARD_STATS)
    second = Pokemon(6, "charizard", (PokemonType.FIRE, PokemonType.FLYING), CHARIZARD_STATS)

    assert first == second
    assert hash(first) == hash(second)


def test_pokemon_is_immutable() -> None:
    pokemon = Pokemon(25, "pikachu", (PokemonType.ELECTRIC,), PIKACHU_STATS)

    with pytest.raises(AttributeError):
        pokemon.name = "raichu"  # type: ignore[misc]


@pytest.mark.parametrize("name", ["mr-mime", "porygon2", "nidoran-f", "ho-oh"])
def test_pokemon_accepts_canonical_slug_names(name: str) -> None:
    assert Pokemon(1, name, (PokemonType.NORMAL,), PIKACHU_STATS).name == name


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
        Pokemon(pokedex_id, "pikachu", (PokemonType.ELECTRIC,), PIKACHU_STATS)


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
        Pokemon(25, name, (PokemonType.ELECTRIC,), PIKACHU_STATS)


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
        Pokemon(6, "charizard", types, CHARIZARD_STATS)


@pytest.mark.parametrize("stats", [None, (35, 55, 40, 50, 50, 90), {"hp": 35}])
def test_stats_must_be_base_stats(stats: Any) -> None:
    with pytest.raises(ValueError, match="BaseStats"):
        Pokemon(25, "pikachu", (PokemonType.ELECTRIC,), stats)


def test_base_stats_total() -> None:
    assert CHARIZARD_STATS.total == 534


@pytest.mark.parametrize("value", [1, 255])
def test_base_stats_accept_the_full_range(value: int) -> None:
    assert BaseStats(value, value, value, value, value, value).hp == value


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (0, "between 1 and 255"),
        (256, "between 1 and 255"),
        (-5, "between 1 and 255"),
        (True, "integer"),
        (50.0, "integer"),
        ("50", "integer"),
        (None, "integer"),
    ],
)
def test_invalid_base_stat_is_rejected(value: Any, message: str) -> None:
    with pytest.raises(ValueError, match=f"speed must be (an )?{message}"):
        BaseStats(35, 55, 40, 50, 50, value)


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
    mr_mime = Pokemon(122, "mr-mime", (PokemonType.PSYCHIC, PokemonType.FAIRY), PIKACHU_STATS)
    assert mr_mime.display_name == "Mr Mime"


def test_to_dict_is_json_friendly() -> None:
    pokemon = Pokemon(6, "charizard", (PokemonType.FIRE, PokemonType.FLYING), CHARIZARD_STATS)

    assert pokemon.to_dict() == {
        "pokedex_id": 6,
        "name": "charizard",
        "types": ["fire", "flying"],
        "base_stats": {
            "hp": 78,
            "attack": 84,
            "defense": 78,
            "special_attack": 109,
            "special_defense": 85,
            "speed": 100,
        },
    }


def test_to_dict_can_omit_stats() -> None:
    pokemon = Pokemon(25, "pikachu", (PokemonType.ELECTRIC,), PIKACHU_STATS)

    assert pokemon.to_dict(stats=False) == {
        "pokedex_id": 25,
        "name": "pikachu",
        "types": ["electric"],
    }


def test_learnset_is_kept_but_not_serialized() -> None:
    learnset = frozenset({"thunderbolt", "u-turn"})
    pokemon = Pokemon(25, "pikachu", (PokemonType.ELECTRIC,), PIKACHU_STATS, learnset)

    assert pokemon.learnset == learnset
    assert "learnset" not in pokemon.to_dict()


@pytest.mark.parametrize(
    "learnset",
    [
        {"thunderbolt"},
        ("thunderbolt",),
        frozenset({"Thunderbolt"}),
        frozenset({"swords dance"}),
        frozenset({85}),
    ],
)
def test_invalid_learnset_is_rejected(learnset: Any) -> None:
    with pytest.raises(ValueError, match="learnset"):
        Pokemon(25, "pikachu", (PokemonType.ELECTRIC,), PIKACHU_STATS, learnset)


def make_move(**overrides: Any) -> Move:
    fields: dict[str, Any] = {
        "move_id": 85,
        "name": "thunderbolt",
        "type": PokemonType.ELECTRIC,
        "damage_class": DamageClass.SPECIAL,
        "power": 90,
        "accuracy": 100,
        "priority": 0,
        "pp": 15,
    }
    return Move(**(fields | overrides))


def test_move_can_be_created_and_serialized() -> None:
    move = make_move()

    assert move.display_name == "Thunderbolt"
    assert move.to_dict() == {
        "move_id": 85,
        "name": "thunderbolt",
        "type": "electric",
        "damage_class": "special",
        "power": 90,
        "accuracy": 100,
        "priority": 0,
        "pp": 15,
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "name": "swords-dance",
            "damage_class": DamageClass.STATUS,
            "power": None,
            "accuracy": None,
        },
        {"name": "seismic-toss", "damage_class": DamageClass.PHYSICAL, "power": None},
        {"name": "swift", "accuracy": None},
        {"name": "explosion", "power": 250},
        {"name": "trick-room", "damage_class": DamageClass.STATUS, "power": None, "priority": -7},
        {"name": "struggle", "pp": 1},
    ],
)
def test_move_accepts_real_edge_cases(overrides: dict[str, Any]) -> None:
    assert make_move(**overrides).name == overrides["name"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"move_id": 0}, "positive"),
        ({"move_id": "85"}, "integer"),
        ({"name": "Thunderbolt"}, "slug"),
        ({"name": "breakneck-blitz--physical"}, "slug"),
        ({"type": "electric"}, "PokemonType"),
        ({"damage_class": "special"}, "DamageClass"),
        ({"damage_class": DamageClass.STATUS}, "status moves must not have power"),
        ({"power": 0}, "power must be between 1 and 250"),
        ({"power": 251}, "power must be between 1 and 250"),
        ({"accuracy": 0}, "accuracy must be between 1 and 100"),
        ({"accuracy": 101}, "accuracy must be between 1 and 100"),
        ({"priority": 6}, "priority must be between -7 and 5"),
        ({"priority": None}, "priority must be an integer"),
        ({"pp": 0}, "pp must be between 1 and 40"),
        ({"pp": None}, "pp must be an integer"),
        ({"power": True}, "power must be an integer"),
    ],
)
def test_invalid_move_is_rejected(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        make_move(**overrides)
