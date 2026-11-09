"""Catalog endpoints: Pokémon, learnsets and moves, always read from PokéAPI."""

from typing import Annotated

from fastapi import APIRouter, Query

from pokeverse.api.app import Catalogs, Identifier
from pokeverse.catalog import Move, Pokemon, PokemonIndex
from pokeverse.model import FrozenModel

router = APIRouter(tags=["catalog"])

MAX_PAGE_SIZE = 100


class Learnset(FrozenModel):
    pokemon: str
    learnset: list[str]


@router.get("/pokemon", response_model=PokemonIndex)
def list_pokemon(
    catalogs: Catalogs,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PokemonIndex:
    """One page of every Pokémon on PokéAPI, in Pokédex order (names and ids only)."""
    with catalogs() as catalog:
        return catalog.index(limit, offset)


@router.get("/pokemon/{name_or_id}", response_model=Pokemon)
def get_pokemon(name_or_id: Identifier, catalogs: Catalogs) -> Pokemon:
    with catalogs() as catalog:
        return catalog.get(name_or_id)


@router.get("/pokemon/{name_or_id}/learnset", response_model=Learnset)
def get_learnset(name_or_id: Identifier, catalogs: Catalogs) -> Learnset:
    """Names of every move the Pokémon can learn (no move lookups)."""
    with catalogs() as catalog:
        pokemon = catalog.get(name_or_id)
    return Learnset(pokemon=pokemon.name, learnset=sorted(pokemon.learnset))


@router.get("/moves/{name_or_id}", response_model=Move)
def get_move(name_or_id: Identifier, catalogs: Catalogs) -> Move:
    with catalogs() as catalog:
        return catalog.get_move(name_or_id)
