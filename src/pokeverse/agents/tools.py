"""Tools that give the model read-only access to the Pokémon catalog."""

import re
from typing import Any

from pokeverse.catalog import (
    Pokemon,
    PokemonCatalog,
    PokemonNotInCatalogError,
    UpstreamUnavailableError,
)
from pokeverse.catalog.type_chart import defensive_profile
from pokeverse.llm import Tool

_APOSTROPHES = re.compile(r"['’]")
_SEPARATORS = re.compile(r"[^a-z0-9]+")

GET_POKEMON_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name_or_id": {
            "type": "string",
            "description": "Pokémon name (e.g. 'Pikachu', 'Mr. Mime') or National Pokédex number "
            "(e.g. '25').",
        }
    },
    "required": ["name_or_id"],
    "additionalProperties": False,
}


def normalize_pokemon_identifier(raw: str) -> str | int:
    """Turn free-form model input into a catalog identifier.

    ``"Mr. Mime"`` -> ``"mr-mime"``, ``"Farfetch'd"`` -> ``"farfetchd"``, ``"#025"`` -> ``25``.
    """
    text = raw.strip().lower().removeprefix("#")
    if text.isdigit():
        return int(text)
    return _SEPARATORS.sub("-", _APOSTROPHES.sub("", text)).strip("-")


def make_catalog_tools(catalog: PokemonCatalog) -> tuple[Tool, ...]:
    def lookup(name_or_id: str) -> Pokemon | dict[str, Any]:
        """The Pokémon, or an error object the model can explain."""
        try:
            return catalog.get(normalize_pokemon_identifier(name_or_id))
        except ValueError as error:
            return {"error": "invalid_identifier", "message": str(error)}
        except PokemonNotInCatalogError as error:
            return {"error": "not_found", "message": str(error)}
        except UpstreamUnavailableError as error:
            return {"error": "unavailable", "message": str(error)}

    def get_pokemon(name_or_id: str) -> dict[str, Any]:
        found = lookup(name_or_id)
        return found.to_dict() if isinstance(found, Pokemon) else found

    def get_type_matchups(name_or_id: str) -> dict[str, Any]:
        found = lookup(name_or_id)
        if not isinstance(found, Pokemon):
            return found
        return {"pokemon": found.to_dict(), **defensive_profile(found.types)}

    return (
        Tool(
            name="get_pokemon",
            description=(
                "Look up a Pokémon in the PokéVerse catalog. Returns its National Pokédex "
                "number, canonical name and elemental types, or an error object. Use it for "
                "any question about a specific Pokémon's types or Pokédex number instead of "
                "answering from memory."
            ),
            parameters=GET_POKEMON_PARAMETERS,
            handler=get_pokemon,
        ),
        Tool(
            name="get_type_matchups",
            description=(
                "Compute how attacking move types affect a Pokémon, using the official type "
                "chart (Generation 6+). Returns the Pokémon plus `weak_to`, `resists` and "
                "`immune_to`, each mapping attacking type to its damage multiplier (types not "
                "listed deal 1x). Use it for any question about weaknesses, resistances, "
                "immunities or whether a move type is effective; never work these out from "
                "memory."
            ),
            parameters=GET_POKEMON_PARAMETERS,
            handler=get_type_matchups,
        ),
    )
