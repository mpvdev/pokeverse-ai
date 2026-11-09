from pokeverse.battles import Battler, matchup
from pokeverse.catalog import BaseStats, DamageClass, Move, Pokemon, PokemonType

T = PokemonType
D = DamageClass

EARTHQUAKE = Move(
    move_id=89,
    name="earthquake",
    type=T.GROUND,
    damage_class=D.PHYSICAL,
    power=100,
    accuracy=100,
    priority=0,
    pp=10,
)
DRAGON_CLAW = Move(
    move_id=337,
    name="dragon-claw",
    type=T.DRAGON,
    damage_class=D.PHYSICAL,
    power=80,
    accuracy=100,
    priority=0,
    pp=15,
)
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

LEARNSET = frozenset(
    move.name for move in (EARTHQUAKE, DRAGON_CLAW, THUNDERBOLT, QUICK_ATTACK, FLAMETHROWER)
)
GARCHOMP_SPECIES = Pokemon(
    pokedex_id=445,
    name="garchomp",
    types=(T.DRAGON, T.GROUND),
    stats=BaseStats(
        hp=108, attack=130, defense=95, special_attack=80, special_defense=85, speed=102
    ),
    learnset=LEARNSET,
)
PIKACHU_SPECIES = Pokemon(
    pokedex_id=25,
    name="pikachu",
    types=(T.ELECTRIC,),
    stats=BaseStats(hp=35, attack=55, defense=40, special_attack=50, special_defense=50, speed=90),
    learnset=LEARNSET,
)
CHARIZARD_SPECIES = Pokemon(
    pokedex_id=6,
    name="charizard",
    types=(T.FIRE, T.FLYING),
    stats=BaseStats(
        hp=78, attack=84, defense=78, special_attack=109, special_defense=85, speed=100
    ),
    learnset=LEARNSET,
)

GARCHOMP = Battler(GARCHOMP_SPECIES, (EARTHQUAKE, DRAGON_CLAW))
EARTHQUAKE_ONLY = Battler(GARCHOMP_SPECIES, (EARTHQUAKE,))
PIKACHU = Battler(PIKACHU_SPECIES, (THUNDERBOLT, QUICK_ATTACK))
CHARIZARD = Battler(CHARIZARD_SPECIES, (FLAMETHROWER,))


def test_matchup_uses_each_sides_best_move_and_minimum_rolls() -> None:
    result = matchup(GARCHOMP, PIKACHU)

    assert (result.move, result.damage) == (EARTHQUAKE, (284, 336))
    assert result.reply == QUICK_ATTACK
    assert result.hits_to_ko == 1
    assert result.hits_to_be_ko == 17
    assert result.moves_first is False
    assert result.wins


def test_a_side_that_cannot_hurt_never_wins() -> None:
    stuck = matchup(EARTHQUAKE_ONLY, CHARIZARD)

    assert stuck.damage == (0, 0)
    assert stuck.hits_to_ko is None
    assert not stuck.wins
    assert matchup(CHARIZARD, EARTHQUAKE_ONLY).wins


def test_equal_hit_counts_go_to_whoever_moves_first() -> None:
    mirror = matchup(PIKACHU, PIKACHU)

    assert mirror.moves_first is None
    assert mirror.hits_to_ko == mirror.hits_to_be_ko
    assert not mirror.wins


def test_describe_and_to_dict() -> None:
    result = matchup(GARCHOMP, PIKACHU)

    assert result.describe() == (
        "Garchomp vs Pikachu: Garchomp's Earthquake 258%-305%, KO in 1 hit; "
        "Pikachu's Quick Attack 6%-7%, KO in 17 hits; Pikachu moves first; "
        "one-on-one: Garchomp wins."
    )
    assert result.to_dict()["wins"] is True
    assert "no effect, KO in never" in matchup(EARTHQUAKE_ONLY, CHARIZARD).describe()
