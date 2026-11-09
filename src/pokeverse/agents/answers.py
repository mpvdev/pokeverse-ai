"""Structured answers returned by the Pokédex assistant."""

from enum import StrEnum
from typing import Any

from pydantic import Field

from pokeverse.catalog.models import Slug
from pokeverse.llm import OutputSchema
from pokeverse.model import FrozenModel, NonBlank


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PokedexAnswer(FrozenModel):
    """A validated answer; built from untrusted model output with ``parse_reply``."""

    answer: NonBlank = Field(description="Concise answer to the user's question, in plain prose.")
    pokemon: tuple[Slug, ...] = Field(
        description="Canonical lowercase slugs (e.g. 'pikachu', 'mr-mime') of every "
        "Pokémon the answer is about. Empty if none."
    )
    confidence: Confidence = Field(
        description="'high' only when every fact came from a tool result."
    )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


POKEDEX_ANSWER_SCHEMA = OutputSchema.from_model("pokedex_answer", PokedexAnswer)
