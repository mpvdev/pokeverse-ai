"""Tools that give the model read-only access to the Pokémon catalog."""

import re
from typing import Any

from pokeverse.catalog import PokemonCatalog, PokemonNotInCatalogError, UpstreamUnavailableError
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
    def get_pokemon(name_or_id: str) -> dict[str, Any]:
        try:
            return catalog.get(normalize_pokemon_identifier(name_or_id)).to_dict()
        except ValueError as error:
            return {"error": "invalid_identifier", "message": str(error)}
        except PokemonNotInCatalogError as error:
            return {"error": "not_found", "message": str(error)}
        except UpstreamUnavailableError as error:
            return {"error": "unavailable", "message": str(error)}

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
    )
