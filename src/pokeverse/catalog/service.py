"""Local-first Pokémon catalog with PokéAPI as an optional upstream."""

from typing import Protocol

from pokeverse.catalog.models import Pokemon, parse_identifier
from pokeverse.catalog.pokeapi import (
    PokeApiRateLimitedError,
    PokeApiResponseError,
    PokeApiUnavailableError,
    PokemonNotFoundError,
)
from pokeverse.catalog.repository import SqlitePokemonRepository


class PokemonSource(Protocol):
    """An upstream source of Pokémon reference data (e.g. ``PokeApiClient``)."""

    def fetch_pokemon(self, name_or_id: str | int) -> Pokemon: ...


class CatalogError(Exception):
    """Base class for catalog lookup errors."""


class PokemonNotInCatalogError(CatalogError):
    """The Pokémon is not stored locally and does not exist upstream."""


class UpstreamUnavailableError(CatalogError):
    """The Pokémon is not stored locally and the upstream could not provide it."""


class PokemonCatalog:
    """Reads Pokémon from local storage, importing from upstream on a miss.

    Stored data is always served without contacting the upstream, so previously
    imported Pokémon remain available during upstream outages. With
    ``source=None`` the catalog runs fully offline.
    """

    def __init__(
        self, repository: SqlitePokemonRepository, source: PokemonSource | None = None
    ) -> None:
        self._repository = repository
        self._source = source

    def get(self, name_or_id: str | int) -> Pokemon:
        identifier = parse_identifier(name_or_id)
        cached = (
            self._repository.get_by_id(identifier)
            if isinstance(identifier, int)
            else self._repository.get_by_name(identifier)
        )
        if cached is not None:
            return cached
        if self._source is None:
            raise PokemonNotInCatalogError(f"{identifier!r} is not in the local catalog")
        return self._import(identifier)

    def list_all(self) -> list[Pokemon]:
        return self._repository.list_all()

    def _import(self, identifier: str | int) -> Pokemon:
        assert self._source is not None
        try:
            pokemon = self._source.fetch_pokemon(identifier)
        except PokemonNotFoundError as error:
            raise PokemonNotInCatalogError(f"{identifier!r} does not exist") from error
        except (
            PokeApiUnavailableError,
            PokeApiRateLimitedError,
            PokeApiResponseError,
        ) as error:
            raise UpstreamUnavailableError(
                f"{identifier!r} is not cached locally and the upstream failed: {error}"
            ) from error
        self._repository.save(pokemon)
        return pokemon
