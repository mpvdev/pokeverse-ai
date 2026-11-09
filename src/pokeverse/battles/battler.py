"""A Pokémon prepared for battle: the species plus the moves it will use."""

from collections.abc import Sequence
from typing import Any, Self

from pydantic import field_validator, model_validator

from pokeverse.catalog import DamageClass, Move, Pokemon, PokemonCatalog
from pokeverse.model import FrozenModel

MAX_MOVES = 4

UNMODELLED_MOVES = frozenset(
    {
        "explosion",
        "self-destruct",
        "misty-explosion",
        "hyper-beam",
        "giga-impact",
        "blast-burn",
        "frenzy-plant",
        "hydro-cannon",
        "rock-wrecker",
        "roar-of-time",
        "prismatic-laser",
        "eternabeam",
        "meteor-assault",
        "solar-beam",
        "solar-blade",
        "fly",
        "dig",
        "dive",
        "bounce",
        "phantom-force",
        "shadow-force",
        "sky-attack",
        "skull-bash",
        "razor-wind",
        "freeze-shock",
        "ice-burn",
        "meteor-beam",
        "electro-shot",
        "sky-drop",
        "focus-punch",
        "future-sight",
        "doom-desire",
        "dream-eater",
        "fake-out",
        "first-impression",
        "last-resort",
        "belch",
        "snore",
        "sucker-punch",
        "synchronoise",
        "steel-roller",
        "poltergeist",
        "burn-up",
        "water-spout",
        "eruption",
        "dragon-energy",
        "steel-beam",
        "mind-blown",
        "chloroblast",
        "foul-play",
        "body-press",
    }
)


def is_battle_move(move: Move) -> bool:
    """Power-based damage whose drawback, if any, the engine can fairly ignore."""
    return (
        move.damage_class is not DamageClass.STATUS
        and move.power is not None
        and move.name not in UNMODELLED_MOVES
    )


class Battler(FrozenModel):
    """An immutable battler with 1-4 distinct, learnable moves that the engine supports."""

    pokemon: Pokemon
    moves: tuple[Move, ...]

    @field_validator("moves")
    @classmethod
    def _distinct_moves(cls, moves: tuple[Move, ...]) -> tuple[Move, ...]:
        if not 1 <= len(moves) <= MAX_MOVES:
            raise ValueError(f"a battler must have between 1 and {MAX_MOVES} moves")
        names = [move.name for move in moves]
        if len(set(names)) != len(names):
            raise ValueError("moves must not contain duplicates")
        return moves

    @model_validator(mode="after")
    def _usable_moves(self) -> Self:
        names = [move.name for move in self.moves]
        unlearnable = [name for name in names if name not in self.pokemon.learnset]
        if unlearnable:
            raise ValueError(f"{self.pokemon.name} cannot learn: {', '.join(unlearnable)}")
        unsupported = [move.name for move in self.moves if not is_battle_move(move)]
        if unsupported:
            raise ValueError(
                f"moves not supported in battle: {', '.join(unsupported)} (status, fixed-damage, "
                "self-KO, recharge, charge-turn and conditional moves are not modelled)"
            )
        return self

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
    return Battler(pokemon=species, moves=tuple(catalog.get_move(name) for name in moves))
