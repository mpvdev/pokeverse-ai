"""A Pokémon prepared for battle: the species plus the moves it will use."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pokeverse.catalog import DamageClass, Move, Pokemon, PokemonCatalog

MAX_MOVES = 4


@dataclass(frozen=True, slots=True)
class Battler:
    """An immutable battler with 1-4 distinct, learnable, power-based damaging moves."""

    pokemon: Pokemon
    moves: tuple[Move, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.pokemon, Pokemon):
            raise ValueError("pokemon must be a Pokemon")
        if not isinstance(self.moves, tuple) or not all(isinstance(m, Move) for m in self.moves):
            raise ValueError("moves must be a tuple of Move")
        if not 1 <= len(self.moves) <= MAX_MOVES:
            raise ValueError(f"a battler must have between 1 and {MAX_MOVES} moves")
        names = [move.name for move in self.moves]
        if len(set(names)) != len(names):
            raise ValueError("moves must not contain duplicates")
        unlearnable = [name for name in names if name not in self.pokemon.learnset]
        if unlearnable:
            raise ValueError(f"{self.pokemon.name} cannot learn: {', '.join(unlearnable)}")
        unsupported = [
            move.name
            for move in self.moves
            if move.damage_class is DamageClass.STATUS or move.power is None
        ]
        if unsupported:
            raise ValueError(
                f"only moves with a fixed power are supported in battle: {', '.join(unsupported)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "pokemon": self.pokemon.to_dict(),
            "moves": [move.to_dict() for move in self.moves],
        }


def load_battler(catalog: PokemonCatalog, pokemon: str | int, moves: Sequence[str]) -> Battler:
    """Resolve a battler through the catalog, checking the learnset before fetching any move."""
    if not 1 <= len(moves) <= MAX_MOVES:
        raise ValueError(f"a battler must have between 1 and {MAX_MOVES} moves")
    species = catalog.get(pokemon)
    unlearnable = [name for name in moves if name not in species.learnset]
    if unlearnable:
        raise ValueError(f"{species.name} cannot learn: {', '.join(unlearnable)}")
    return Battler(species, tuple(catalog.get_move(name) for name in moves))
