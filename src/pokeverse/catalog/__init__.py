"""Domain models and services for the local Pokémon catalog."""

from pokeverse.catalog.models import (
    BaseStats,
    DamageClass,
    Move,
    Pokemon,
    PokemonType,
    parse_identifier,
)
from pokeverse.catalog.repository import SqlitePokemonRepository
from pokeverse.catalog.service import (
    CatalogError,
    MoveNotInCatalogError,
    PokemonCatalog,
    PokemonNotInCatalogError,
    UpstreamUnavailableError,
)

__all__ = [
    "BaseStats",
    "CatalogError",
    "DamageClass",
    "Move",
    "MoveNotInCatalogError",
    "Pokemon",
    "PokemonCatalog",
    "PokemonNotInCatalogError",
    "PokemonType",
    "SqlitePokemonRepository",
    "UpstreamUnavailableError",
    "parse_identifier",
]
