from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field

from pokeverse.llm import OutputSchema
from pokeverse.llm.structured import strict_json_schema
from pokeverse.model import FrozenModel


class Inner(FrozenModel):
    """Developer notes that must not reach the model."""

    kind: Literal["only"]
    tags: tuple[str, ...] = Field(max_length=2, description="Short tags.")


class Outer(FrozenModel):
    """Also private."""

    title: str = Field(description="A field named like a JSON Schema keyword.")
    inner: Inner = Field(description="The nested part.")
    items: tuple[Inner, ...]


def test_generated_schema_is_inlined_and_strict() -> None:
    assert strict_json_schema(Outer) == {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "A field named like a JSON Schema keyword."},
            "inner": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["only"]},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 2,
                        "description": "Short tags.",
                    },
                },
                "required": ["kind", "tags"],
                "additionalProperties": False,
                "description": "The nested part.",
            },
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["only"]},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 2,
                            "description": "Short tags.",
                        },
                    },
                    "required": ["kind", "tags"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["title", "inner", "items"],
        "additionalProperties": False,
    }


def test_from_model_wraps_the_generated_schema() -> None:
    schema = OutputSchema.from_model("outer", Outer)

    assert schema.name == "outer"
    assert schema.schema == strict_json_schema(Outer)


class WithDefault(FrozenModel):
    answer: str = "maybe"


class AllowsExtras(BaseModel):
    model_config = ConfigDict(extra="allow")

    answer: str


@pytest.mark.parametrize(
    ("model", "message"),
    [
        (WithDefault, "every property must be required"),
        (AllowsExtras, "must forbid extra properties"),
    ],
)
def test_models_strict_mode_would_reject_are_refused(model: type[BaseModel], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        strict_json_schema(model)
