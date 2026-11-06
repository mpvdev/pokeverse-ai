"""HTTP client for the upstream PokéAPI (https://pokeapi.co).

PokéAPI is a reference data *source*, not a runtime dependency: callers should
read from the local catalog and use this client only to import data.
"""

from collections.abc import Mapping
from importlib.metadata import version
from types import TracebackType
from typing import Any, Self

import httpx

from pokeverse.catalog.models import BaseStats, Pokemon, PokemonType, parse_identifier

DEFAULT_BASE_URL = "https://pokeapi.co/api/v2"
DEFAULT_TIMEOUT_SECONDS = 10.0


class PokeApiError(Exception):
    """Base class for all PokéAPI client errors."""


class PokemonNotFoundError(PokeApiError):
    """The requested Pokémon does not exist upstream."""


class PokeApiUnavailableError(PokeApiError):
    """PokéAPI could not be reached or returned a server error."""


class PokeApiRateLimitedError(PokeApiError):
    """PokéAPI rejected the request because of rate limiting."""


class PokeApiResponseError(PokeApiError):
    """PokéAPI returned an unexpected status or a malformed payload."""


def parse_pokemon(payload: Mapping[str, Any]) -> Pokemon:
    """Map a PokéAPI ``/pokemon/{id}`` payload to a validated ``Pokemon``.

    Types are ordered by slot. Non-elemental types that are not part of
    ``PokemonType`` (e.g. ``stellar``) are skipped. All six base stats are required.
    """
    try:
        type_entries = sorted(payload["types"], key=lambda entry: entry["slot"])
        types = tuple(
            PokemonType(entry["type"]["name"])
            for entry in type_entries
            if entry["type"]["name"] in PokemonType
        )
        base = {entry["stat"]["name"]: entry["base_stat"] for entry in payload["stats"]}
        stats = BaseStats(
            hp=base["hp"],
            attack=base["attack"],
            defense=base["defense"],
            special_attack=base["special-attack"],
            special_defense=base["special-defense"],
            speed=base["speed"],
        )
        return Pokemon(pokedex_id=payload["id"], name=payload["name"], types=types, stats=stats)
    except (KeyError, TypeError, ValueError) as error:
        raise PokeApiResponseError(f"Malformed Pokémon payload: {error}") from error


class PokeApiClient:
    """Synchronous PokéAPI client.

    Use as a context manager, or call ``close()`` when finished. Pass a custom
    ``transport`` (e.g. ``httpx.MockTransport``) to avoid real network calls in tests.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={
                "User-Agent": (
                    f"pokeverse-ai/{version('pokeverse-ai')} "
                    "(+https://github.com/mpvdev/pokeverse-ai)"
                ),
                "Accept": "application/json",
            },
        )

    def fetch_pokemon(self, name_or_id: str | int) -> Pokemon:
        """Fetch a single Pokémon by name (e.g. ``"Pikachu"``) or Pokédex id."""
        identifier = parse_identifier(name_or_id)
        return parse_pokemon(self._get_json(f"/pokemon/{identifier}"))

    def _get_json(self, path: str) -> Mapping[str, Any]:
        try:
            response = self._client.get(path)
        except httpx.TimeoutException as error:
            raise PokeApiUnavailableError(f"PokéAPI request timed out: {path}") from error
        except httpx.TransportError as error:
            raise PokeApiUnavailableError(f"Could not reach PokéAPI: {error}") from error

        status = response.status_code
        if status == httpx.codes.NOT_FOUND:
            raise PokemonNotFoundError(f"Not found on PokéAPI: {path}")
        if status == httpx.codes.TOO_MANY_REQUESTS:
            raise PokeApiRateLimitedError("PokéAPI rate limit exceeded")
        if status >= 500:
            raise PokeApiUnavailableError(f"PokéAPI server error {status}: {path}")
        if status != httpx.codes.OK:
            raise PokeApiResponseError(f"Unexpected PokéAPI status {status}: {path}")

        try:
            payload = response.json()
        except ValueError as error:
            raise PokeApiResponseError(f"PokéAPI returned invalid JSON: {path}") from error
        if not isinstance(payload, Mapping):
            raise PokeApiResponseError(f"PokéAPI returned a non-object payload: {path}")
        return payload

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
