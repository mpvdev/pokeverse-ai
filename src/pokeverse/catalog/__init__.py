"""Domain models and services for the local Pokémon catalog."""

from pokeverse.catalog.models import Pokemon, PokemonType, parse_identifier
from pokeverse.catalog.repository import SqlitePokemonRepository
from pokeverse.catalog.service import (
    CatalogError,
    PokemonCatalog,
    PokemonNotInCatalogError,
    UpstreamUnavailableError,
)

__all__ = [
    "CatalogError",
    "Pokemon",
    "PokemonCatalog",
    "PokemonNotInCatalogError",
    "PokemonType",
    "SqlitePokemonRepository",
    "UpstreamUnavailableError",
    "parse_identifier",
]
