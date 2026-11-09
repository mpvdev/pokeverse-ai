import pytest
from pydantic import ValidationError

from pokeverse.catalog import BaseStats, Pokemon, PokemonType
from pokeverse.teams import Team

T = PokemonType
STATS = BaseStats(hp=80, attack=80, defense=80, special_attack=80, special_defense=80, speed=80)
PIKACHU = Pokemon(pokedex_id=25, name="pikachu", types=(T.ELECTRIC,), stats=STATS)
CHARIZARD = Pokemon(pokedex_id=6, name="charizard", types=(T.FIRE, T.FLYING), stats=STATS)


def test_team_keeps_member_order() -> None:
    team = Team(members=(PIKACHU, CHARIZARD))

    assert team.names == ("pikachu", "charizard")
    assert team.to_dict() == {
        "members": [PIKACHU.to_dict(stats=False), CHARIZARD.to_dict(stats=False)]
    }


def test_full_team_of_six_is_allowed() -> None:
    members = tuple(
        Pokemon(pokedex_id=i, name=f"mon-{i}", types=(T.NORMAL,), stats=STATS) for i in range(1, 7)
    )

    assert len(Team(members=members).members) == 6


def test_same_species_may_appear_more_than_once() -> None:
    team = Team(members=(PIKACHU, CHARIZARD, PIKACHU))

    assert team.names == ("pikachu", "charizard", "pikachu")


@pytest.mark.parametrize(
    ("members", "message"),
    [
        ((), "between 1 and 6"),
        (
            tuple(
                Pokemon(pokedex_id=i, name=f"mon-{i}", types=(T.NORMAL,), stats=STATS)
                for i in range(1, 8)
            ),
            "between 1 and 6",
        ),
    ],
)
def test_invalid_teams_are_rejected(members: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Team(members=members)  # type: ignore[arg-type]


@pytest.mark.parametrize("members", [[PIKACHU], ("pikachu",)])
def test_members_must_be_a_tuple_of_pokemon(members: object) -> None:
    with pytest.raises(ValidationError) as excinfo:
        Team(members=members)  # type: ignore[arg-type]

    assert excinfo.value.errors()[0]["loc"][0] == "members"
