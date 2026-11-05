"""Structured answers returned by the Pokédex assistant."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pokeverse.catalog.models import NAME_PATTERN
from pokeverse.llm import OutputSchema


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


POKEDEX_ANSWER_SCHEMA = OutputSchema(
    name="pokedex_answer",
    schema={
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "description": "Concise answer to the user's question, in plain prose.",
            },
            "pokemon": {
                "type": "array",
                "description": "Canonical lowercase slugs (e.g. 'pikachu', 'mr-mime') of every "
                "Pokémon the answer is about. Empty if none.",
                "items": {"type": "string", "pattern": f"^{NAME_PATTERN.pattern}$"},
            },
            "confidence": {
                "type": "string",
                "enum": [level.value for level in Confidence],
                "description": "'high' only when every fact came from a tool result.",
            },
        },
        "required": ["answer", "pokemon", "confidence"],
        "additionalProperties": False,
    },
)


@dataclass(frozen=True, slots=True)
class PokedexAnswer:
    """A validated answer; built from untrusted model output via ``from_dict``."""

    answer: str
    pokemon: tuple[str, ...]
    confidence: Confidence

    def __post_init__(self) -> None:
        if not isinstance(self.answer, str) or not self.answer.strip():
            raise ValueError("answer must be a non-empty string")
        if not isinstance(self.pokemon, tuple) or not all(
            isinstance(name, str) and NAME_PATTERN.fullmatch(name) for name in self.pokemon
        ):
            raise ValueError("pokemon must be a tuple of canonical slugs")
        if not isinstance(self.confidence, Confidence):
            raise ValueError("confidence must be a Confidence value")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PokedexAnswer:
        try:
            pokemon = data["pokemon"]
            if not isinstance(pokemon, list):
                raise ValueError("pokemon must be a list")
            return cls(
                answer=data["answer"],
                pokemon=tuple(pokemon),
                confidence=Confidence(data["confidence"]),
            )
        except KeyError as error:
            raise ValueError(f"missing field {error}") from error

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "pokemon": list(self.pokemon),
            "confidence": self.confidence.value,
        }
