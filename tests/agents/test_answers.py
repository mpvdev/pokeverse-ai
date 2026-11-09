from typing import Any

import pytest

from pokeverse.agents import POKEDEX_ANSWER_SCHEMA, Confidence, PokedexAnswer
from pokeverse.llm import Completion, LlmRequestError, parse_reply

VALID = {"answer": "Mr. Mime is Psychic/Fairy.", "pokemon": ["mr-mime"], "confidence": "high"}


def reply(data: dict[str, Any]) -> Completion:
    return Completion("", "fake", "completed", 10, 5, 7, (), data)


def test_parse_reply_builds_validated_answer() -> None:
    answer = parse_reply(PokedexAnswer, reply(VALID))

    assert answer == PokedexAnswer(
        answer="Mr. Mime is Psychic/Fairy.", pokemon=("mr-mime",), confidence=Confidence.HIGH
    )
    assert answer.to_dict() == VALID


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"answer": "   "}, "answer"),
        ({"answer": 42}, "answer"),
        ({"pokemon": "mr-mime"}, "pokemon"),
        ({"pokemon": ["Mr. Mime"]}, "pokemon.0"),
        ({"pokemon": [25]}, "pokemon.0"),
        ({"confidence": "certain"}, "confidence"),
        ({"extra": 1}, "extra"),
    ],
)
def test_parse_reply_rejects_invalid_data(overrides: dict[str, Any], field: str) -> None:
    completion = reply({**VALID, **overrides})

    with pytest.raises(LlmRequestError, match=f"failed validation: {field}:") as excinfo:
        parse_reply(PokedexAnswer, completion)
    assert excinfo.value.completion is completion


def test_parse_reply_rejects_missing_field() -> None:
    with pytest.raises(LlmRequestError, match="confidence: Field required"):
        parse_reply(PokedexAnswer, reply({"answer": "hi", "pokemon": []}))


def test_schema_is_strict_mode_compatible() -> None:
    schema = POKEDEX_ANSWER_SCHEMA.schema

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["confidence"]["enum"] == ["high", "medium", "low"]
