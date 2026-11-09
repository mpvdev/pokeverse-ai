from pokeverse.battles import Battler, matchup
from pokeverse.catalog import BaseStats, DamageClass, Move, Pokemon, PokemonType

T = PokemonType
D = DamageClass

EARTHQUAKE = Move(89, "earthquake", T.GROUND, D.PHYSICAL, 100, 100, 0, 10)
DRAGON_CLAW = Move(337, "dragon-claw", T.DRAGON, D.PHYSICAL, 80, 100, 0, 15)
THUNDERBOLT = Move(85, "thunderbolt", T.ELECTRIC, D.SPECIAL, 90, 100, 0, 15)
QUICK_ATTACK = Move(98, "quick-attack", T.NORMAL, D.PHYSICAL, 40, 100, 1, 30)
FLAMETHROWER = Move(53, "flamethrower", T.FIRE, D.SPECIAL, 90, 100, 0, 15)

LEARNSET = frozenset(
    move.name for move in (EARTHQUAKE, DRAGON_CLAW, THUNDERBOLT, QUICK_ATTACK, FLAMETHROWER)
)
GARCHOMP_SPECIES = Pokemon(
    445, "garchomp", (T.DRAGON, T.GROUND), BaseStats(108, 130, 95, 80, 85, 102), LEARNSET
)
PIKACHU_SPECIES = Pokemon(25, "pikachu", (T.ELECTRIC,), BaseStats(35, 55, 40, 50, 50, 90), LEARNSET)
CHARIZARD_SPECIES = Pokemon(
    6, "charizard", (T.FIRE, T.FLYING), BaseStats(78, 84, 78, 109, 85, 100), LEARNSET
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
