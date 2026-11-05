from typing import Any

import pytest

from pokeverse.agents import POKEDEX_ANSWER_SCHEMA, Confidence, PokedexAnswer

VALID = {"answer": "Mr. Mime is Psychic/Fairy.", "pokemon": ["mr-mime"], "confidence": "high"}


def test_from_dict_builds_validated_answer() -> None:
    answer = PokedexAnswer.from_dict(VALID)

    assert answer == PokedexAnswer("Mr. Mime is Psychic/Fairy.", ("mr-mime",), Confidence.HIGH)
    assert answer.to_dict() == VALID


@pytest.mark.parametrize(
    "overrides",
    [
        {"answer": "   "},
        {"answer": 42},
        {"pokemon": "mr-mime"},
        {"pokemon": ["Mr. Mime"]},
        {"pokemon": [25]},
        {"confidence": "certain"},
    ],
)
def test_from_dict_rejects_invalid_data(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        PokedexAnswer.from_dict({**VALID, **overrides})


def test_from_dict_rejects_missing_field() -> None:
    with pytest.raises(ValueError, match="confidence"):
        PokedexAnswer.from_dict({"answer": "hi", "pokemon": []})


def test_schema_is_strict_mode_compatible() -> None:
    schema = POKEDEX_ANSWER_SCHEMA.schema

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["confidence"]["enum"] == ["high", "medium", "low"]
