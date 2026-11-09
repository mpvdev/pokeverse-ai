from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from pokeverse.catalog import BaseStats, DamageClass, Move, Pokemon, PokemonType, parse_identifier

PIKACHU_STATS = BaseStats(
    hp=35, attack=55, defense=40, special_attack=50, special_defense=50, speed=90
)
CHARIZARD_STATS = BaseStats(
    hp=78, attack=84, defense=78, special_attack=109, special_defense=85, speed=100
)


def rejected_field(build: Callable[[], object]) -> str:
    """The top-level field pydantic rejected ("" for whole-model rules)."""
    with pytest.raises(ValidationError) as error:
        build()
    (problem, *_) = error.value.errors()
    return str(problem["loc"][0]) if problem["loc"] else ""


def test_pokemon_can_be_created() -> None:
    pokemon = Pokemon(
        pokedex_id=25, name="pikachu", types=(PokemonType.ELECTRIC,), stats=PIKACHU_STATS
    )

    assert pokemon.pokedex_id == 25
    assert pokemon.name == "pikachu"
    assert pokemon.types == (PokemonType.ELECTRIC,)
    assert pokemon.stats.speed == 90


def test_pokemon_with_same_values_is_equal() -> None:
    first = Pokemon(
        pokedex_id=6,
        name="charizard",
        types=(PokemonType.FIRE, PokemonType.FLYING),
        stats=CHARIZARD_STATS,
    )
    second = Pokemon(
        pokedex_id=6,
        name="charizard",
        types=(PokemonType.FIRE, PokemonType.FLYING),
        stats=CHARIZARD_STATS,
    )

    assert first == second
    assert hash(first) == hash(second)


def test_pokemon_is_immutable() -> None:
    pokemon = Pokemon(
        pokedex_id=25, name="pikachu", types=(PokemonType.ELECTRIC,), stats=PIKACHU_STATS
    )

    with pytest.raises(ValidationError, match="frozen"):
        pokemon.name = "raichu"


@pytest.mark.parametrize("name", ["mr-mime", "porygon2", "nidoran-f", "ho-oh"])
def test_pokemon_accepts_canonical_slug_names(name: str) -> None:
    assert (
        Pokemon(pokedex_id=1, name=name, types=(PokemonType.NORMAL,), stats=PIKACHU_STATS).name
        == name
    )


def test_pokemon_type_values_match_pokeapi_names() -> None:
    assert len(PokemonType) == 18
    assert PokemonType("electric") is PokemonType.ELECTRIC
    assert all(member.value == member.name.lower() for member in PokemonType)


@pytest.mark.parametrize("pokedex_id", [0, -1, True, False, 25.0, "25", None])
def test_invalid_pokedex_id_is_rejected(pokedex_id: Any) -> None:
    assert (
        rejected_field(
            lambda: Pokemon(
                pokedex_id=pokedex_id,
                name="pikachu",
                types=(PokemonType.ELECTRIC,),
                stats=PIKACHU_STATS,
            )
        )
        == "pokedex_id"
    )


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
    assert (
        rejected_field(
            lambda: Pokemon(
                pokedex_id=25, name=name, types=(PokemonType.ELECTRIC,), stats=PIKACHU_STATS
            )
        )
        == "name"
    )


@pytest.mark.parametrize(
    "types",
    [
        [PokemonType.ELECTRIC],
        {PokemonType.ELECTRIC},
        PokemonType.ELECTRIC,
        (),
        (PokemonType.FIRE, PokemonType.FLYING, PokemonType.DRAGON),
        ("electric",),
        (PokemonType.FIRE, "flying"),
        (None,),
        (PokemonType.FIRE, PokemonType.FIRE),
    ],
)
def test_invalid_types_are_rejected(types: Any) -> None:
    assert (
        rejected_field(
            lambda: Pokemon(pokedex_id=6, name="charizard", types=types, stats=CHARIZARD_STATS)
        )
        == "types"
    )


def test_duplicate_types_are_explained() -> None:
    with pytest.raises(ValidationError, match="types must not contain duplicates"):
        Pokemon(
            pokedex_id=6,
            name="charizard",
            types=(PokemonType.FIRE, PokemonType.FIRE),
            stats=CHARIZARD_STATS,
        )


@pytest.mark.parametrize("stats", [None, (35, 55, 40, 50, 50, 90), {"hp": 35}])
def test_stats_must_be_base_stats(stats: Any) -> None:
    assert (
        rejected_field(
            lambda: Pokemon(
                pokedex_id=25, name="pikachu", types=(PokemonType.ELECTRIC,), stats=stats
            )
        )
        == "stats"
    )


def test_base_stats_total() -> None:
    assert CHARIZARD_STATS.total == 534


@pytest.mark.parametrize("value", [1, 255])
def test_base_stats_accept_the_full_range(value: int) -> None:
    assert (
        BaseStats(
            hp=value,
            attack=value,
            defense=value,
            special_attack=value,
            special_defense=value,
            speed=value,
        ).hp
        == value
    )


@pytest.mark.parametrize("value", [0, 256, -5, True, 50.0, "50", None])
def test_invalid_base_stat_is_rejected(value: Any) -> None:
    assert (
        rejected_field(
            lambda: BaseStats(
                hp=35, attack=55, defense=40, special_attack=50, special_defense=50, speed=value
            )
        )
        == "speed"
    )


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
    mr_mime = Pokemon(
        pokedex_id=122,
        name="mr-mime",
        types=(PokemonType.PSYCHIC, PokemonType.FAIRY),
        stats=PIKACHU_STATS,
    )
    assert mr_mime.display_name == "Mr Mime"


def test_to_dict_is_json_friendly() -> None:
    pokemon = Pokemon(
        pokedex_id=6,
        name="charizard",
        types=(PokemonType.FIRE, PokemonType.FLYING),
        stats=CHARIZARD_STATS,
    )

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
    pokemon = Pokemon(
        pokedex_id=25, name="pikachu", types=(PokemonType.ELECTRIC,), stats=PIKACHU_STATS
    )

    assert pokemon.to_dict(stats=False) == {
        "pokedex_id": 25,
        "name": "pikachu",
        "types": ["electric"],
    }


def test_learnset_is_kept_but_not_serialized() -> None:
    learnset = frozenset({"thunderbolt", "u-turn"})
    pokemon = Pokemon(
        pokedex_id=25,
        name="pikachu",
        types=(PokemonType.ELECTRIC,),
        stats=PIKACHU_STATS,
        learnset=learnset,
    )

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
    assert (
        rejected_field(
            lambda: Pokemon(
                pokedex_id=25,
                name="pikachu",
                types=(PokemonType.ELECTRIC,),
                stats=PIKACHU_STATS,
                learnset=learnset,
            )
        )
        == "learnset"
    )


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
    ("overrides", "field"),
    [
        ({"move_id": 0}, "move_id"),
        ({"move_id": "85"}, "move_id"),
        ({"name": "Thunderbolt"}, "name"),
        ({"name": "breakneck-blitz--physical"}, "name"),
        ({"type": "electric"}, "type"),
        ({"damage_class": "special"}, "damage_class"),
        ({"damage_class": DamageClass.STATUS}, ""),
        ({"power": 0}, "power"),
        ({"power": 251}, "power"),
        ({"accuracy": 0}, "accuracy"),
        ({"accuracy": 101}, "accuracy"),
        ({"priority": 6}, "priority"),
        ({"priority": None}, "priority"),
        ({"pp": 0}, "pp"),
        ({"pp": None}, "pp"),
        ({"power": True}, "power"),
    ],
)
def test_invalid_move_is_rejected(overrides: dict[str, Any], field: str) -> None:
    assert rejected_field(lambda: make_move(**overrides)) == field


def test_status_moves_with_power_are_explained() -> None:
    with pytest.raises(ValidationError, match="status moves must not have power"):
        make_move(damage_class=DamageClass.STATUS)
