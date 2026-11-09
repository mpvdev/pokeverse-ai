"""Domain models and services for the Pokémon catalog (PokéAPI, synced to SQLite)."""

from pokeverse.catalog.models import (
    BaseStats,
    DamageClass,
    Move,
    Pokemon,
    PokemonEntry,
    PokemonIndex,
    PokemonType,
    parse_identifier,
)
from pokeverse.catalog.repository import SqlitePokemonRepository
from pokeverse.catalog.service import (
    CatalogError,
    MoveNotInCatalogError,
    PokemonCatalog,
    PokemonNotInCatalogError,
    PokemonSource,
    StaticSource,
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
    "PokemonEntry",
    "PokemonIndex",
    "PokemonNotInCatalogError",
    "PokemonSource",
    "PokemonType",
    "SqlitePokemonRepository",
    "StaticSource",
    "UpstreamUnavailableError",
    "parse_identifier",
]
