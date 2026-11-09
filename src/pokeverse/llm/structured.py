"""Provider-neutral structured-output definitions."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

DROPPED_KEYWORDS = frozenset({"title", "default"})


@dataclass(frozen=True, slots=True)
class OutputSchema:
    """JSON Schema the model's final reply must match.

    Sent in strict mode: every object needs ``additionalProperties: false`` and all
    properties listed in ``required``.
    """

    name: str
    schema: Mapping[str, Any]

    @classmethod
    def from_model(cls, name: str, model: type[BaseModel]) -> OutputSchema:
        """The model's JSON Schema, inlined and checked against strict-mode rules."""
        return cls(name=name, schema=strict_json_schema(model))


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Inline ``$ref``s, drop titles, defaults and class docstrings, turn ``const`` into ``enum``.

    Field descriptions are kept: they are instructions to the model. Raises ``ValueError`` if an
    object allows extra properties or has optional fields, since strict mode would reject it.
    """
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})
    schema.pop("description", None)

    def resolve(node: Any) -> Any:
        if isinstance(node, list):
            return [resolve(item) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            target = definitions[node["$ref"].rsplit("/", 1)[1]]
            target = {k: v for k, v in target.items() if k != "description"}
            node = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
        result = {
            key: (
                {name: resolve(child) for name, child in value.items()}
                if key == "properties"
                else resolve(value)
            )
            for key, value in node.items()
            if key not in DROPPED_KEYWORDS
        }
        if "const" in result:
            result["enum"] = [result.pop("const")]
        if result.get("type") == "object":
            if result.get("additionalProperties") is not False:
                raise ValueError(f"{model.__name__}: objects must forbid extra properties")
            if set(result.get("required", ())) != set(result.get("properties", {})):
                raise ValueError(f"{model.__name__}: every property must be required")
        return result

    return resolve(schema)
