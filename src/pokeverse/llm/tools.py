"""Provider-neutral tool definitions for LLM tool calling."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Tool:
    """A function the model may ask the application to run.

    ``parameters`` is a JSON Schema object. Tools are sent in strict mode, so every
    property must be listed in ``required`` and ``additionalProperties`` must be false.
    ``handler`` receives the parsed arguments as keyword arguments and returns a
    JSON-serializable dict; domain failures should be returned as data, not raised.
    """

    name: str
    description: str
    parameters: Mapping[str, Any]
    handler: Callable[..., dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One tool invocation made while answering a prompt, kept for tracing."""

    name: str
    arguments: dict[str, Any]
    output: dict[str, Any]
