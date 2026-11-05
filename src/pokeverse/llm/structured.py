"""Provider-neutral structured-output definitions."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class OutputSchema:
    """JSON Schema the model's final reply must match.

    Sent in strict mode: every object needs ``additionalProperties: false`` and all
    properties listed in ``required``.
    """

    name: str
    schema: Mapping[str, Any]
