import pytest

from pokeverse.catalog import BaseStats, Pokemon, PokemonType
from pokeverse.teams import Team

T = PokemonType
STATS = BaseStats(80, 80, 80, 80, 80, 80)
PIKACHU = Pokemon(25, "pikachu", (T.ELECTRIC,), STATS)
CHARIZARD = Pokemon(6, "charizard", (T.FIRE, T.FLYING), STATS)


def test_team_keeps_member_order() -> None:
    team = Team((PIKACHU, CHARIZARD))

    assert team.names == ("pikachu", "charizard")
    assert team.to_dict() == {
        "members": [PIKACHU.to_dict(stats=False), CHARIZARD.to_dict(stats=False)]
    }


def test_full_team_of_six_is_allowed() -> None:
    members = tuple(Pokemon(i, f"mon-{i}", (T.NORMAL,), STATS) for i in range(1, 7))

    assert len(Team(members).members) == 6


def test_same_species_may_appear_more_than_once() -> None:
    team = Team((PIKACHU, CHARIZARD, PIKACHU))

    assert team.names == ("pikachu", "charizard", "pikachu")


@pytest.mark.parametrize(
    ("members", "message"),
    [
        ((), "between 1 and 6"),
        (tuple(Pokemon(i, f"mon-{i}", (T.NORMAL,), STATS) for i in range(1, 8)), "between 1 and 6"),
        ([PIKACHU], "tuple"),
        (("pikachu",), "must be Pokemon"),
    ],
)
def test_invalid_teams_are_rejected(members: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Team(members)  # type: ignore[arg-type]
