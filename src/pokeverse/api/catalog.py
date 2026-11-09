"""Catalog endpoints: Pokémon, learnsets and moves (local-first, PokéAPI on a miss)."""

from typing import Annotated

from fastapi import APIRouter, Query

from pokeverse.api.app import Catalogs, Identifier
from pokeverse.catalog import Move, Pokemon
from pokeverse.model import FrozenModel

router = APIRouter(tags=["catalog"])

Offline = Annotated[bool, Query(description="Only use the local catalog; never call PokéAPI.")]


class Learnset(FrozenModel):
    pokemon: str
    learnset: list[str]


@router.get("/pokemon", response_model=list[Pokemon])
def list_pokemon(catalogs: Catalogs) -> list[Pokemon]:
    """Pokémon stored in the local catalog, in Pokédex order (never calls PokéAPI)."""
    with catalogs(True) as catalog:
        return catalog.list_all()


@router.get("/pokemon/{name_or_id}", response_model=Pokemon)
def get_pokemon(name_or_id: Identifier, catalogs: Catalogs, offline: Offline = False) -> Pokemon:
    with catalogs(offline) as catalog:
        return catalog.get(name_or_id)


@router.get("/pokemon/{name_or_id}/learnset", response_model=Learnset)
def get_learnset(name_or_id: Identifier, catalogs: Catalogs, offline: Offline = False) -> Learnset:
    """Names of every move the Pokémon can learn (no move lookups)."""
    with catalogs(offline) as catalog:
        pokemon = catalog.get(name_or_id)
    return Learnset(pokemon=pokemon.name, learnset=sorted(pokemon.learnset))


@router.get("/moves/{name_or_id}", response_model=Move)
def get_move(name_or_id: Identifier, catalogs: Catalogs, offline: Offline = False) -> Move:
    with catalogs(offline) as catalog:
        return catalog.get_move(name_or_id)
