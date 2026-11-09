"""Pokémon catalog that always reads from PokéAPI and syncs what it reads to SQLite."""

from collections.abc import Callable, Iterable
from typing import Protocol

from pokeverse.catalog.models import Move, Pokemon, PokemonEntry, PokemonIndex, parse_identifier
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

    def fetch_index(self, limit: int, offset: int) -> PokemonIndex: ...


class CatalogError(Exception):
    """Base class for catalog lookup errors."""


class PokemonNotInCatalogError(CatalogError):
    """The Pokémon does not exist upstream."""


class MoveNotInCatalogError(CatalogError):
    """The move does not exist upstream."""


class UpstreamUnavailableError(CatalogError):
    """The upstream could not provide the record (outage, rate limit, bad payload)."""


class StaticSource:
    """A fixed, in-memory ``PokemonSource`` (tests and demos); unknown records are 404s."""

    def __init__(self, pokemon: Iterable[Pokemon] = (), moves: Iterable[Move] = ()) -> None:
        self._pokemon = {key: p for p in pokemon for key in (p.name, p.pokedex_id)}
        self._moves = {key: m for m in moves for key in (m.name, m.move_id)}

    def fetch_pokemon(self, name_or_id: str | int) -> Pokemon:
        if name_or_id not in self._pokemon:
            raise PokemonNotFoundError(f"Not found: {name_or_id}")
        return self._pokemon[name_or_id]

    def fetch_move(self, name_or_id: str | int) -> Move:
        if name_or_id not in self._moves:
            raise PokemonNotFoundError(f"Not found: move {name_or_id}")
        return self._moves[name_or_id]

    def fetch_index(self, limit: int, offset: int) -> PokemonIndex:
        entries = sorted({p.pokedex_id: p for p in self._pokemon.values()}.items())
        return PokemonIndex(
            count=len(entries),
            results=tuple(
                PokemonEntry(pokedex_id=pokedex_id, name=p.name)
                for pokedex_id, p in entries[offset : offset + limit]
            ),
        )


class PokemonCatalog:
    """Fetches Pokémon and moves from the upstream on every new lookup and syncs them to SQLite.

    SQLite is a write-only mirror: it is never read here, so an upstream outage fails the
    lookup (``UpstreamUnavailableError``). Within one catalog instance (one API request or
    one CLI command) each record is fetched once and then reused, so a battle that needs
    the same move many times does not refetch it.
    """

    def __init__(self, repository: SqlitePokemonRepository, source: PokemonSource) -> None:
        self._repository = repository
        self._source = source
        self._pokemon: dict[str | int, Pokemon] = {}
        self._moves: dict[str | int, Move] = {}

    def get(self, name_or_id: str | int) -> Pokemon:
        identifier = parse_identifier(name_or_id)
        if identifier not in self._pokemon:
            pokemon = self._fetch(
                lambda: self._source.fetch_pokemon(identifier), identifier, PokemonNotInCatalogError
            )
            self._repository.save(pokemon)
            self._pokemon[pokemon.name] = self._pokemon[pokemon.pokedex_id] = pokemon
            self._pokemon[identifier] = pokemon
        return self._pokemon[identifier]

    def get_move(self, name_or_id: str | int) -> Move:
        identifier = parse_identifier(name_or_id)
        if identifier not in self._moves:
            move = self._fetch(
                lambda: self._source.fetch_move(identifier), identifier, MoveNotInCatalogError
            )
            self._repository.save_move(move)
            self._moves[move.name] = self._moves[move.move_id] = move
            self._moves[identifier] = move
        return self._moves[identifier]

    def index(self, limit: int, offset: int = 0) -> PokemonIndex:
        """One page of every Pokémon the upstream knows (names and ids only)."""
        return self._fetch(
            lambda: self._source.fetch_index(limit, offset), "the Pokémon index", CatalogError
        )

    @staticmethod
    def _fetch[T](
        fetch: Callable[[], T],
        identifier: str | int,
        not_found: type[CatalogError],
    ) -> T:
        """Call the upstream, translating its errors into catalog errors."""
        try:
            return fetch()
        except PokemonNotFoundError as error:
            raise not_found(f"{identifier!r} does not exist") from error
        except (
            PokeApiUnavailableError,
            PokeApiRateLimitedError,
            PokeApiResponseError,
        ) as error:
            raise UpstreamUnavailableError(
                f"PokéAPI could not provide {identifier!r}: {error}"
            ) from error
