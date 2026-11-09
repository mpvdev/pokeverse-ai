"""Deterministic default movesets: the strongest move first, then type coverage."""

from collections.abc import Iterable

from pokeverse.battles.battler import MAX_MOVES, Battler, is_battle_move
from pokeverse.battles.stats import battle_stats
from pokeverse.catalog import (
    DamageClass,
    Move,
    Pokemon,
    PokemonCatalog,
    PokemonType,
)
from pokeverse.catalog.type_chart import effectiveness

STAB = 1.5


def move_score(pokemon: Pokemon, move: Move) -> float:
    """Power x accuracy x STAB x the attacker's matching attack stat."""
    stats = battle_stats(pokemon.stats)
    attack = stats.attack if move.damage_class is DamageClass.PHYSICAL else stats.special_attack
    stab = STAB if move.type in pokemon.types else 1.0
    return (move.power or 0) * (move.accuracy or 100) / 100 * stab * attack


def super_effective_against(types: Iterable[PokemonType]) -> frozenset[PokemonType]:
    attacking = tuple(types)
    return frozenset(
        defending
        for defending in PokemonType
        if any(effectiveness(attack, (defending,)) > 1 for attack in attacking)
    )


def choose_moveset(pokemon: Pokemon, moves: Iterable[Move]) -> tuple[Move, ...]:
    """Up to 4 learnable battle moves: the best-scoring one, then the best that add coverage."""
    candidates = sorted(
        {
            move.name: move
            for move in moves
            if is_battle_move(move) and move.name in pokemon.learnset
        }.values(),
        key=lambda move: (-move_score(pokemon, move), move.name),
    )
    chosen: list[Move] = candidates[:1]
    candidates = candidates[1:]
    while candidates and len(chosen) < MAX_MOVES:
        covered = super_effective_against(move.type for move in chosen)
        used_types = {move.type for move in chosen}
        pool = [move for move in candidates if move.type not in used_types] or candidates
        best = max(
            pool,
            key=lambda move: (
                bool(super_effective_against((move.type,)) - covered),
                move_score(pokemon, move),
            ),
        )
        chosen.append(best)
        candidates.remove(best)
    return tuple(chosen)


def default_battler(catalog: PokemonCatalog, pokemon: str | int) -> Battler:
    """A battler with the default moveset; needs every learnable move (fetched once, cached)."""
    species = catalog.get(pokemon)
    moves = [catalog.get_move(name) for name in sorted(species.learnset)]
    chosen = choose_moveset(species, moves)
    if not chosen:
        raise ValueError(f"{species.name} has no moves usable in battle")
    return Battler(pokemon=species, moves=chosen)
