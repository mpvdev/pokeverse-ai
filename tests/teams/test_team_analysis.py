from pokeverse.catalog import BaseStats, Pokemon, PokemonType
from pokeverse.teams import Team, analyze_team

T = PokemonType
STATS = BaseStats(hp=80, attack=80, defense=80, special_attack=80, special_defense=80, speed=80)
CHARIZARD = Pokemon(pokedex_id=6, name="charizard", types=(T.FIRE, T.FLYING), stats=STATS)
BLASTOISE = Pokemon(pokedex_id=9, name="blastoise", types=(T.WATER,), stats=STATS)
VENUSAUR = Pokemon(pokedex_id=3, name="venusaur", types=(T.GRASS, T.POISON), stats=STATS)
GARCHOMP = Pokemon(pokedex_id=445, name="garchomp", types=(T.DRAGON, T.GROUND), stats=STATS)
FLYGON = Pokemon(pokedex_id=330, name="flygon", types=(T.GROUND, T.DRAGON), stats=STATS)
LAPRAS = Pokemon(pokedex_id=131, name="lapras", types=(T.WATER, T.ICE), stats=STATS)
STARTERS = Team(members=(CHARIZARD, BLASTOISE, VENUSAUR))


def test_exposure_lists_every_attacking_type() -> None:
    analysis = analyze_team(STARTERS)

    assert [e.attacking_type for e in analysis.exposures] == list(PokemonType)


def test_starter_trio_is_vulnerable_only_to_electric() -> None:
    (electric,) = analyze_team(STARTERS).vulnerabilities

    assert electric.attacking_type is T.ELECTRIC
    assert electric.weak == ("charizard", "blastoise")
    assert electric.resists == ("venusaur",)
    assert electric.immune == ()


def test_immunity_counts_as_cover() -> None:
    ground = analyze_team(STARTERS).exposures[list(PokemonType).index(T.GROUND)]

    assert ground.immune == ("charizard",)
    assert not ground.is_unresisted


def test_unresisted_types() -> None:
    assert analyze_team(STARTERS).unresisted == (
        T.NORMAL, T.POISON, T.FLYING, T.PSYCHIC, T.ROCK, T.GHOST, T.DRAGON, T.DARK,
    )  # fmt: skip


def test_offensive_gaps_use_own_types_only() -> None:
    assert analyze_team(STARTERS).offensive_gaps == (
        T.NORMAL, T.ELECTRIC, T.POISON, T.FLYING, T.PSYCHIC, T.GHOST, T.DRAGON, T.DARK,
    )  # fmt: skip


def test_single_weak_member_is_not_a_vulnerability() -> None:
    analysis = analyze_team(Team(members=(GARCHOMP,)))

    assert analysis.vulnerabilities == ()
    ice = analysis.exposures[list(PokemonType).index(T.ICE)]
    assert ice.weak == ("garchomp",)


def test_weak_members_must_outnumber_cover() -> None:
    # Ice is 4x on both Dragon/Ground members; Blastoise resists it: 2 weak > 1 cover.
    analysis = analyze_team(Team(members=(GARCHOMP, FLYGON, BLASTOISE)))

    ice = next(e for e in analysis.vulnerabilities if e.attacking_type is T.ICE)
    assert ice.weak == ("garchomp", "flygon")
    assert ice.resists == ("blastoise",)


def test_equal_weak_and_cover_is_not_a_vulnerability() -> None:
    analysis = analyze_team(Team(members=(GARCHOMP, FLYGON, BLASTOISE, LAPRAS)))

    assert T.ICE not in [e.attacking_type for e in analysis.vulnerabilities]


def test_score_orders_by_vulnerabilities_then_exposure_then_coverage() -> None:
    assert analyze_team(STARTERS).score == (1, 2, 8, 8)
    worse = analyze_team(Team(members=(GARCHOMP, FLYGON, BLASTOISE)))
    assert worse.score > analyze_team(STARTERS).score


def test_to_dict_is_json_ready() -> None:
    data = analyze_team(STARTERS).to_dict()

    assert data["team"] == STARTERS.to_dict()
    assert data["vulnerabilities"] == [
        {
            "attacking_type": "electric",
            "weak": ["charizard", "blastoise"],
            "resists": ["venusaur"],
            "immune": [],
        }
    ]
    assert data["unresisted"][0] == "normal"
    assert len(data["exposures"]) == len(PokemonType)
