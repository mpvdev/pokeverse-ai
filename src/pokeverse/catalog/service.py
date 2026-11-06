"""Local-first Pokémon catalog with PokéAPI as an optional upstream."""

from collections.abc import Callable
from typing import Protocol

from pokeverse.catalog.models import Move, Pokemon, parse_identifier
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

    def fetch_move(self, name_or_id: str | int) -> Move: ...


class CatalogError(Exception):
    """Base class for catalog lookup errors."""


class PokemonNotInCatalogError(CatalogError):
    """The Pokémon is not stored locally and does not exist upstream."""


class MoveNotInCatalogError(CatalogError):
    """The move is not stored locally and does not exist upstream."""


class UpstreamUnavailableError(CatalogError):
    """The record is not stored locally and the upstream could not provide it."""


class PokemonCatalog:
    """Reads Pokémon and moves from local storage, importing from upstream on a miss.

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
        pokemon = self._fetch(self._source.fetch_pokemon, identifier, PokemonNotInCatalogError)
        self._repository.save(pokemon)
        return pokemon

    def get_move(self, name_or_id: str | int) -> Move:
        identifier = parse_identifier(name_or_id)
        cached = (
            self._repository.get_move_by_id(identifier)
            if isinstance(identifier, int)
            else self._repository.get_move_by_name(identifier)
        )
        if cached is not None:
            return cached
        if self._source is None:
            raise MoveNotInCatalogError(f"move {identifier!r} is not in the local catalog")
        move = self._fetch(self._source.fetch_move, identifier, MoveNotInCatalogError)
        self._repository.save_move(move)
        return move

    def list_all(self) -> list[Pokemon]:
        return self._repository.list_all()

    @staticmethod
    def _fetch[T](
        fetch: Callable[[str | int], T],
        identifier: str | int,
        not_found: type[CatalogError],
    ) -> T:
        """Call the upstream, translating its errors into catalog errors."""
        try:
            return fetch(identifier)
        except PokemonNotFoundError as error:
            raise not_found(f"{identifier!r} does not exist") from error
        except (
            PokeApiUnavailableError,
            PokeApiRateLimitedError,
            PokeApiResponseError,
        ) as error:
            raise UpstreamUnavailableError(
                f"{identifier!r} is not cached locally and the upstream failed: {error}"
            ) from error
